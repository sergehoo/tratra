"""Tests scoring qualité + OTP + coupons.

- Score de confiance composite (note/volume/KYC/complétude), recalcul sur avis
- OTP : génération, vérification (succès / mauvais code / expiré) -> is_verified
- Coupons : validité, réduction %/montant, endpoint de validation, application au paiement
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient

from handy.models import (
    User, Booking, Service, ServiceCategory, HandymanProfile,
    Review, Coupon, OTPCode, Payment,
)


@pytest.fixture
def api_client(db):
    return APIClient()


def _user(u, t="client", verified=True):
    return User.objects.create_user(
        username=u, email=f"{u}@ex.com", password="pass1234", user_type=t, is_verified=verified)


# ---------- Scoring qualité ----------

@pytest.mark.django_db
def test_quality_score_composite():
    h = _user("h_q1", "handyman")
    p = HandymanProfile.objects.get(user=h)
    p.rating = 4.0
    p.completed_jobs = 50
    p.is_approved = True
    p.save()
    # note 40 + volume 25 + KYC 15 + complétude 0 (profil vide) = 80
    assert p.compute_quality_score() == 80


@pytest.mark.django_db
def test_avis_met_a_jour_quality_score():
    c, h = _user("c_q2"), _user("h_q2", "handyman")
    p = HandymanProfile.objects.get(user=h)
    p.is_approved = True
    p.save()
    b = Booking.objects.create(
        client=c, handyman=h, status="completed",
        booking_date=timezone.now() - timedelta(days=1),
        address="a", city="Abidjan", postal_code="0")
    Review.objects.create(booking=b, rating=5)  # signal -> rating + quality_score

    p.refresh_from_db()
    assert p.rating == 5.0
    assert 60 <= p.quality_score <= 70  # 50 (note) + 15 (KYC) = 65


# ---------- OTP ----------

@pytest.mark.django_db
def test_otp_request_puis_verify(api_client):
    u = _user("u_otp", verified=False)
    api_client.force_authenticate(user=u)

    r = api_client.post(reverse("otp-request"), {}, format="json")
    assert r.status_code == 201
    otp = OTPCode.objects.filter(user=u).latest("created_at")

    wrong = "111111" if otp.code != "111111" else "222222"
    bad = api_client.post(reverse("otp-verify"), {"code": wrong}, format="json")
    assert bad.status_code == 400

    ok = api_client.post(reverse("otp-verify"), {"code": otp.code}, format="json")
    assert ok.status_code == 200
    u.refresh_from_db()
    assert u.is_verified is True


@pytest.mark.django_db
def test_otp_expire_rejete(api_client):
    u = _user("u_otp2", verified=False)
    OTPCode.objects.create(user=u, code="123456", purpose="signup",
                           expires_at=timezone.now() - timedelta(minutes=1))
    api_client.force_authenticate(user=u)
    r = api_client.post(reverse("otp-verify"), {"code": "123456"}, format="json")
    assert r.status_code == 400
    u.refresh_from_db()
    assert u.is_verified is False


# ---------- Coupons ----------

@pytest.mark.django_db
def test_coupon_validite_et_reduction():
    now = timezone.now()
    c1 = Coupon.objects.create(code="P20", percent_off=Decimal("20"),
                               valid_from=now - timedelta(days=1), valid_to=now + timedelta(days=1), active=True)
    assert c1.is_valid() is True
    assert c1.discount_for(Decimal("10000")) == Decimal("2000")
    assert c1.apply(Decimal("10000")) == Decimal("8000")

    c2 = Coupon.objects.create(code="A1500", amount_off=Decimal("1500"),
                               valid_from=now - timedelta(days=1), valid_to=now + timedelta(days=1), active=True)
    assert c2.apply(Decimal("10000")) == Decimal("8500")

    expired = Coupon.objects.create(code="OLD", percent_off=Decimal("50"),
                                    valid_from=now - timedelta(days=5), valid_to=now - timedelta(days=1), active=True)
    assert expired.is_valid() is False


@pytest.mark.django_db
def test_coupon_validate_endpoint(api_client):
    now = timezone.now()
    Coupon.objects.create(code="WELCOME", percent_off=Decimal("10"),
                          valid_from=now - timedelta(days=1), valid_to=now + timedelta(days=1), active=True)
    u = _user("u_cp")
    api_client.force_authenticate(user=u)

    r = api_client.post(reverse("coupon-validate"), {"code": "WELCOME", "amount": "5000"}, format="json")
    assert r.status_code == 200 and r.json()["valid"] is True
    assert r.json()["net"] == "4500"

    r2 = api_client.post(reverse("coupon-validate"), {"code": "NOPE", "amount": "5000"}, format="json")
    assert r2.json()["valid"] is False


@pytest.mark.django_db
def test_payment_initiate_applique_le_coupon(api_client):
    cat = ServiceCategory.objects.create(name="Plomberie", slug="plomberie")
    h, c = _user("h_cp", "handyman"), _user("c_cp")
    svc = Service.objects.create(handyman=h, category=cat, title="s", description="d",
                                 price_type="fixed", price=Decimal("5000"), is_active=True)
    b = Booking.objects.create(client=c, handyman=h, service=svc, status="pending",
                               booking_date=timezone.now() + timedelta(days=1),
                               address="a", city="Abidjan", postal_code="0")
    now = timezone.now()
    Coupon.objects.create(code="P50", percent_off=Decimal("50"),
                          valid_from=now - timedelta(days=1), valid_to=now + timedelta(days=1), active=True)

    api_client.force_authenticate(user=c)
    r = api_client.post(reverse("payment-initiate"), {
        "booking_id": b.id, "method": "om", "minutes": 60,
        "category_id": cat.id, "coupon_code": "P50",
    }, format="json")
    assert r.status_code == 201, r.content
    pay = Payment.objects.get(booking=b)
    assert pay.coupon is not None
    assert pay.discount > 0
