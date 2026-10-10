"""Back-Office opérationnel : Services, Réservations et litiges, Suivi en direct, Avis. Machine à états et escrow jamais
contournés, séparation des tâches (le support médie, la finance exécute), GPS protégé, contenu privé jamais exposé."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.gis.geos import Point
from django.utils import timezone
from rest_framework.test import APIClient

from backoffice import rbac
from handy import eligibility
from handy.models import Booking, Conversation, Dispute, Message, Notification, Payment, Report, Review, Service, ServiceCategory
from handy.test_eligibility import artisan, service
from live.models import LivePosition, TrackingSession
from trust.models import AuditEvent

User = get_user_model()
pytestmark = pytest.mark.django_db
BO = "/handy/backoffice"


def person(name, **kw):
    return User.objects.create_user(name, f"{name}@x.test", "pass1234", user_type="client", is_verified=True, **kw)


def staff(name, role=None, superuser=False):
    rbac.ensure_roles()
    u = User.objects.create_user(name, f"{name}@x.test", "pass1234", is_staff=True, is_superuser=superuser, first_name=name.title(), last_name="Admin")
    if role:
        u.groups.add(Group.objects.get(name=rbac.role_group_name(role)))
    return u


def api(u=None):
    c = APIClient()
    if u:
        c.force_authenticate(u)
    return c


def audited(action, **target):
    return AuditEvent.objects.filter(action=f"backoffice.{action}", **target)


def make_booking(client, art, status="pending", svc=None, **kw):
    return Booking.objects.create(client=client, handyman=art, service=svc, status=status, address="Rue des Jardins 12", city="Abidjan",
                                  booking_date=kw.pop("booking_date", timezone.now() + timedelta(days=1)), **kw)


def pay(booking, status="held", amount="10000", fee="1000"):
    return Payment.objects.create(booking=booking, amount=Decimal(amount), platform_fee=Decimal(fee), method="om", status=status, is_paid=status != "pending")


# ═══ Services ═══════════════════════════════════════════════════════════════════════════════════════════════════════

def test_services_list_flags_publication_and_hiding_has_real_effect_with_notification_and_audit():
    a = artisan("sv_art")
    svc = service(a, "Dépannage fuite")
    ops = api(staff("sv_ops", "ops"))
    row = ops.get(f"{BO}/services/?q=fuite").json()["results"][0]
    assert row["title"] == "Dépannage fuite" and row["published"] is True and row["artisan"] == "Compte #" + str(a.id)
    assert ops.post(f"{BO}/services/{svc.id}/hide/", {}, format="json").status_code == 400            # motif obligatoire
    hidden = ops.post(f"{BO}/services/{svc.id}/hide/", {"reason": "Contenu trompeur"}, format="json")
    assert hidden.status_code == 200 and hidden.json()["is_active"] is False and hidden.json()["published"] is False
    assert svc.id not in eligibility.restrict_public_services(Service.objects.all()).values_list("id", flat=True)     # retiré du catalogue public
    assert Notification.objects.filter(user=a, notification_type="system", title="Service masqué").exists()
    assert ops.post(f"{BO}/services/{svc.id}/hide/", {"reason": "Encore"}, format="json").status_code == 409
    assert ops.post(f"{BO}/services/{svc.id}/restore/", {}, format="json").json()["is_active"] is True
    assert audited("service.hidden", target_id=svc.id).get().data["reason"] == "Contenu trompeur" and audited("service.restored", target_id=svc.id).exists()
    assert api(staff("sv_support", "support")).get(f"{BO}/services/").status_code == 403


def test_categories_validation_uniqueness_and_updates_are_audited():
    ops = api(staff("ct_ops", "ops"))
    bad = ops.post(f"{BO}/services/categories/", {"name": "", "slug": "Pas valide!"}, format="json")
    assert bad.status_code == 400 and set(bad.json()["fields"]) == {"name", "slug"}
    ok = ops.post(f"{BO}/services/categories/", {"name": "Climatisation", "slug": "Climatisation", "icon": "snowflake"}, format="json")
    assert ok.status_code == 201 and ok.json()["slug"] == "climatisation"
    assert ops.post(f"{BO}/services/categories/", {"name": "Autre", "slug": "climatisation"}, format="json").json()["fields"]["slug"] == "Cet identifiant existe déjà."
    assert ops.post(f"{BO}/services/categories/", {"name": "X", "slug": "x-1", "parent": 999999}, format="json").json()["fields"]["parent"]
    cid = ok.json()["id"]
    assert ops.patch(f"{BO}/services/categories/{cid}/", {"name": ""}, format="json").status_code == 400
    assert ops.patch(f"{BO}/services/categories/{cid}/", {"is_active": False, "description": "Froid et clim"}, format="json").json()["is_active"] is False
    assert audited("category.created", target_id=cid).exists() and audited("category.updated", target_id=cid).exists()
    assert any(c["id"] == cid for c in ops.get(f"{BO}/services/categories/").json()["results"])


# ═══ Réservations ═══════════════════════════════════════════════════════════════════════════════════════════════════

def test_booking_detail_hides_what_the_role_must_not_see_and_never_exposes_messages():
    c, a = person("b_cli", phone="+2250701234567"), artisan("b_art")
    b = make_booking(c, a, "confirmed", svc=service(a))
    pay(b)
    conv = Conversation.objects.create(booking=b)
    conv.participants.add(c, a)
    Message.objects.create(conversation=conv, sender=c, content="Mon code de porte est 4821")
    support, finance, root = api(staff("b_support", "support")), api(staff("b_finance", "finance")), api(staff("b_root", superuser=True))
    s = support.get(f"{BO}/bookings/{b.id}/").json()
    assert s["address"] == "Rue des Jardins 12" and s["client_phone"] == "+22507••••4567" and s["can_cancel"] is True
    assert "amount" not in s["payment"] and s["messages"] == 1                                       # pas de montant sans finance.view
    f = finance.get(f"{BO}/bookings/{b.id}/").json()
    assert f["address"] is None and f["payment"]["amount"] == "10000.00" and f["can_cancel"] is False   # la finance consulte, n'annule pas
    assert "4821" not in support.get(f"{BO}/bookings/{b.id}/").content.decode() + root.get(f"{BO}/bookings/{b.id}/").content.decode()
    assert api(staff("b_mkt", "marketing")).get(f"{BO}/bookings/").status_code == 403
    assert root.get(f"{BO}/bookings/?q={b.id}").json()["count"] == 1 and root.get(f"{BO}/bookings/?status=confirmed&active=true").json()["count"] == 1
    assert root.get(f"{BO}/bookings/?disputed=true").json()["count"] == 0


def test_staff_cancellation_goes_through_the_state_machine_with_reason_escrow_and_audit():
    c, a = person("bc_cli"), artisan("bc_art")
    b = make_booking(c, a, "pending")
    p = pay(b)
    support = api(staff("bc_support", "support"))
    assert support.post(f"{BO}/bookings/{b.id}/cancel/", {}, format="json").status_code == 400
    ok = support.post(f"{BO}/bookings/{b.id}/cancel/", {"reason": "Demande du client par téléphone"}, format="json")
    assert ok.status_code == 200 and ok.json()["status"] == "cancelled"
    p.refresh_from_db()
    assert p.status == "refunded"                                                                    # l'escrow est restitué par la machine à états
    assert Notification.objects.filter(user=c, category="booking").exists() and Notification.objects.filter(user=a, category="booking").exists()
    assert audited("booking.cancelled", target_id=b.id).get().data["reason"] == "Demande du client par téléphone"
    again = support.post(f"{BO}/bookings/{b.id}/cancel/", {"reason": "Encore une fois"}, format="json")
    assert again.status_code == 409 and again.json()["code"] == "invalid_transition"
    done = make_booking(c, a, "completed")
    assert support.post(f"{BO}/bookings/{done.id}/cancel/", {"reason": "Trop tard pour cela"}, format="json").status_code == 409
    assert api(staff("bc_fin", "finance")).post(f"{BO}/bookings/{done.id}/cancel/", {"reason": "Pas mon rôle"}, format="json").status_code == 403


# ═══ Litiges ════════════════════════════════════════════════════════════════════════════════════════════════════════

def test_dispute_money_decisions_need_finance_manage_while_support_can_mediate():
    c, a = person("dp_cli"), artisan("dp_art")
    b = make_booking(c, a, "completed")
    p = pay(b)
    d = Dispute.objects.create(booking=b, reporter=c, reason="Travail non terminé", status="open")
    support = api(staff("dp_support", "support"))
    listing = support.get(f"{BO}/disputes/?open=true").json()["results"]
    assert listing[0]["id"] == d.id and listing[0]["amount"] is None                                 # le support ne voit pas les montants
    assert support.post(f"{BO}/disputes/{d.id}/review/", {}, format="json").json()["status"] == "under_review"
    assert support.post(f"{BO}/disputes/{d.id}/review/", {}, format="json").status_code == 409
    detail = support.get(f"{BO}/disputes/{d.id}/").json()
    assert detail["can_decide"] is True and detail["can_move_money"] is False and detail["reporter_role"] == "client"
    refused = support.post(f"{BO}/disputes/{d.id}/resolve/", {"action": "refund_client", "reason": "Remboursement accordé"}, format="json")
    assert refused.status_code == 403 and refused.json()["code"] == "finance_required"
    p.refresh_from_db()
    assert p.status == "held" and Dispute.objects.get(pk=d.id).status == "under_review"             # rien n'a bougé
    assert support.post(f"{BO}/disputes/{d.id}/resolve/", {"action": "none"}, format="json").status_code == 400      # motif obligatoire
    finance = api(staff("dp_fin", "finance"))
    # la finance exécute l'argent mais ne tranche pas seule : sans bookings.manage la décision est refusée
    assert finance.post(f"{BO}/disputes/{d.id}/resolve/", {"action": "refund_client", "reason": "Preuves reçues"}, format="json").status_code == 403


def test_finance_role_cannot_decide_disputes_but_super_admin_resolves_with_real_escrow_effect():
    c, a = person("dr_cli"), artisan("dr_art")
    b = make_booking(c, a, "completed")
    p = pay(b)
    d = Dispute.objects.create(booking=b, reporter=c, reason="Travail non terminé", status="open")
    assert api(staff("dr_fin", "finance")).post(f"{BO}/disputes/{d.id}/resolve/", {"action": "none", "reason": "Rien à faire ici"}, format="json").status_code == 403   # finance ≠ bookings.manage
    root = api(staff("dr_root", superuser=True))
    assert root.post(f"{BO}/disputes/{d.id}/resolve/", {"action": "inconnue", "reason": "Action inexistante"}, format="json").status_code == 400
    ok = root.post(f"{BO}/disputes/{d.id}/resolve/", {"action": "refund_client", "reason": "Preuves reçues"}, format="json")
    assert ok.status_code == 200 and ok.json()["status"] == "resolved"
    p.refresh_from_db()
    assert p.status == "refunded"
    assert audited("dispute.resolved", target_id=d.id).get().data["resolution_action"] == "refund_client"
    assert root.post(f"{BO}/disputes/{d.id}/resolve/", {"action": "none", "reason": "Une seconde décision"}, format="json").json()["code"] == "not_open"
    assert Notification.objects.filter(user=c, notification_type="dispute_resolved").exists()
    d2 = Dispute.objects.create(booking=make_booking(c, a, "completed"), reporter=a, reason="Non-paiement", status="open")
    assert root.post(f"{BO}/disputes/{d2.id}/reject/", {"reason": "Aucune preuve fournie"}, format="json").json()["status"] == "rejected"
    assert root.post(f"{BO}/disputes/{d2.id}/reject/", {}, format="json").status_code in (400, 409)


# ═══ Suivi en direct ════════════════════════════════════════════════════════════════════════════════════════════════

def live_session(sharing=True, age=10, status="in_progress", arrival=None):
    c, a = person(f"lv_cli{age}{status}"), artisan(f"lv_art{age}{status}")
    b = make_booking(c, a, status, booking_date=timezone.now())
    s = TrackingSession.objects.create(booking=b, artisan_sharing=sharing, en_route_at=timezone.now() - timedelta(minutes=10), arrival_distance_m=arrival)
    LivePosition.objects.create(session=s, role="artisan", loc=Point(-4.012345, 5.367891, srid=4326), captured_at=timezone.now() - timedelta(seconds=age))
    return b, s


def test_live_module_shows_state_and_flags_but_never_coordinates():
    b, s = live_session(age=300, status="confirmed")             # « en route » = mission confirmée dont l'artisan est parti
    ops = api(staff("lv_ops", "ops"))
    r = ops.get(f"{BO}/live/")
    row = r.json()["results"][0]
    assert row["booking_id"] == b.id and row["artisan_sharing"] is True and "position_stale" in row["flags"] and row["last_position_age_s"] >= 300
    text = r.content.decode() + ops.get(f"{BO}/live/{b.id}/").content.decode()
    for forbidden in ("lat", "lng", "5.36", "4.01", "polyline", "loc"):
        assert forbidden not in text, forbidden
    far, _ = live_session(age=5, status="confirmed", arrival=900)
    assert "arrival_far" in ops.get(f"{BO}/live/{far.id}/").json()["flags"]
    assert api(staff("lv_support", "support")).get(f"{BO}/live/").status_code == 403


def test_position_access_needs_reason_consent_fresh_data_and_is_rounded_and_audited():
    b, s = live_session(age=10)
    ops = api(staff("lp_ops", "ops"))
    assert ops.post(f"{BO}/live/{b.id}/position/", {}, format="json").status_code == 400
    ok = ops.post(f"{BO}/live/{b.id}/position/", {"reason": "Artisan injoignable depuis 20 minutes"}, format="json")
    assert ok.status_code == 200 and (ok.json()["lat"], ok.json()["lng"], ok.json()["precision_m"]) == (5.368, -4.012, 100)   # arrondi à ~100 m
    assert audited("live.position_viewed", target_id=b.id).get().data["reason"].startswith("Artisan injoignable")
    s.artisan_sharing = False
    s.save()
    assert ops.post(f"{BO}/live/{b.id}/position/", {"reason": "Sans consentement"}, format="json").status_code == 409   # consentement retiré
    b2, _ = live_session(age=500)
    assert ops.post(f"{BO}/live/{b2.id}/position/", {"reason": "Position ancienne"}, format="json").json()["code"] == "stale"
    b3, _ = live_session(age=5, status="completed")
    assert ops.post(f"{BO}/live/{b3.id}/position/", {"reason": "Mission terminée"}, format="json").status_code == 409      # hors intervention
    assert api(staff("lp_support", "support")).post(f"{BO}/live/{b.id}/position/", {"reason": "Pas mon rôle"}, format="json").status_code == 403


# ═══ Avis ═══════════════════════════════════════════════════════════════════════════════════════════════════════════

def test_reviews_moderation_hides_never_edits_and_resolves_reports():
    c, a = person("rv_cli", first_name="Awa", last_name="Kone"), artisan("rv_art")
    b = make_booking(c, a, "completed")
    r = Review.objects.create(booking=b, rating=1, comment="Très mauvais, voleur !")
    rep = Report.objects.create(reporter=a, report_type="review", review=r, reason="Insulte")
    support = api(staff("rv_support", "support"))
    queue = support.get(f"{BO}/reviews/?reported=true").json()["results"]
    assert queue[0]["id"] == r.id and queue[0]["reports"] == 1 and queue[0]["author"] == "Awa K."
    detail = support.get(f"{BO}/reviews/{r.id}/").json()
    assert detail["comment"] == "Très mauvais, voleur !" and detail["reports"][0]["reason"] == "Insulte"
    assert support.post(f"{BO}/reviews/{r.id}/hide/", {}, format="json").status_code == 400
    assert support.post(f"{BO}/reviews/{r.id}/hide/", {"reason": "Insultes envers l'artisan"}, format="json").json()["is_hidden"] is True
    r.refresh_from_db(); rep.refresh_from_db()
    assert r.is_hidden and r.comment == "Très mauvais, voleur !" and rep.is_resolved             # masqué, jamais réécrit ; signalements clos
    assert support.post(f"{BO}/reviews/{r.id}/hide/", {"reason": "Encore une fois"}, format="json").status_code == 409
    assert support.get(f"{BO}/reviews/?hidden=true").json()["count"] == 1
    assert support.post(f"{BO}/reviews/{r.id}/restore/", {"reason": "Décision révisée"}, format="json").json()["is_hidden"] is False
    assert audited("review.hidden", target_id=r.id).exists() and audited("review.restored", target_id=r.id).exists()
    m = Message.objects.create(conversation=Conversation.objects.create(booking=b), sender=c, content="Message signalé")
    rep2 = Report.objects.create(reporter=a, report_type="message", message=m, reason="Menace")
    reports = support.get(f"{BO}/reviews/reports/").json()["results"]
    assert [x["id"] for x in reports] == [rep2.id] and reports[0]["excerpt"] == "Message signalé"
    assert support.post(f"{BO}/reviews/reports/{rep2.id}/resolve/", {}, format="json").status_code == 400
    assert support.post(f"{BO}/reviews/reports/{rep2.id}/resolve/", {"reason": "Pris en charge par le support"}, format="json").json()["is_resolved"] is True
    assert support.post(f"{BO}/reviews/reports/{rep2.id}/resolve/", {"reason": "Encore une fois"}, format="json").status_code == 409
    assert api(staff("rv_fin", "finance")).get(f"{BO}/reviews/").status_code == 403
