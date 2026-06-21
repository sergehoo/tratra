"""Tests Sprint 3 — paiement bout-en-bout (escrow + payout).

- Escrow Payment : held -> released (à la complétion) + facture + gains artisan
- Escrow : remboursement à l'annulation
- Transitions escrow invalides rejetées
- Payout : gains disponibles, demande de retrait atomique, blocage si insuffisant
"""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework.test import APIClient

from handy.models import (
    User, Booking, Payment, Invoice, Payout, artisan_available_earnings,
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
    return Booking.objects.create(
        client=client, handyman=handyman, status=status,
        booking_date="2020-06-01T10:00:00Z",
        address="Cocody", city="Abidjan", postal_code="00225",
    )


def _payment(booking, status="pending", ref="tx", amount="10000", fee="1100"):
    return Payment.objects.create(
        booking=booking, amount=Decimal(amount), platform_fee=Decimal(fee),
        method="om", status=status, transaction_id=ref,
    )


# ---------- Escrow ----------

@pytest.mark.django_db
def test_escrow_release_a_la_completion_avec_facture_et_gains():
    c, h = _user("c_e1"), _user("h_e1", "handyman")
    b = _booking(c, h)
    pay = _payment(b, status="pending", ref="e1")

    pay.mark_held()                 # fournisseur confirme -> séquestre
    assert pay.status == "held" and pay.is_paid is True

    # Complétion via la machine à états -> libère le séquestre
    b.transition_to("confirmed")
    b.transition_to("in_progress")
    b.transition_to("completed")

    pay.refresh_from_db()
    assert pay.status == "released"
    assert Invoice.objects.filter(booking=b).exists()       # facture générée
    # gains = montant - commission
    assert artisan_available_earnings(h) == Decimal("8900")


@pytest.mark.django_db
def test_escrow_refund_a_lannulation():
    c, h = _user("c_e2"), _user("h_e2", "handyman")
    b = _booking(c, h)
    pay = _payment(b, status="held", ref="e2", amount="5000", fee="550")

    b.transition_to("cancelled")    # annulation -> remboursement
    pay.refresh_from_db()
    assert pay.status == "refunded"
    assert artisan_available_earnings(h) == Decimal("0.00")


@pytest.mark.django_db
def test_escrow_transition_invalide():
    c, h = _user("c_e3"), _user("h_e3", "handyman")
    pay = _payment(_booking(c, h), status="pending", ref="e3")
    with pytest.raises(ValidationError):
        pay.release()               # pending -> released interdit (doit passer par held)


# ---------- Payout ----------

@pytest.mark.django_db
def test_payout_demande_et_solde_insuffisant(api_client):
    c, h = _user("c_p1"), _user("h_p1", "handyman")
    b = _booking(c, h)
    pay = _payment(b, status="held", ref="p1", amount="10000", fee="1000")
    pay.release()                   # gains = 9000

    api_client.force_authenticate(user=h)

    av = api_client.get(reverse("payouts-available"))
    assert av.status_code == 200 and Decimal(av.json()["available"]) == Decimal("9000")

    # retrait de 5000 -> OK
    r = api_client.post(reverse("payouts-list"), {"amount": "5000"}, format="json")
    assert r.status_code == 201, r.content

    # gains dispo désormais 4000 (retrait pending déduit)
    av2 = api_client.get(reverse("payouts-available"))
    assert Decimal(av2.json()["available"]) == Decimal("4000")

    # nouveau retrait de 5000 -> refusé (gains insuffisants)
    r2 = api_client.post(reverse("payouts-list"), {"amount": "5000"}, format="json")
    assert r2.status_code == 400


@pytest.mark.django_db
def test_payout_cloisonne_par_artisan(api_client):
    """Un artisan ne voit pas les retraits d'un autre (anti-IDOR)."""
    h1, h2 = _user("h_p2", "handyman"), _user("h_p3", "handyman")
    Payout.objects.create(handyman=h1, amount=Decimal("1000"), status="pending")

    api_client.force_authenticate(user=h2)
    r = api_client.get(reverse("payouts-list"))
    results = r.json().get("results", r.json())
    assert results == [] or all(row["handyman"] == h2.id for row in results)
