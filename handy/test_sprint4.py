"""Tests Sprint 4 — confiance & conformité.

- Litiges : ouverture par une partie, refus pour un tiers, résolution admin
  (remboursement client / versement artisan) déclenchant l'escrow.
- Annulation : pénalité selon CancellationPolicy + remboursement partiel net.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient

from handy.models import (
    User, Booking, Payment, Dispute, CancellationPolicy, artisan_available_earnings,
)


@pytest.fixture
def api_client(db):
    return APIClient()


def _user(username, utype="client"):
    return User.objects.create_user(
        username=username, email=f"{username}@ex.com",
        password="pass1234", user_type=utype, is_verified=True,
    )


def _admin(username):
    u = _user(username, "admin")
    u.is_staff = True
    u.save(update_fields=["is_staff"])
    return u


def _booking(client, handyman, status="pending", booking_date="2020-06-01T10:00:00Z"):
    return Booking.objects.create(
        client=client, handyman=handyman, status=status, booking_date=booking_date,
        address="Cocody", city="Abidjan", postal_code="00225",
    )


def _payment(booking, status="held", ref="tx", amount="10000", fee="1000"):
    return Payment.objects.create(
        booking=booking, amount=Decimal(amount), platform_fee=Decimal(fee),
        method="om", status=status, transaction_id=ref,
    )


# ---------- Litiges ----------

@pytest.mark.django_db
def test_litige_ouverture_et_resolution_remboursement(api_client):
    c, h, admin = _user("c_d1"), _user("h_d1", "handyman"), _admin("adm1")
    b = _booking(c, h)
    pay = _payment(b, status="held", ref="d1")

    # le client ouvre un litige
    api_client.force_authenticate(user=c)
    r = api_client.post(reverse("disputes-list"),
                        {"booking": b.id, "reason": "travail non conforme"}, format="json")
    assert r.status_code == 201, r.content
    did = r.json()["id"]

    # l'admin résout en remboursant le client -> escrow remboursé
    api_client.force_authenticate(user=admin)
    rr = api_client.post(reverse("disputes-resolve", kwargs={"pk": did}),
                         {"action": "refund_client", "resolution": "OK remboursé"}, format="json")
    assert rr.status_code == 200, rr.content
    pay.refresh_from_db()
    assert pay.status == "refunded"
    assert pay.refunded_amount == Decimal("10000")


@pytest.mark.django_db
def test_litige_resolution_versement_artisan(api_client):
    c, h, admin = _user("c_d3"), _user("h_d3", "handyman"), _admin("adm3")
    b = _booking(c, h)
    pay = _payment(b, status="held", ref="d3")
    d = Dispute.objects.create(booking=b, reporter=h, reason="paiement bloqué", status="open")

    api_client.force_authenticate(user=admin)
    rr = api_client.post(reverse("disputes-resolve", kwargs={"pk": d.id}),
                         {"action": "release_artisan"}, format="json")
    assert rr.status_code == 200, rr.content
    pay.refresh_from_db()
    assert pay.status == "released"
    assert artisan_available_earnings(h) == Decimal("9000")


@pytest.mark.django_db
def test_litige_par_tiers_refuse(api_client):
    c, h, intrus = _user("c_d2"), _user("h_d2", "handyman"), _user("intrus_d")
    b = _booking(c, h)
    api_client.force_authenticate(user=intrus)
    r = api_client.post(reverse("disputes-list"),
                        {"booking": b.id, "reason": "pas mon affaire"}, format="json")
    assert r.status_code == 403


@pytest.mark.django_db
def test_litige_resolution_reservee_admin(api_client):
    c, h = _user("c_d4"), _user("h_d4", "handyman")
    b = _booking(c, h)
    d = Dispute.objects.create(booking=b, reporter=c, reason="x", status="open")
    api_client.force_authenticate(user=c)  # non-admin
    rr = api_client.post(reverse("disputes-resolve", kwargs={"pk": d.id}),
                         {"action": "refund_client"}, format="json")
    assert rr.status_code == 403


# ---------- Annulation avec pénalités ----------

@pytest.mark.django_db
def test_annulation_penalite_remboursement_partiel():
    CancellationPolicy.objects.create(
        name="standard", free_until_minutes=60, fee_percent=Decimal("20"), active=True)
    c, h = _user("c_cx"), _user("h_cx", "handyman")
    # mission dans 10 min < fenêtre gratuite de 60 min -> pénalité
    b = _booking(c, h, booking_date=timezone.now() + timedelta(minutes=10))
    pay = _payment(b, status="held", ref="cx1", amount="10000", fee="1000")

    b.transition_to("cancelled")
    b.refresh_from_db()
    pay.refresh_from_db()
    assert b.cancellation_fee == Decimal("2000")        # 20% de 10000
    assert pay.status == "refunded"
    assert pay.refunded_amount == Decimal("8000")        # net remboursé (10000 - 2000)


@pytest.mark.django_db
def test_annulation_gratuite_hors_fenetre():
    CancellationPolicy.objects.create(
        name="std2", free_until_minutes=60, fee_percent=Decimal("20"), active=True)
    c, h = _user("c_cf"), _user("h_cf", "handyman")
    # mission dans 2 jours -> annulation gratuite
    b = _booking(c, h, booking_date=timezone.now() + timedelta(days=2))
    pay = _payment(b, status="held", ref="cf1", amount="5000", fee="500")

    b.transition_to("cancelled")
    b.refresh_from_db()
    pay.refresh_from_db()
    assert b.cancellation_fee == Decimal("0")
    assert pay.refunded_amount == Decimal("5000")        # remboursement intégral
