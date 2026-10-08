"""Tests Sprint 2 — cœur transactionnel.

- Machine à états Booking (transitions validées, BookingTimeline, completed_jobs idempotent)
- Wallet : contrôle de solde (anti-débit au-delà du solde)
- Présence artisan + matching
- API : action transition + status en lecture seule
"""
from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework.test import APIClient

from handy.models import (
    User, Booking, HandymanProfile, ServiceCategory, DepositTransaction,
)


@pytest.fixture
def api_client(db):
    return APIClient()


def _user(username, utype="client"):
    return User.objects.create_user(
        username=username, email=f"{username}@ex.com",
        password="pass1234", user_type=utype, is_verified=True,
    )


def _booking(client, handyman, status="pending"):
    # date passée : la complétion pose end_date=now, qui doit rester >= booking_date
    # (contrainte bk_end_after_start).
    return Booking.objects.create(
        client=client, handyman=handyman, status=status,
        booking_date="2020-06-01T10:00:00Z",
        address="Cocody", city="Abidjan", postal_code="00225",
    )


# ---------- Machine à états ----------

@pytest.mark.django_db
def test_transition_invalide_levee():
    b = _booking(_user("c_sm"), _user("h_sm", "handyman"))
    with pytest.raises(ValidationError):
        b.transition_to("in_progress")  # pending -> in_progress interdit
    with pytest.raises(ValidationError):
        b.transition_to("completed")    # pending -> completed interdit


@pytest.mark.django_db
def test_cycle_complet_timeline_et_completed_jobs():
    h = _user("h_sm2", "handyman")
    b = _booking(_user("c_sm2"), h)

    b.transition_to("confirmed")
    b.transition_to("in_progress")
    b.transition_to("completed")

    b.refresh_from_db()
    assert b.status == "completed"
    assert b.end_date is not None            # end_date posé à la complétion
    assert b.timeline.count() == 3           # BookingTimeline alimenté

    prof = HandymanProfile.objects.get(user=h)
    assert prof.completed_jobs == 1          # incrémenté une seule fois

    # Re-sauvegarde d'une réservation déjà 'completed' -> PAS de double comptage
    b.save()
    prof.refresh_from_db()
    assert prof.completed_jobs == 1


@pytest.mark.django_db
def test_annulation_depuis_pending():
    b = _booking(_user("c_sm3"), _user("h_sm3", "handyman"))
    b.transition_to("cancelled")
    b.refresh_from_db()
    assert b.status == "cancelled"


# ---------- Wallet ----------

@pytest.mark.django_db
def test_wallet_debit_au_dela_du_solde_bloque():
    h = _user("h_w", "handyman")
    DepositTransaction.objects.create(
        handyman=h, type="deposit", amount=Decimal("1000"), status="completed")
    DepositTransaction.objects.create(
        handyman=h, type="deduction", amount=Decimal("-600"), status="completed")
    assert DepositTransaction.get_balance(h) == Decimal("400")

    with pytest.raises(ValidationError):
        DepositTransaction.objects.create(
            handyman=h, type="deduction", amount=Decimal("-500"), status="completed")
    # solde inchangé
    assert DepositTransaction.get_balance(h) == Decimal("400")


@pytest.mark.django_db
def test_deduct_platform_fee_cree_transaction():
    h = _user("h_fee", "handyman")
    DepositTransaction.objects.create(
        handyman=h, type="deposit", amount=Decimal("100000"), status="completed")
    prof = HandymanProfile.objects.get(user=h)
    ok = prof.deduct_platform_fee(Decimal("10000"))  # 11% par défaut = 1100
    assert ok is True
    assert DepositTransaction.get_balance(h) == Decimal("98900")


# ---------- Présence + matching ----------

@pytest.mark.django_db
def test_presence_active_le_matching(api_client):
    h = _user("h_pres", "handyman")
    cat = ServiceCategory.objects.create(name="Plomberie", slug="plomberie")
    prof = HandymanProfile.objects.get(user=h)  # auto-créé par signal
    prof.is_approved = True
    prof.location = Point(-4.017, 5.345, srid=4326)
    prof.online = False
    prof.save()
    prof.skills.add(cat)

    cli = _user("c_pres")
    payload = {"category_id": cat.id, "lat": 5.346, "lng": -4.018}

    # hors-ligne -> aucun match
    api_client.force_authenticate(user=cli)
    r = api_client.post(reverse("match"), payload, format="json")
    assert r.status_code == 200 and len(r.json()) == 0

    # l'artisan passe en ligne via l'endpoint présence
    api_client.force_authenticate(user=h)
    pr = api_client.post(reverse("handymen-presence"), {"online": True}, format="json")
    assert pr.status_code == 200 and pr.json()["online"] is True

    # désormais il est matché
    api_client.force_authenticate(user=cli)
    r2 = api_client.post(reverse("match"), payload, format="json")
    assert r2.status_code == 200 and len(r2.json()) >= 1


# ---------- API transition + status read-only ----------

@pytest.mark.django_db
def test_api_transition_et_status_readonly(api_client):
    c = _user("c_api")
    b = _booking(c, _user("h_api", "handyman"))
    api_client.force_authenticate(user=c)

    url = reverse("bookings-transition", kwargs={"pk": b.pk})
    # transition invalide -> 400
    bad = api_client.post(url, {"status": "completed"}, format="json")
    assert bad.status_code == 400

    # transition valide -> 200
    ok = api_client.post(url, {"status": "confirmed"}, format="json")
    assert ok.status_code == 200
    b.refresh_from_db()
    assert b.status == "confirmed"

    # status NON modifiable via PATCH (read-only)
    api_client.patch(
        reverse("bookings-detail", kwargs={"pk": b.pk}),
        {"status": "completed"}, format="json",
    )
    b.refresh_from_db()
    assert b.status == "confirmed"  # inchangé
