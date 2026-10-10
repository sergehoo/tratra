"""Tableau de bord unifié : client seul, artisan seul, compte mixte, création du profil pro."""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from handy.models import Booking, HandymanProfile, Review, User
from handy.test_eligibility import artisan, service
from handy.testing import make_eligible

pytestmark = pytest.mark.django_db
URL = "/handy/me/dashboard/"


def client_user(name="cli", **extra):
    return User.objects.create_user(username=name, email=f"{name}@x.test", password="pass1234",
                                    user_type="client", first_name="Aya", last_name="Konan", **extra)


def api(user=None):
    c = APIClient()
    if user:
        c.force_authenticate(user)
    return c


def book(client, svc, status="pending", days=2):
    return Booking.objects.create(
        client=client, handyman=svc.handyman, service=svc, status=status, city="Abidjan",
        booking_date=timezone.now() + timedelta(days=days), address="Rue 1", postal_code="00225")


def test_requires_authentication():
    assert api().get(URL).status_code == 401


def test_new_client_has_zero_everything_and_no_provider():
    me = client_user()
    d = api(me).get(URL).json()
    assert d["capabilities"] == {"client": True, "provider": False, "publishable": False, "company": False, "business": False}
    assert d["provider"] is None
    assert d["client"]["bookings"]["total"] == 0
    assert d["reviews"] == {"received_count": 0, "received_average": None, "to_write": 0}
    assert d["upcoming"] == [] and d["actions"] == []


def test_client_counts_upcoming_and_reviews_to_write():
    me = client_user()
    svc = service(artisan("pro1"))
    book(me, svc, "pending", 3)
    book(me, svc, "confirmed", 1)
    done = book(me, svc, "completed", -5)
    reviewed = book(me, svc, "completed", -9)
    Review.objects.create(booking=reviewed, rating=5, comment="ok")
    book(me, svc, "cancelled", 4)
    d = api(me).get(URL).json()
    assert d["client"]["bookings"] == {"pending": 1, "confirmed": 1, "in_progress": 0, "completed": 2,
                                       "cancelled": 1, "total": 5}
    assert [i["status"] for i in d["upcoming"]] == ["confirmed", "pending"]  # triés par date
    assert d["upcoming"][0]["counterpart"].endswith(".") or d["upcoming"][0]["counterpart"] == "Membre Tratra"
    assert d["client"]["reviews_to_write"] == 1 == d["reviews"]["to_write"]
    assert any(a["key"] == "reviews_to_write" for a in d["actions"])
    assert done.id  # (réservation sans avis comptée)
    assert "email" not in str(d["upcoming"]).lower()


def test_provider_only_sees_missions_checklist_and_actions():
    pro = artisan("pro2", eligible=False)
    other = client_user("cli2")
    svc = service(pro)
    book(other, svc, "pending", 1)
    book(other, svc, "in_progress", 0)
    d = api(pro).get(URL).json()
    assert d["capabilities"]["provider"] is True and d["capabilities"]["publishable"] is False
    p = d["provider"]
    assert p["missions"]["pending"] == 1 and p["missions"]["in_progress"] == 1 and p["missions"]["total"] == 2
    assert p["completion"]["done"] == 0 and p["completion"]["total"] == 7 and p["completion"]["percent"] == 0
    assert p["kyc"]["status"] == "none" and p["services"] == {"active": 1, "total": 1}
    keys = [a["key"] for a in d["actions"]]
    assert "missions_pending" in keys and "kyc_missing" in keys and "profile_incomplete" in keys
    assert d["actions"][0]["severity"] in ("warning", "danger")  # trié par urgence
    assert d["client"]["bookings"]["total"] == 0  # aucune réservation en tant que client


def test_publishable_provider_progress_is_complete():
    pro = artisan("pro3")
    p = api(pro).get(URL).json()["provider"]
    assert p["publishable"] is True and p["completion"]["percent"] == 100
    assert p["kyc"]["status"] == "approved" and p["earnings"]["currency"] == "XOF"


def test_mixed_account_has_both_blocks_with_distinct_roles():
    both = artisan("mix")  # artisan éligible…
    both.first_name = "Moussa"; both.last_name = "Traoré"; both.save()
    seller = artisan("vendeur")
    buyer = client_user("acheteur")
    book(both, service(seller), "confirmed", 2)             # …qui RÉSERVE un autre artisan
    book(buyer, service(both, "Mon service"), "pending", 1)  # …et que l'on réserve
    d = api(both).get(URL).json()
    assert d["capabilities"]["client"] and d["capabilities"]["provider"]
    assert d["client"]["bookings"]["confirmed"] == 1 and d["provider"]["missions"]["pending"] == 1
    roles = {i["role"] for i in d["upcoming"]}
    assert roles == {"client", "handyman"}
    assert d["upcoming"][0]["role"] == "handyman"  # la mission du lendemain passe avant
    assert d["user"]["display_name"] == "Moussa T."


