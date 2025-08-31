from django.test import TestCase

# Create your tests here.
# tests/test_api_endpoints.py
import pytest
from django.urls import reverse
from django.utils import timezone
from django.contrib.gis.geos import Point

from rest_framework.test import APIClient

from handy.models import (
    User, ServiceCategory, Service, HandymanProfile, Booking,
    Payment
)


@pytest.fixture
def api_client(db):
    return APIClient()


@pytest.fixture
def user_client(db):
    return User.objects.create_user(
        username="client1",
        email="client1@example.com",
        password="pass1234",
        user_type="client",
        is_verified=True,
    )


@pytest.fixture
def user_handyman(db):
    return User.objects.create_user(
        username="pro1",
        email="pro1@example.com",
        password="pass1234",
        user_type="handyman",
        is_verified=True,
    )


@pytest.fixture
def category(db):
    return ServiceCategory.objects.create(name="Plomberie", slug="plomberie", description="Travaux plomberie")


@pytest.fixture
def handyman_profile(db, user_handyman, category):
    hp = HandymanProfile.objects.create(
        user=user_handyman,
        is_approved=True,
        rating=4.5,
        completed_jobs=10,
        online=True,
        location=Point(-4.017, 5.345, srid=4326),  # Abidjan (ex.)
    )
    hp.skills.add(category)
    return hp


@pytest.fixture
def service(db, user_handyman, category):
    return Service.objects.create(
        handyman=user_handyman,
        category=category,
        title="Réparation fuite",
        description="Recherche et réparation de fuite",
        price_type="fixed",
        price=5000,
        is_active=True,
    )


@pytest.fixture
def auth_client(api_client, user_client):
    api_client.force_authenticate(user=user_client)
    return api_client


@pytest.mark.django_db
def test_price_estimate(api_client):
    url = reverse("price-estimate")
    payload = {"category_slug": "plomberie", "minutes": 90}
    res = api_client.post(url, payload, format="json")
    assert res.status_code == 200
    assert "amount_xof" in res.json()
    assert isinstance(res.json()["amount_xof"], int)


@pytest.mark.django_db
def test_match_endpoint(auth_client, handyman_profile, category):
    url = reverse("match")
    payload = {"category_id": category.id, "lat": 5.346, "lng": -4.018}
    res = auth_client.post(url, payload, format="json")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # champs attendus
    assert {"id", "full_name", "rating", "completed_jobs", "distance_m"}.issubset(data[0].keys())


@pytest.mark.django_db
def test_booking_create_and_timeline(auth_client, user_handyman, service):
    # CREATE
    url = reverse("bookings-list")  # DRF router basename "bookings"
    start = timezone.now() + timezone.timedelta(hours=2)
    payload = {
        "handyman": user_handyman.id,
        "service": service.id,
        "booking_date": start.isoformat(),
        "end_date": (start + timezone.timedelta(hours=1)).isoformat(),
        "address": "Cocody Riviera",
        "city": "Abidjan",
        "postal_code": "00225",
        "description": "Urgence robinet",
        "proposed_price": "6000",
        "type": "scheduled",
        "minutes": 60,
        "category_id": service.category_id,
    }
    res = auth_client.post(url, payload, format="json")
    assert res.status_code == 201, res.content
    b_id = res.json()["id"]

    # TIMELINE
    tl_url = reverse("bookings-timeline", kwargs={"pk": b_id})
    tl_res = auth_client.get(tl_url)
    assert tl_res.status_code == 200
    assert "status" in tl_res.json()
    assert "payment_logs" in tl_res.json()


@pytest.mark.django_db
def test_payment_initiate_and_webhook(auth_client, user_handyman, service):
    # 1) créer une réservation
    create_url = reverse("bookings-list")
    start = timezone.now() + timezone.timedelta(hours=1)
    payload = {
        "handyman": user_handyman.id,
        "service": service.id,
        "booking_date": start.isoformat(),
        "end_date": (start + timezone.timedelta(hours=1)).isoformat(),
        "address": "Plateau",
        "city": "Abidjan",
        "postal_code": "00225",
        "description": "Réparation",
        "proposed_price": "7000",
        "type": "scheduled",
        "minutes": 60,
        "category_id": service.category_id,
    }
    res = auth_client.post(create_url, payload, format="json")
    assert res.status_code == 201, res.content
    booking_id = res.json()["id"]

    # 2) initier un paiement (OM)
    pay_init_url = reverse("payment-initiate")
    pay_payload = {"booking_id": booking_id, "method": "om", "minutes": 60, "category_id": service.category_id}
    pay_res = auth_client.post(pay_init_url, pay_payload, format="json")
    assert pay_res.status_code == 201, pay_res.content
    data = pay_res.json()
    assert "payment_id" in data
    assert "provider_ref" in data
    provider_ref = data["provider_ref"]

    # 3) vérifier objet Payment créé
    p = Payment.objects.get(id=data["payment_id"])
    assert p.booking_id == booking_id
    assert p.transaction_id == provider_ref
    assert p.status == "pending"

    # 4) webhook -> completed
    webhook_url = reverse("payment-webhook", kwargs={"provider": "om"})
    webhook_payload = {"provider_ref": provider_ref, "status": "completed"}
    w_res = api_client.post(webhook_url, webhook_payload, format="json")  # webhook sans auth
    assert w_res.status_code == 200, w_res.content

    # 5) recharger depuis DB et valider
    p.refresh_from_db()
    assert p.status == "completed"