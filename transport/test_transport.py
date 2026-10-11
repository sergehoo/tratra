"""Frais de déplacement : calcul déterministe (distance, tranche horaire, mode aller-retour), seuil 1 km, forfait de secours 1 000 FCFA,
fuseau d'Abidjan, montant figé et recalculé côté serveur, pas de double facturation, droits et historique du Back-Office."""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from handy.models import Booking, Payment, UserAddress
from handy.test_eligibility import artisan, service
from transport import pricing
from transport.models import TransportBand, TransportConfig, TransportConfigVersion, TransportZone
from trust.models import AuditEvent

User = get_user_model()
pytestmark = pytest.mark.django_db
BO = "/handy/backoffice/settings/transport"
KM = "transport.pricing.road_distance_km"


def at(h, m=0, *, day=date(2026, 10, 12)):  # lundi 12 octobre 2026
    return datetime.combine(day, time(h, m), tzinfo=pricing.TZ)


@pytest.fixture
def cfg():
    c = TransportConfig.current()
    c.enabled, c.mode, c.rounding_step = True, TransportConfig.ROUND_TRIP_BILLED, 1
    c.save()
    for name, s, e, rate in (("Matin", 6, 9, 250), ("Journée", 9, 17, 100), ("Soir", 17, 21, 250)):
        TransportBand.objects.create(name=name, start_time=time(s, 0), end_time=time(e, 0), rate_per_km=rate)
    return c


def calc(c, km, when, **kw):
    return pricing.compute(c, distance_km=km, when=when, **kw)


def test_rate_and_round_trip_modes_never_bill_the_return_twice(cfg):
    assert calc(cfg, 8, at(7))["amount"] == 4000                      # 8 km × 2 (aller + retour) × 250
    assert calc(cfg, 8, at(7))["multiplier"] == 2
    cfg.mode = TransportConfig.ROUND_TRIP_INCLUDED
    r = calc(cfg, 8, at(7))
    assert r["amount"] == 2000 and r["multiplier"] == 1               # tarif d'aller simple, retour inclus : 8 × 250
    assert calc(cfg, 8, at(10))["amount"] == 800                      # 8 × 100
    assert calc(cfg, 8, at(10))["band"]["name"] == "Journée" and r["version"] == cfg.version


def test_threshold_is_free_up_to_one_km_and_configurable(cfg):
    assert calc(cfg, 1.0, at(7))["amount"] == 0 and calc(cfg, 1.0, at(7))["reason"] == "within_threshold"
    assert calc(cfg, 1.01, at(7))["amount"] > 0
    cfg.threshold_km = Decimal("2.5")
    assert calc(cfg, 2.5, at(7))["amount"] == 0 and calc(cfg, 2.6, at(7))["amount"] > 0


def test_flat_fallback_when_no_rate_applies_or_distance_unavailable(cfg):
    night = calc(cfg, 8, at(23))                                      # aucune tranche à 23 h
    assert night["amount"] == 1000 and night["fallback"] and night["fallback_reason"] == "no_applicable_rate"
    unknown = calc(cfg, None, at(7))
    assert unknown["amount"] == 1000 and unknown["distance_unavailable"] and unknown["fallback_reason"] == "distance_unavailable"
    assert calc(cfg, 8, at(23), needs_travel=False)["amount"] == 0    # le forfait ne vise que les missions avec déplacement
    assert calc(cfg, None, at(7), needs_travel=False)["reason"] == "no_travel"


def test_disabled_configuration_adds_nothing_and_effective_date_is_respected(cfg):
    cfg.enabled = False
    assert calc(cfg, 8, at(7))["amount"] == 0 and calc(cfg, 8, at(7))["reason"] == "disabled"
    cfg.enabled, cfg.effective_from = True, date(2026, 10, 20)
    assert calc(cfg, 8, at(7))["reason"] == "disabled"                # pas encore applicable
    assert calc(cfg, 8, at(7, day=date(2026, 10, 20)))["amount"] == 4000


