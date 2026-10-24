"""Recrutement (invitation → candidature) et modes des offres (ponctuel, récurrent, contractuel), sans régression des prestations."""
from datetime import date, timedelta

import pytest
from rest_framework.test import APIClient

from engagements.models import EngagementApplication, EngagementInvitation, EngagementRule
from engagements.services import postings
from engagements.services.common import EngagementError
from engagements.testing import WEEK, category, person, pro
from handy.models import Notification, Service

pytestmark = pytest.mark.django_db
TODAY = date(2027, 2, 1)


def api(user=None):
    c = APIClient()
    if user is not None:
        c.force_authenticate(user)
    return c


def open_posting(owner):
    p = postings.create_posting(owner, dict(category=category().pk, title="Nounou à domicile — Cocody", mission_type="long_term",
                                            description="Garde de deux enfants après l'école, aide aux devoirs et préparation du goûter.",
                                            work_relationship="independent", city="Abidjan", start_date=TODAY + timedelta(days=7), schedule=WEEK,
                                            amount="120000", period="monthly", benefits="Repas de midi fourni", duration_months=12), today=TODAY)
    return postings.publish(p, owner)


def test_invite_a_verified_professional_who_applies_by_accepting():
    owner, worker = person("famille_inv"), pro("nounou_inv")
    p = open_posting(owner)
    assert (p.benefits, p.duration_months) == ("Repas de midi fourni", 12)
    r = api(owner).post(f"/handy/engagements/postings/{p.pk}/invitations/", {"invitee": worker.pk, "message": "Votre profil nous intéresse."},
                        format="json")
    assert r.status_code == 201 and r.json()["status"] == "sent"
    assert Notification.objects.filter(user=worker, dedupe_key__startswith="eng-invite:").exists()
    assert api(owner).post(f"/handy/engagements/postings/{p.pk}/invitations/", {"invitee": worker.pk}, format="json").status_code == 409
    mine = api(worker).get("/handy/engagements/invitations/mine/").json()["results"]
    assert len(mine) == 1 and mine[0]["can_respond"] and mine[0]["posting"]["title"] == p.title
    r = api(worker).post(f"/handy/engagements/invitations/{mine[0]['id']}/respond/", {"accept": True, "message": "Disponible dès lundi."}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "accepted" and r.json()["application_id"]
    assert EngagementApplication.objects.get(pk=r.json()["application_id"]).applicant == worker


def test_invitations_are_limited_to_the_publisher_and_to_verified_professionals():
    owner, other, client = person("p_inv2"), person("intrus_inv"), person("client_simple")
    p = open_posting(owner)
    assert api(other).post(f"/handy/engagements/postings/{p.pk}/invitations/", {"invitee": client.pk}, format="json").status_code == 404
    r = api(owner).post(f"/handy/engagements/postings/{p.pk}/invitations/", {"invitee": client.pk}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "worker_not_verified" and not EngagementInvitation.objects.exists()
    worker = pro("pro_decline")
    inv = postings.invite(p, owner, worker.pk)
    assert api(other).post(f"/handy/engagements/invitations/{inv.pk}/respond/", {"accept": True}, format="json").status_code == 404
    postings.respond_invitation(inv, worker, False)
    inv.refresh_from_db()
    assert inv.status == "declined" and not EngagementApplication.objects.filter(posting=p, applicant=worker).exists()
    with pytest.raises(EngagementError):
        postings.respond_invitation(inv, worker, True)                                   # une seule réponse


def test_a_service_offers_several_modes_within_the_trade_rules():
    worker = pro("chauffeur_modes")
    cat = category("chauffeur", "Chauffeur")
    c = api(worker)
    r = c.post("/handy/services/", {"category": cat.pk, "title": "Chauffeur de maison", "description": "Conduite et courses.",
                                    "price_type": "fixed", "price": "150000", "modes": ["one_off", "contract"]}, format="json")
    assert r.status_code == 201, r.content
    s = Service.objects.get(pk=r.json()["id"])
    assert (s.offers_one_off, s.offers_recurring, s.offers_contract) == (True, False, True) and r.json()["modes"] == ["one_off", "contract"]
    listing = api().get(f"/handy/services/?mode=contract&handyman={worker.pk}").json()
    assert [row["id"] for row in listing["results"]] == [s.pk]
    assert api().get(f"/handy/services/?mode=recurring&handyman={worker.pk}").json()["results"] == []
    EngagementRule.objects.create(category=cat, allow_long_term=False)
    r = c.patch(f"/handy/services/{s.pk}/", {"modes": ["contract"]}, format="json")
    assert r.status_code == 400 and "modes" in r.json().get("fields", r.json())
    assert c.patch(f"/handy/services/{s.pk}/", {"modes": []}, format="json").status_code == 400      # au moins un mode


def test_existing_services_stay_one_off_by_default():
    worker = pro("plombier_modes")
    r = api(worker).post("/handy/services/", {"category": category().pk, "title": "Fuite d'eau", "description": "Réparation rapide.",
                                              "price_type": "fixed", "price": "8000"}, format="json")
    assert r.status_code == 201 and r.json()["modes"] == ["one_off"]
