"""Intégration avec l'existant : organisations Business (RBAC), continuité, réservations, passeport Trust, notifications."""
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from business.models import Membership, Organization, Role
from engagements import tasks
from engagements.testing import WEEK, category, contract_data, make_contract, person, pro
from handy.models import Notification

pytestmark = pytest.mark.django_db
BASE = "/handy/engagements/"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def client(user=None):
    c = APIClient()
    if user is not None:
        c.force_authenticate(user)
    return c


def test_organization_members_act_for_the_organization_only_with_the_engagement_capability():
    owner, admin, requester, outsider, worker = person("o_owner"), person("o_admin"), person("o_req"), person("o_out"), pro("o_worker")
    org = Organization.objects.create(name="Résidence Les Palmiers", owner=owner) if "owner" in [f.name for f in Organization._meta.get_fields()] else Organization.objects.create(name="Résidence Les Palmiers")
    Membership.objects.create(organization=org, user=owner, role=Role.OWNER)
    Membership.objects.create(organization=org, user=admin, role=Role.ADMIN)
    Membership.objects.create(organization=org, user=requester, role=Role.REQUESTER)
    today = timezone.localdate()
    body = dict(contract_data(worker, start=today + timedelta(days=2)), organization=org.pk, schedule=WEEK)
    for key in ("worker",):
        body[key] = worker.pk
    r = client(requester).post(BASE + "contracts/", body, format="json")
    assert r.status_code == 403 and r.data["code"] == "organization_forbidden"                   # un simple demandeur n'engage pas l'organisation
    assert client(outsider).post(BASE + "contracts/", body, format="json").status_code == 403
    made = client(admin).post(BASE + "contracts/", body, format="json")
    assert made.status_code == 201 and made.data["organization"]["name"] == "Résidence Les Palmiers" and made.data["my_role"] == "principal"
    cid = made.data["id"]
    assert client(owner).get(BASE + f"contracts/{cid}/").status_code == 200                       # le propriétaire voit et gère le contrat de son organisation
    assert client(requester).get(BASE + f"contracts/{cid}/").status_code == 404
    assert client(outsider).get(BASE + f"contracts/{cid}/").status_code == 404
    assert client(owner).post(BASE + f"contracts/{cid}/propose/").data["status"] == "pending_acceptance"
    assert Notification.objects.filter(user=worker, notification_type="contract_proposed").exists()
    terms = client(worker).get(BASE + f"contracts/{cid}/").data["terms_hash"]
    assert client(worker).post(BASE + f"contracts/{cid}/accept/", {"terms_hash": terms}, format="json").data["status"] == "accepted"
    assert len(client(admin).get(BASE + "contracts/?role=principal").data["results"]) == 1
    assert client(admin).get(BASE + "me/overview/").data["organizations"] == [{"id": org.pk, "name": "Résidence Les Palmiers"}]
    assert client(requester).get(BASE + "me/overview/").data["organizations"] == []                 # sans habilitation : aucune organisation proposée
    # Un membre retiré perd immédiatement l'accès.
    Membership.objects.filter(organization=org, user=admin).update(is_active=False)
    assert client(admin).get(BASE + f"contracts/{cid}/").status_code == 404
    # Les notifications destinées au donneur d'ordre parviennent aux responsables de l'organisation.
    assert Notification.objects.filter(user=owner, notification_type="contract_accepted").exists()


def test_contracts_appear_in_the_continuity_feed_without_hijacking_the_resume_button():
    owner, worker = person("k_owner"), pro("k_worker")
    today = timezone.localdate()
    c = make_contract(owner, worker, start=today + timedelta(days=5), today=today, months=12)
    feed = client(worker).get("/handy/me/activities/").data
    items = [i for i in feed["activities"] if i["kind"] == "contract"]
    assert len(items) == 1 and items[0]["id"] == c.pk and items[0]["deeplink"] == f"tratra://contract/{c.pk}" and items[0]["role"] == "worker"
    assert items[0]["status"] == "accepted" and items[0]["active"] is True and "amount" not in items[0] and "address" not in str(items[0]).lower()
    assert feed["primary"]["kind"] == "contract"                                                  # seule activité : elle est reprise
    changes = client(owner).get("/handy/me/activities/?since=" + (timezone.now() - timedelta(minutes=5)).isoformat().replace("+", "%2B")).data["changes"]
    assert [i["id"] for i in changes if i["kind"] == "contract"] == [c.pk]
    stranger = pro("k_stranger")
    assert not [i for i in client(stranger).get("/handy/me/activities/").data["activities"] if i["kind"] == "contract"]
    pending = contract_data(worker, start=today + timedelta(days=9))
    from engagements.services import contracts as svc
    draft = svc.create_draft(owner, pending, today=today)
    assert draft.pk not in [i["id"] for i in client(worker).get("/handy/me/activities/").data["activities"] if i["kind"] == "contract"]   # brouillon invisible du prestataire


def test_bookings_expose_their_recurring_origin_and_one_off_bookings_are_unchanged():
    owner, worker = person("b_owner"), pro("b_worker")
    today = timezone.localdate()
    c = make_contract(owner, worker, start=today, today=today, months=6, bookings_mode="per_occurrence", schedule=[{"weekday": d, "start": "09:00", "end": "11:00"} for d in range(7)])
    tasks.run(today)
    rows = client(owner).get("/handy/bookings/").data
    rows = rows["results"] if isinstance(rows, dict) else rows
    assert rows and all(r["mission_type"] == "recurring" and r["contract_id"] == c.pk for r in rows)
    from handy.models import Booking
    one_off = Booking.objects.create(client=owner, handyman=worker, booking_date=timezone.now() + timedelta(days=30), address="Rue 1", city="Abidjan", description="Réparation ponctuelle")
    row = client(owner).get(f"/handy/bookings/{one_off.pk}/").data
    assert row["mission_type"] == "one_off" and row["contract_id"] is None


def test_trust_passport_gains_a_verifiable_engagements_block_without_touching_badges_or_score():
    owner, worker = person("t_owner"), pro("t_worker")
    today = timezone.localdate()
    from trust import passport
    profile = worker.handyman_profile
    before = passport.build(profile)
    assert before["engagements"]["contracts_completed"] == 0 and before["engagements"]["source"] == "plateforme"
    make_contract(owner, worker, start=today, today=today, months=12)
    after = passport.build(profile)
    assert after["engagements"]["contracts_active"] == 1 and after["engagements"]["distinct_principals"] == 1
    assert after["score"] == before["score"] and after["badges"] == before["badges"]              # aucun effet sur le score ni les badges
    text = str(after["engagements"])
    assert owner.username not in text and "amount" not in text