def test_abidjan_timezone_is_used_whatever_the_input_zone(cfg):
    plus2 = dt_timezone(timedelta(hours=2))
    assert pricing.local(datetime(2026, 10, 12, 8, 30, tzinfo=plus2)).hour == 6      # 08:30 (+02:00) = 06:30 à Abidjan (UTC+0)
    assert calc(cfg, 8, datetime(2026, 10, 12, 8, 30, tzinfo=plus2))["band"]["name"] == "Matin"
    assert calc(cfg, 8, datetime(2026, 10, 12, 5, 59, tzinfo=dt_timezone.utc))["fallback"] is True


def test_days_validity_zone_precedence_and_rounding(cfg):
    TransportBand.objects.filter(name="Journée").update(weekdays=[0, 1, 2, 3, 4])
    saturday = date(2026, 10, 17)
    assert calc(cfg, 8, at(10, day=saturday))["fallback"] is True      # la tranche ne couvre pas le samedi
    TransportBand.objects.filter(name="Journée").update(valid_to=date(2026, 10, 11))
    assert calc(cfg, 8, at(10))["fallback"] is True                    # tranche expirée
    zone = TransportZone.objects.create(name="Cocody", communes=["Cocody", "Riviéra"])
    TransportBand.objects.create(name="Cocody matin", zone=zone, start_time=time(6), end_time=time(9), rate_per_km=300)
    assert calc(cfg, 8, at(7), commune="riviera")["band"]["name"] == "Cocody matin"   # zone prioritaire, sans casse ni accents
    assert calc(cfg, 8, at(7), commune="Yopougon")["band"]["name"] == "Matin"
    cfg.rounding_step, cfg.rounding_method = 50, "up"
    assert calc(cfg, 3.31, at(7), commune="Yopougon")["amount"] == 1700    # 3,31×2×250 = 1655 → 1700 (au supérieur, pas de 50)


def test_suggestions_use_real_amounts_and_only_existing_slots(cfg):
    pro = artisan("tr_pro")
    now = at(8, day=date(2026, 10, 12))
    with mock.patch(KM, return_value=8.0):
        out = {s["key"]: s for s in pricing.suggestions(handyman=pro, destination=(5.4, -4.0), now=now)}
    assert out["now"]["amount"] == 4000 and out["tomorrow_morning"]["amount"] == 4000
    assert out["off_peak"]["amount"] == 1600 and out["peak"]["amount"] == 4000
    TransportBand.objects.all().delete()
    with mock.patch(KM, return_value=8.0):
        only = pricing.suggestions(handyman=pro, destination=(5.4, -4.0), now=now)
    assert [s["key"] for s in only] == ["now"] and only[0]["amount"] == 1000 and only[0]["fallback"]   # pas de créneau inventé
    cfg.enabled = False
    cfg.save()
    assert pricing.suggestions(handyman=pro, destination=(5.4, -4.0), now=now) == []


def member(name="tr_client"):
    return User.objects.create_user(name, f"{name}@x.test", "pass1234", is_verified=True)


def book(client, pro, svc, **extra):
    body = {"service": svc.pk, "booking_date": (timezone.now() + timedelta(days=1)).isoformat(), "address": "Rue 1", "city": "Abidjan",
            "postal_code": "00225", "lat": 5.4, "lng": -4.0, **extra}
    return client.post("/handy/bookings/", body, format="json")


def test_booking_freezes_server_computed_transport_and_rejects_stale_expected_amount(cfg):
    pro, c = artisan("tr_pro2"), member()
    svc = service(pro)
    api = APIClient()
    api.force_authenticate(c)
    with mock.patch(KM, return_value=8.0), mock.patch("transport.pricing.local", wraps=pricing.local):
        stale = book(api, pro, svc, expected_transport_fee=1)
        assert stale.status_code == 409 and stale.json()["code"] == "transport_changed" and stale.json()["quote"]["amount"] in (4000, 1600, 1000)
        assert Booking.objects.count() == 0                            # aucun enregistrement tant que le montant n'est pas confirmé
        expected = stale.json()["quote"]["amount"]
        ok = book(api, pro, svc, expected_transport_fee=expected)
    assert ok.status_code == 201
    b = Booking.objects.get()
    assert b.transport_fee == expected and b.transport_quote["version"] == cfg.version and b.transport_quote["distance_km"] == 8.0
    assert "latitude" not in str(b.transport_quote) and "origin" not in b.transport_quote           # jamais l'adresse du prestataire


