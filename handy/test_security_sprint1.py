"""Tests de non-régression pour les correctifs de sécurité du Sprint 1.

Couvre :
- blocage de l'escalade de rôle à l'inscription (user_type=admin),
- authentification HMAC du webhook de paiement,
- cloisonnement des données (anti-IDOR) sur les réservations.

Les fixtures sont créées via l'ORM pour ne pas dépendre du sérialiseur de
création de Booking (bug pré-existant hors périmètre Sprint 1).
"""
import hashlib
import hmac
import json

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from handy.models import User, Booking, Payment


@pytest.fixture
def api_client(db):
    return APIClient()


def _user(username, utype="client"):
    return User.objects.create_user(
        username=username, email=f"{username}@ex.com",
        password="pass1234", user_type=utype, is_verified=True,
    )


def _booking(client, handyman):
    return Booking.objects.create(
        client=client, handyman=handyman,
        booking_date="2030-01-01T10:00:00Z",
        address="Cocody", city="Abidjan", postal_code="00225",
    )


# ---------- Escalade de rôle ----------

@pytest.mark.django_db
def test_signup_rejette_role_admin(api_client):
    url = reverse("users-list")
    res = api_client.post(url, {
        "username": "evil", "email": "evil@ex.com",
        "password": "pass1234", "user_type": "admin",
    }, format="json")
    assert res.status_code == 400
    assert not User.objects.filter(username="evil").exists()


@pytest.mark.django_db
def test_signup_client_ok_sans_privilege(api_client):
    url = reverse("users-list")
    res = api_client.post(url, {
        "username": "alice", "email": "alice@ex.com",
        "password": "pass1234", "user_type": "client",
    }, format="json")
    assert res.status_code == 201, res.content
    u = User.objects.get(username="alice")
    assert u.is_staff is False and u.is_superuser is False


# ---------- Webhook de paiement signé ----------

def _payment(transaction_id="ref-abc"):
    c, h = _user("cli_w"), _user("pro_w", "handyman")
    b = _booking(c, h)
    return Payment.objects.create(
        booking=b, amount=5000, platform_fee=550,
        method="cash", status="pending", transaction_id=transaction_id,
    )


@pytest.mark.django_db
@override_settings(PAYMENT_WEBHOOK_SECRET="testsecret")
def test_webhook_non_signe_rejete(api_client):
    p = _payment()
    url = reverse("payment-webhook", kwargs={"provider": "om"})
    res = api_client.post(url, {"provider_ref": p.transaction_id, "status": "completed"}, format="json")
    assert res.status_code == 401
    p.refresh_from_db()
    assert p.status == "pending"  # inchangé


@pytest.mark.django_db
@override_settings(PAYMENT_WEBHOOK_SECRET="testsecret")
def test_webhook_signe_accepte(api_client):
    p = _payment()
    url = reverse("payment-webhook", kwargs={"provider": "om"})
    body = json.dumps({"provider_ref": p.transaction_id, "status": "completed"}).encode()
    sig = hmac.new(b"testsecret", body, hashlib.sha256).hexdigest()
    res = api_client.post(url, body, content_type="application/json", HTTP_X_WEBHOOK_SIGNATURE=sig)
    assert res.status_code == 200, res.content
    p.refresh_from_db()
    # confirmation fournisseur -> séquestre (escrow), is_paid vrai
    assert p.status == "held" and p.is_paid is True


@pytest.mark.django_db
@override_settings(PAYMENT_WEBHOOK_SECRET="testsecret")
def test_webhook_mauvaise_signature_rejete(api_client):
    p = _payment()
    url = reverse("payment-webhook", kwargs={"provider": "om"})
    body = json.dumps({"provider_ref": p.transaction_id, "status": "completed"}).encode()
    res = api_client.post(url, body, content_type="application/json", HTTP_X_WEBHOOK_SIGNATURE="deadbeef")
    assert res.status_code == 401


# ---------- Anti-IDOR sur les réservations ----------

@pytest.mark.django_db
def test_idor_booking_invisible_aux_tiers(api_client):
    owner, pro = _user("owner"), _user("pro_idor", "handyman")
    intrus = _user("intrus")
    b = _booking(owner, pro)

    api_client.force_authenticate(user=intrus)
    detail = api_client.get(reverse("bookings-detail", kwargs={"pk": b.pk}))
    assert detail.status_code == 404  # cloisonné

    lst = api_client.get(reverse("bookings-list"))
    ids = [row["id"] for row in lst.json().get("results", lst.json())]
    assert b.pk not in ids


@pytest.mark.django_db
def test_proprietaire_voit_sa_booking(api_client):
    owner, pro = _user("owner2"), _user("pro_idor2", "handyman")
    b = _booking(owner, pro)
    api_client.force_authenticate(user=owner)
    detail = api_client.get(reverse("bookings-detail", kwargs={"pk": b.pk}))
    assert detail.status_code == 200
