"""Tests Absences/Remplacement + Sprint 5 (notifications, tracking).

- Absences (TimeOff) : exclusion du matching, déclaration via API
- Remplacement : génération auto sur absence impactante + acceptation (réassignation)
- Notifications : la tâche notify_booking_status crée des notifs in-app (2 parties),
  _send_fcm ne plante pas sans device
- Tracking GPS : helper d'autorisation (parties seulement)
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient

from handy.models import (
    User, Booking, Service, ServiceCategory, HandymanProfile,
    TimeOff, ReplacementSuggestion, Notification,
)
from handy.services.matching import match_artisans
from handy.services.tracking import can_access_booking_tracking
from handy.tasks import notify_booking_status, _send_fcm


@pytest.fixture
def api_client(db):
    return APIClient()


def _user(u, t="client"):
    return User.objects.create_user(
        username=u, email=f"{u}@ex.com", password="pass1234", user_type=t, is_verified=True)


def _artisan_ready(u, cat, *, online=True, approved=True):
    h = _user(u, "handyman")
    p = HandymanProfile.objects.get(user=h)  # auto-créé par signal
    p.is_approved = approved
    p.online = online
    p.location = Point(-4.017, 5.345, srid=4326)
    p.save()
    p.skills.add(cat)
    return h, p


def _service(h, cat, title="svc", price="5000"):
    return Service.objects.create(
        handyman=h, category=cat, title=title, description="d",
        price_type="fixed", price=Decimal(price), is_active=True)


def _future_booking(client, handyman, service=None, status="confirmed"):
    return Booking.objects.create(
        client=client, handyman=handyman, service=service, status=status,
        booking_date=timezone.now() + timedelta(days=1),
        address="Cocody", city="Abidjan", postal_code="00225")


# ---------- Absences (TimeOff) ----------

@pytest.mark.django_db
def test_matching_exclut_artisan_en_conge():
    cat = ServiceCategory.objects.create(name="Plomberie", slug="plomberie")
    h, p = _artisan_ready("h_to1", cat)
    assert len(list(match_artisans(5.346, -4.018, cat.id))) == 1

    TimeOff.objects.create(handyman=p,
                           start=timezone.now() - timedelta(hours=1),
                           end=timezone.now() + timedelta(hours=1))
    assert p.is_on_timeoff() is True
    assert len(list(match_artisans(5.346, -4.018, cat.id))) == 0


@pytest.mark.django_db
def test_declaration_absence_genere_remplacements(api_client):
    cat = ServiceCategory.objects.create(name="Elec", slug="elec")
    h1, p1 = _artisan_ready("h_r1", cat)
    s1 = _service(h1, cat, "s1")
    h2, p2 = _artisan_ready("h_r2", cat)        # remplaçant potentiel
    s2 = _service(h2, cat, "s2")
    c = _user("c_r1")
    b = _future_booking(c, h1, s1)              # mission confirmée avec h1

    api_client.force_authenticate(user=h1)
    r = api_client.post(reverse("timeoffs-list"), {
        "start": timezone.now().isoformat(),
        "end": (timezone.now() + timedelta(days=2)).isoformat(),
    }, format="json")
    assert r.status_code == 201, r.content
    # une suggestion vers le service de h2 a été générée pour la mission impactée
    assert ReplacementSuggestion.objects.filter(booking=b, suggested_service=s2).exists()


# ---------- Remplacement ----------

@pytest.mark.django_db
def test_accept_replacement_reassigne_la_mission(api_client):
    cat = ServiceCategory.objects.create(name="Menuiserie", slug="menuiserie")
    h1, p1 = _artisan_ready("h_a1", cat)
    s1 = _service(h1, cat, "s1")
    h2, p2 = _artisan_ready("h_a2", cat)
    s2 = _service(h2, cat, "s2")
    c = _user("c_a1")
    b = _future_booking(c, h1, s1)
    sugg = ReplacementSuggestion.objects.create(
        booking=b, suggested_service=s2, original_service=s1, score=4.5)

    api_client.force_authenticate(user=c)
    r = api_client.post(reverse("bookings-accept-replacement", kwargs={"pk": b.id}),
                        {"suggestion_id": sugg.id}, format="json")
    assert r.status_code == 200, r.content
    b.refresh_from_db()
    assert b.handyman_id == h2.id and b.service_id == s2.id


# ---------- Notifications (Sprint 5) ----------

@pytest.mark.django_db
def test_notify_booking_status_notifie_les_deux_parties():
    c, h = _user("c_n1"), _user("h_n1", "handyman")
    b = _future_booking(c, h)
    notify_booking_status(b.id, "confirmed")   # appel direct (synchrone)
    assert Notification.objects.filter(user=c, notification_type="booking_status").count() == 1
    assert Notification.objects.filter(user=h, notification_type="booking_status").count() == 1


@pytest.mark.django_db
def test_send_fcm_sans_device_ne_plante_pas():
    u = _user("u_fcm")
    _send_fcm(u.id, "Titre", "Corps", {"x": 1})   # ne doit lever aucune exception


# ---------- Tracking GPS (Sprint 5) ----------

@pytest.mark.django_db
def test_tracking_autorisation_parties_seulement():
    c, h, tier = _user("c_t1"), _user("h_t1", "handyman"), _user("tier_t")
    b = _future_booking(c, h)
    assert can_access_booking_tracking(c, b.id) is True
    assert can_access_booking_tracking(h, b.id) is True
    assert can_access_booking_tracking(tier, b.id) is False
    assert can_access_booking_tracking(None, b.id) is False