def test_service_without_travel_never_pays_transport(cfg):
    pro, c = artisan("tr_pro3"), member("tr_client3")
    svc = service(pro)
    svc.requires_travel = False
    svc.save()
    api = APIClient()
    api.force_authenticate(c)
    with mock.patch(KM, return_value=8.0):
        assert book(api, pro, svc).status_code == 201
    b = Booking.objects.get()
    assert b.transport_fee == 0 and b.transport_quote["reason"] == "no_travel"


def test_payment_adds_frozen_transport_once_even_after_a_failed_attempt(cfg):
    pro, c = artisan("tr_pro4"), member("tr_client4")
    svc = service(pro)
    api = APIClient()
    api.force_authenticate(c)
    with mock.patch(KM, return_value=8.0):
        book(api, pro, svc)
    b = Booking.objects.get()
    fee = int(b.transport_fee)
    assert fee > 0
    init = {"booking_id": b.pk, "method": "cash", "minutes": 60}
    first = api.post("/handy/payments/initiate/", init, format="json")
    assert first.status_code == 201
    p = Payment.objects.get(booking=b)
    from handy.services.pricing import estimate_price

    base = Decimal(estimate_price(b.service.category.slug, 60))
    assert p.amount == base + fee
    Payment.objects.filter(pk=p.pk).update(status="failed")
    again = api.post("/handy/payments/initiate/", init, format="json")
    assert again.status_code == 201
    p.refresh_from_db()
    assert p.amount == base + fee                                      # recalculé depuis ses sources : le déplacement n'est pas ajouté deux fois


def test_requote_requires_explicit_acceptance_and_is_locked_by_a_payment(cfg):
    pro, c = artisan("tr_pro5"), member("tr_client5")
    svc = service(pro)
    api = APIClient()
    api.force_authenticate(c)
    with mock.patch(KM, return_value=8.0):
        book(api, pro, svc)
        b = Booking.objects.get()
        TransportBand.objects.update(rate_per_km=500)                  # tarifs modifiés depuis la réservation
        silent = api.post(f"/handy/bookings/{b.pk}/transport/", {}, format="json")
        assert silent.status_code == 409 and silent.json()["code"] == "transport_changed"
        b.refresh_from_db()
        old = b.transport_fee
        new = silent.json()["quote"]["amount"]
        assert new != old and b.transport_fee == old                   # rien n'a changé sans accord
        ok = api.post(f"/handy/bookings/{b.pk}/transport/", {"accept_fee": new}, format="json")
    assert ok.status_code == 200
    b.refresh_from_db()
    assert b.transport_fee == new and AuditEvent.objects.filter(action="booking.transport_requoted").exists()
    Payment.objects.create(booking=b, amount=5000, platform_fee=0, method="cash", status="pending")
    locked = api.post(f"/handy/bookings/{b.pk}/transport/", {"accept_fee": 1}, format="json")
    assert locked.status_code == 409 and locked.json()["code"] == "transport_locked"


def test_quote_endpoint_uses_own_address_only_and_hides_provider_location(cfg):
    pro, a, other = artisan("tr_pro6"), member("tr_a"), member("tr_b")
    mine = UserAddress.objects.create(user=a, city="Abidjan", commune="Cocody", street="Rue", latitude=Decimal("5.35"), longitude=Decimal("-4.0"), is_primary=True)
    theirs = UserAddress.objects.create(user=other, city="Abidjan", street="X", is_primary=True)
    svc = service(pro)
    api = APIClient()
    api.force_authenticate(a)
    with mock.patch(KM, return_value=8.0):
        r = api.post("/handy/transport/quote/", {"service": svc.pk, "address_id": mine.pk}, format="json")
        assert r.status_code == 200 and r.json()["quote"]["distance_km"] == 8.0 and r.json()["suggestions"]
        assert "5.36" not in r.content.decode() and "-4.0083" not in r.content.decode()          # point de départ du prestataire jamais exposé
        assert api.post("/handy/transport/quote/", {"service": svc.pk, "address_id": theirs.pk}, format="json").status_code == 400
    assert APIClient().post("/handy/transport/quote/", {"service": svc.pk}, format="json").status_code in (401, 403)


