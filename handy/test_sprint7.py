"""Tests finalisation backend : PayoutAccount, instant/scheduled, abonnements B2B."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient

from handy.models import (
    User, Booking, Service, ServiceCategory, SubscriptionPlan, Subscription, PayoutAccount,
)


@pytest.fixture
def api_client(db):
    return APIClient()


def _user(u, t="client"):
    return User.objects.create_user(
        username=u, email=f"{u}@ex.com", password="pass1234", user_type=t, is_verified=True)


# ---------- Réservation instantanée / planifiée ----------

@pytest.mark.django_db
def test_booking_instant_vs_scheduled(api_client):
    c, h = _user("c_b7"), _user("h_b7", "handyman")
    cat = ServiceCategory.objects.create(name="X", slug="x")
    svc = Service.objects.create(handyman=h, category=cat, title="s", description="d",
                                 price_type="fixed", price=Decimal("5000"), is_active=True)
    api_client.force_authenticate(user=c)

    r = api_client.post(reverse("bookings-list"), {
        "handyman": h.id, "service": svc.id,
        "booking_date": (timezone.now() + timedelta(hours=2)).isoformat(),
        "address": "a", "city": "Abidjan", "postal_code": "0",
        "type": "instant", "minutes": 60,
    }, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["type"] == "instant"
    assert r.json()["is_immediate"] is True
    assert Booking.objects.get(pk=r.json()["id"]).booking_type == "instant"


# ---------- Compte de versement ----------

@pytest.mark.django_db
def test_payout_account_upsert(api_client):
    h = _user("h_pa", "handyman")
    api_client.force_authenticate(user=h)

    assert api_client.get(reverse("payout-account")).json() == {}

    r = api_client.post(reverse("payout-account"),
                        {"provider": "om", "account_ref": "+22501020304"}, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["provider"] == "om" and r.json()["verified"] is False

    r2 = api_client.post(reverse("payout-account"),
                         {"account_ref": "+22507080910"}, format="json")
    assert r2.status_code == 200
    assert r2.json()["account_ref"] == "+22507080910"
    assert PayoutAccount.objects.filter(handyman=h).count() == 1


# ---------- Abonnements / B2B ----------

@pytest.mark.django_db
def test_souscription_cycle(api_client):
    plan = SubscriptionPlan.objects.create(
        name="Pro", slug="pro", audience="handyman",
        price=Decimal("5000"), interval="monthly", active=True,
        features=["mise en avant", "0% commission première mission"])
    h = _user("h_sub", "handyman")
    api_client.force_authenticate(user=h)

    plans = api_client.get(reverse("subscription-plans-list"))
    assert plans.status_code == 200

    r = api_client.post(reverse("subscriptions-list"), {"plan": plan.id}, format="json")
    assert r.status_code == 201, r.content
    sid = r.json()["id"]

    cur = api_client.get(reverse("subscriptions-current"))
    assert cur.status_code == 200 and cur.json().get("status") == "active"

    cc = api_client.post(reverse("subscriptions-cancel", kwargs={"pk": sid}), {}, format="json")
    assert cc.status_code == 200 and cc.json()["status"] == "cancelled"

    # plus d'abonnement actif
    assert api_client.get(reverse("subscriptions-current")).json() == {"active": False}


@pytest.mark.django_db
def test_api_root_json(api_client):
    """Backend découplé : '/' renvoie un JSON API-root (plus de page HTML Django)."""
    r = api_client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Tratra API"
    assert data["docs"] == "/api/docs/"
    assert data["api"] == "/handy/"


@pytest.mark.django_db
def test_souscription_renouvellement_annule_la_precedente():
    plan = SubscriptionPlan.objects.create(name="Std", slug="std", price=Decimal("0"),
                                           interval="monthly", active=True)
    u = _user("u_sub2")
    s1 = Subscription.subscribe(u, plan)
    s2 = Subscription.subscribe(u, plan)
    s1.refresh_from_db()
    assert s1.status == "cancelled"
    assert s2.status == "active" and s2.is_active() is True
    assert Subscription.objects.filter(user=u, status="active").count() == 1
