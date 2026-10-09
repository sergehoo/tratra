"""Réservations : non-régression de l'historique après la règle d'éligibilité, et refus explicites.

Seules les NOUVELLES réservations exigent un artisan éligible : une réservation existante reste
consultable, gérable (statuts), payable et notable par ses deux parties même si l'artisan n'est
plus (ou n'a jamais été) éligible. Les entrées invalides renvoient toujours 400, jamais 500.
"""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from handy.models import Booking
from handy.test_eligibility import BREAKERS, artisan, service

User = get_user_model()
pytestmark = pytest.mark.django_db
STATUSES = ["pending", "confirmed", "in_progress", "completed", "cancelled"]


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _client(username="hist_client"):
    return User.objects.create_user(username, f"{username}@x.test", "pass1234", user_type="client", is_verified=True)


def _booking(client, handyman, svc=None, status="pending", **extra):
    return Booking.objects.create(
        client=client, handyman=handyman, service=svc, status=status, address="Rue 12", city="Abidjan",
        booking_date=timezone.now() + timedelta(days=1), **extra)


def _payload(**extra):
    return {"booking_date": (timezone.now() + timedelta(days=2)).isoformat(), "address": "Rue 12",
            "city": "Abidjan", "postal_code": "00225", **extra}


# ---- A. Historique : l'artisan perd (ou n'a jamais eu) l'éligibilité ---------------------------------

@pytest.mark.parametrize("case", [k for k in BREAKERS if k != "complet"])
def test_existing_bookings_stay_usable_when_the_artisan_is_no_longer_eligible(case):
    cli, art = _client(), artisan("hist_" + case)
    svc = service(art, "Dépannage")
    ids = {s: _booking(cli, art, svc, status=s).id for s in STATUSES}
    profile = art.handyman_profile
    BREAKERS[case](profile)
    profile.save()
    svc.is_active = False  # la prestation n'est plus publiée non plus
    svc.save()

    ca, ch = _api(cli), _api(art)
    # consultation par les deux parties, prestation incluse
    for api in (ca, ch):
        for pk in ids.values():
            r = api.get(reverse("bookings-detail", args=[pk]))
            assert r.status_code == 200, (case, r.content)
            assert r.json()["service_detail"]["title"] == "Dépannage"
    assert {b["id"] for b in ca.get(reverse("bookings-list"), {"client": cli.id}).json()["results"]} == set(ids.values())
    assert {b["id"] for b in ch.get(reverse("bookings-list"), {"handyman": art.id}).json()["results"]} == set(ids.values())
    dash = ca.get("/handy/me/dashboard/").json()
    assert dash["client"]["bookings"]["total"] == len(STATUSES)

    # cycle de vie : l'artisan fait avancer la mission, le client peut annuler, puis noter
    assert ch.post(reverse("bookings-transition", args=[ids["pending"]]), {"status": "confirmed"}, format="json").status_code == 200
    assert ch.post(reverse("bookings-transition", args=[ids["confirmed"]]), {"status": "in_progress"}, format="json").status_code == 200
    assert ch.post(reverse("bookings-transition", args=[ids["in_progress"]]), {"status": "completed"}, format="json").status_code == 200
    r = ca.post("/handy/reviews/", {"booking": ids["completed"], "rating": 5, "comment": "Très bien"}, format="json")
    assert r.status_code == 201, r.content
    extra = _booking(cli, art, svc, status="pending")
    assert ca.post(reverse("bookings-transition", args=[extra.id]), {"status": "cancelled"}, format="json").status_code == 200

    # …mais une NOUVELLE réservation chez cet artisan est refusée, explicitement
    r = ca.post(reverse("bookings-list"), _payload(service=svc.id, handyman=art.id), format="json")
    assert r.status_code == 400, (case, r.content)


def test_payment_of_an_existing_booking_still_works_for_an_ineligible_artisan():
    cli, art = _client("pay_client"), artisan("pay_art", eligible=False)
    svc = service(art, "Plomberie")
    b = _booking(cli, art, svc, status="confirmed")
    r = _api(cli).post("/handy/payments/initiate/", {"booking_id": b.id, "method": "cash", "minutes": 60}, format="json")
    assert r.status_code in (201, 503), r.content  # 503 = fournisseur du moyen de paiement absent ; jamais 400/500
    assert r.status_code != 500


# ---- B. Réservation sans artisan : refusée explicitement (400), jamais 500 -------------------------

def test_booking_needs_an_artisan_and_never_returns_500():
    cli = _client("noart_client")
    art = artisan("noart_art")
    svc = service(art, "OK")
    other_user = User.objects.create_user("noart_plain", "p@x.test", "pass1234")  # aucun profil artisan
    inactive_svc = service(artisan("noart_off"), "Inactif", active=False)
    unverified_svc = service(artisan("noart_unv", eligible=False), "Non vérifié")
    api = _api(cli)
    url = reverse("bookings-list")

    refused = {
        "ni service ni artisan": _payload(),
        "artisan nul": _payload(handyman=None),
        "service nul": _payload(service=None),
        "artisan inexistant": _payload(handyman=999999),
        "artisan = n'importe quoi": _payload(handyman="abc"),
        "service inexistant": _payload(service=999999),
        "artisan sans profil": _payload(handyman=other_user.id),
        "service inactif": _payload(service=inactive_svc.id),
        "service d'un artisan non éligible": _payload(service=unverified_svc.id),
        "artisan non éligible seul": _payload(handyman=unverified_svc.handyman_id),
        "artisan ≠ artisan du service": _payload(service=svc.id, handyman=other_user.id),
        "date absente": {"service": svc.id},
        "date invalide": _payload(service=svc.id, booking_date="pas-une-date"),
        "corps vide": {},
    }
    for label, payload in refused.items():
        r = api.post(url, payload, format="json")
        assert r.status_code == 400, (label, r.status_code, r.content)
        assert r.json(), label  # message explicite, jamais un corps vide
    assert not Booking.objects.exists()

    # parcours autorisé : la prestation seule suffit, l'artisan est celui de la prestation
    ok = api.post(url, _payload(service=svc.id), format="json")
    assert ok.status_code == 201, ok.content
    assert Booking.objects.get(pk=ok.json()["id"]).handyman_id == art.id
    # …et l'artisan ne peut pas réserver sa propre prestation
    assert _api(art).post(url, _payload(service=svc.id), format="json").status_code == 400


def test_no_artisan_error_names_the_missing_field():
    r = _api(_client("msg_client")).post(reverse("bookings-list"), _payload(), format="json")
    assert r.status_code == 400
    assert "handyman" in r.json()
    assert "prestation" in str(r.json()["handyman"]).lower() or "artisan" in str(r.json()["handyman"]).lower()