def test_recurring_engagement_occurrences_carry_no_automatic_transport():
    import inspect

    from engagements.services import planning

    src = inspect.getsource(planning)
    assert "transport_fee" not in src                                  # contrats : conditions du contrat uniquement
    assert Booking._meta.get_field("transport_fee").default == 0       # une occurrence créée sans devis n'a donc aucun supplément


# ═══ Back-Office ═══════════════════════════════════════════════════════════════════════════════════════════════════

def _staff(name, role):
    from backoffice.test_people import api as bo_api, staff

    return bo_api(staff(name, role))


def test_backoffice_transport_is_reserved_and_every_change_needs_a_reason_and_creates_a_version(cfg):
    support = _staff("tr_support", "support")
    assert support.get(f"{BO}/").status_code == 403 and support.put(f"{BO}/", {"enabled": False, "reason": "essai"}, format="json").status_code == 403
    admin = _staff("tr_admin", "super_admin")
    overview = admin.get(f"{BO}/").json()
    assert overview["config"]["threshold_km"] == "1.00" and overview["config"]["fallback_flat_amount"] == 1000 and overview["timezone"] == "Africa/Abidjan"
    assert overview["example"] and overview["example"][0]["distance_km"] == 8.0                 # exemple chiffré avec les tarifs configurés
    no_reason = admin.put(f"{BO}/", {"fallback_flat_amount": 1500}, format="json")
    assert no_reason.status_code == 400 and "reason" in no_reason.json()["fields"]
    before = TransportConfig.current().version
    ok = admin.put(f"{BO}/", {"fallback_flat_amount": 1500, "mode": "round_trip_included", "reason": "Politique 2026"}, format="json")
    assert ok.status_code == 200 and ok.json()["version"] == before + 1
    assert TransportConfigVersion.objects.get(version=before + 1).snapshot["config"]["mode"] == "round_trip_included"
    event = AuditEvent.objects.get(action="backoffice.transport.config_updated")
    assert event.data["changes"]["fallback_flat_amount"] == {"old": "1000", "new": "1500"}
    assert admin.put(f"{BO}/", {"mode": "inconnu", "reason": "essai"}, format="json").status_code == 400
    unchanged = admin.put(f"{BO}/", {"fallback_flat_amount": 1500, "reason": "Sans changement"}, format="json").json()
    assert unchanged["version"] == before + 1                                                    # aucune modification : pas de nouvelle version


def test_backoffice_bands_and_zones_validate_overlaps_and_are_never_deleted(cfg):
    admin = _staff("tr_admin2", "super_admin")
    body = {"name": "Chevauche", "start": "08:00", "end": "10:00", "weekdays": [0, 1], "rate_per_km": "120", "reason": "Nouvelle tranche"}
    clash = admin.post(f"{BO}/bands/", body, format="json")
    assert clash.status_code == 400 and "start" in clash.json()["fields"]                       # chevauche « Matin » (06–09) le lundi
    assert admin.post(f"{BO}/bands/", {**body, "weekdays": [6], "start": "22:00", "end": "21:00"}, format="json").status_code == 400
    zone = admin.post(f"{BO}/zones/", {"name": "Plateau", "communes": ["Plateau"], "reason": "Zone dense"}, format="json")
    assert zone.status_code == 201 and admin.post(f"{BO}/zones/", {"name": "plateau", "communes": ["x"], "reason": "doublon"}, format="json").status_code == 400
    ok = admin.post(f"{BO}/bands/", {**body, "zone": zone.json()["id"]}, format="json")           # même plage mais zone différente : autorisé
    assert ok.status_code == 201
    off = admin.patch(f"{BO}/bands/{ok.json()['id']}/", {"is_active": False, "reason": "Retirée"}, format="json")
    assert off.status_code == 200 and off.json()["is_active"] is False and TransportBand.objects.filter(pk=ok.json()["id"]).exists()
    assert admin.delete(f"{BO}/bands/{ok.json()['id']}/").status_code == 405                     # pas de suppression : on désactive
    assert AuditEvent.objects.filter(action__in=["backoffice.transport.band_created", "backoffice.transport.zone_created"]).count() == 2