def test_phone_unverified_action_and_unread_counts():
    me = client_user("tel", phone="+2250100000001")
    d = api(me).get(URL).json()
    assert [a["key"] for a in d["actions"]] == ["phone_unverified"]
    assert d["actions"][0]["target"] == "verify_phone"


def test_become_provider_is_idempotent_and_never_creates_an_account():
    me = client_user("futur")
    users_before = User.objects.count()
    c = api(me)
    r1 = c.post("/handy/me/handyman-profile/")
    assert r1.status_code == 201 and r1.json()["created"] is True
    r2 = c.post("/handy/me/handyman-profile/")
    assert r2.status_code == 200 and r2.json()["created"] is False
    assert HandymanProfile.objects.filter(user=me).count() == 1 and User.objects.count() == users_before
    d = c.get(URL).json()
    assert d["capabilities"]["provider"] is True and d["capabilities"]["publishable"] is False
    assert d["provider"]["is_approved"] is False  # création ≠ validation : KYC et approbation restent à faire


def test_become_provider_rules():
    assert api().post("/handy/me/handyman-profile/").status_code == 401
    admin = User.objects.create_user(username="adm", email="adm@x.test", password="x", user_type="admin")
    assert api(admin).post("/handy/me/handyman-profile/").status_code == 403
    # un profil existant (artisan inscrit comme tel) : même réponse « déjà là »
    pro = artisan("deja", eligible=False)
    assert api(pro).post("/handy/me/handyman-profile/").json()["created"] is False
    # make_eligible reste utilisable sur le profil créé ensuite
    me = client_user("neuf")
    api(me).post("/handy/me/handyman-profile/")
    make_eligible(HandymanProfile.objects.get(user=me))
    assert api(me).get(URL).json()["capabilities"]["publishable"] is True


# ---- Agrégations des pages (services, messages, avis, notifications) --------------------------

def test_me_services_lists_unpublished_services_of_the_owner_only():
    pro = artisan("svc_pro", eligible=False)
    mine = service(pro, "Mon service non publié")
    service(artisan("svc_autre"), "Service d'autrui")
    d = api(pro).get("/handy/me/services/").json()
    assert d["publishable"] is False
    assert [s["id"] for s in d["results"]] == [mine.id]
    assert d["results"][0]["published"] is False and d["results"][0]["is_active"] is True
    # …alors que le catalogue public ne l'expose pas
    assert api().get("/handy/services/").json()["count"] == 1  # seul le service de l'artisan éligible « svc_autre »


def test_conversations_flow_is_scoped_to_participants():
    cli, pro, intrus = client_user("c1"), artisan("p1"), client_user("intrus")
    b = book(cli, service(pro))
    r = api(cli).post("/handy/me/conversations/", {"booking": b.id}, format="json")
    assert r.status_code == 201
    cid = r.json()["id"]
    assert api(pro).post("/handy/me/conversations/", {"booking": b.id}, format="json").json() == {"id": cid, "created": False}
    assert api(intrus).post("/handy/me/conversations/", {"booking": b.id}, format="json").status_code == 404
    assert api(cli).post("/handy/messages/", {"conversation": cid, "sender": cli.id, "content": "Bonjour"}, format="json").status_code == 201
    lst = api(pro).get("/handy/me/conversations/").json()["results"]
    assert lst[0]["unread"] == 1 and lst[0]["last_message"] == "Bonjour" and lst[0]["counterpart"].startswith("Aya")
    thread = api(pro).get(f"/handy/me/conversations/{cid}/messages/").json()
    assert [m["mine"] for m in thread["results"]] == [False]
    assert api(intrus).get(f"/handy/me/conversations/{cid}/messages/").status_code == 404
    assert api(pro).post(f"/handy/me/conversations/{cid}/messages/").json() == {"marked": 1}
    assert api(pro).get("/handy/me/conversations/").json()["results"][0]["unread"] == 0


def test_reviews_aggregation_and_notifications_read_all():
    from handy.models import Notification
    cli, pro = client_user("c2"), artisan("p2")
    done = book(cli, service(pro), "completed", -3)
    d = api(cli).get("/handy/me/reviews/").json()
    assert [t["booking_id"] for t in d["to_write"]] == [done.id] and d["given"] == [] and d["received"] == []
    Review.objects.create(booking=done, rating=4, comment="Très bien")
    assert api(pro).get("/handy/me/reviews/").json()["received"][0]["author"].startswith("Aya")
    assert api(cli).get("/handy/me/reviews/").json()["given"][0]["artisan"] != ""
    Notification.objects.create(user=cli, notification_type="booking_status", message="x")
    Notification.objects.create(user=cli, notification_type="booking_status", message="y")
    assert api(cli).post("/handy/me/notifications/read-all/").json() == {"marked": 2}
    assert api(cli).get(URL).json()["unread"]["notifications"] == 0

