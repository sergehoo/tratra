"""Adresses et recherche d'adresse : propriétaire seul, adresse principale unique, consentement pour la position de l'appareil,
cache et limite des appels externes, panne du fournisseur => saisie manuelle, aucune donnée privée dans le cache ni dans les journaux."""
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient

from handy import geo
from handy.models import UserAddress

User = get_user_model()
pytestmark = pytest.mark.django_db
ADDR, GEO = "/handy/me/addresses/", "/handy/geo"


def member(name="adr_a"):
    return User.objects.create_user(name, f"{name}@x.test", "pass1234", is_verified=True)


def client(u):
    c = APIClient()
    c.force_authenticate(u)
    return c


GOOD = {"label": "Maison", "city": "Abidjan", "commune": "Cocody", "street": "Rue des Jardins", "latitude": 5.36, "longitude": -4.0083}


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()


def test_first_address_is_primary_and_mirrors_legacy_fields():
    u = member()
    r = client(u).post(ADDR, GOOD, format="json")
    assert r.status_code == 201 and r.json()["is_primary"] is True and r.json()["country"] == "Côte d'Ivoire"
    u.refresh_from_db()
    assert u.city == "Abidjan" and u.address == "Rue des Jardins, Cocody" and float(u.latitude) == 5.36
    assert client(u).get(ADDR).json()["complete"] is True


def test_only_one_primary_secondary_and_promotion_on_delete():
    u = member()
    c = client(u)
    a1 = c.post(ADDR, GOOD, format="json").json()
    a2 = c.post(ADDR, {"city": "Bouaké", "street": "Av. 1"}, format="json").json()
    assert a2["is_primary"] is False
    c.post(f"{ADDR}{a2['id']}/primary/")
    prim = list(UserAddress.objects.filter(user=u, is_primary=True).values_list("pk", flat=True))
    assert prim == [a2["id"]]
    u.refresh_from_db()
    assert u.city == "Bouaké"
    assert c.delete(f"{ADDR}{a2['id']}/").status_code == 204
    assert UserAddress.objects.get(pk=a1["id"]).is_primary is True              # la plus récente restante devient principale
    u.refresh_from_db()
    assert u.city == "Abidjan"


def test_validation_and_limits():
    c = client(member())
    assert c.post(ADDR, {"city": "", "street": "x"}, format="json").status_code == 400
    assert c.post(ADDR, {"city": "Abidjan"}, format="json").json()["street"]                      # rue ou quartier requis
    assert c.post(ADDR, {**GOOD, "latitude": 95}, format="json").json()["latitude"]
    assert c.post(ADDR, {**GOOD, "longitude": None}, format="json").json()["latitude"]            # le couple lat/lng va ensemble
    for _ in range(UserAddress.MAX_PER_USER):
        assert c.post(ADDR, GOOD, format="json").status_code == 201
    assert c.post(ADDR, GOOD, format="json").status_code == 400


def test_device_position_requires_explicit_consent():
    c = client(member())
    r = c.post(ADDR, {**GOOD, "coords_source": "device"}, format="json")
    assert r.status_code == 400 and "location_consent" in r.json()
    ok = c.post(ADDR, {**GOOD, "coords_source": "device", "location_consent": True}, format="json")
    assert ok.status_code == 201
    assert UserAddress.objects.get(pk=ok.json()["id"]).location_consent_at is not None


def test_addresses_are_private_to_their_owner():
    a, b = member("adr_a"), member("adr_b")
    mine = client(a).post(ADDR, GOOD, format="json").json()
    cb = client(b)
    assert cb.get(ADDR).json()["results"] == []
    assert cb.get(f"{ADDR}{mine['id']}/").status_code == 404
    assert cb.patch(f"{ADDR}{mine['id']}/", {"city": "X"}, format="json").status_code == 404
    assert cb.delete(f"{ADDR}{mine['id']}/").status_code == 404
    assert cb.post(f"{ADDR}{mine['id']}/primary/").status_code == 404
    assert UserAddress.objects.get(pk=mine["id"]).city == "Abidjan"
    assert APIClient().get(ADDR).status_code in (401, 403)


NOMINATIM = [{"display_name": "Rue des Jardins, Cocody, Abidjan", "lat": "5.3600", "lon": "-4.0083",
              "address": {"road": "Rue des Jardins", "suburb": "Cocody", "city": "Abidjan", "country": "Côte d'Ivoire"}}]


def fake_response(payload):
    r = mock.Mock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


def test_search_is_cached_normalized_and_country_biased(settings):
    settings.GEO_PROVIDER = "nominatim"
    with mock.patch("handy.geo.requests.get", return_value=fake_response(NOMINATIM)) as get:
        c = client(member())
        r1 = c.get(f"{GEO}/search/", {"q": "  Rue des  Jardins "}).json()
        r2 = c.get(f"{GEO}/search/", {"q": "rue des jardins"}).json()
    assert r1["results"][0]["commune"] == "Cocody" and r1["results"] == r2["results"]
    assert get.call_count == 1                                                                      # la 2e recherche vient du cache
    assert get.call_args.kwargs["params"]["countrycodes"] == "ci"
    assert c.get(f"{GEO}/search/", {"q": "ab"}).json()["results"] == []                           # < 3 caractères : aucun appel externe


def test_provider_failure_falls_back_to_manual_entry_without_hammering(settings):
    settings.GEO_PROVIDER = "nominatim"
    c = client(member())
    with mock.patch("handy.geo.requests.get", side_effect=TimeoutError("boom")) as get:
        r = c.get(f"{GEO}/search/", {"q": "cocody"})
        again = c.get(f"{GEO}/search/", {"q": "plateau"})
    assert r.status_code == 503 and r.json()["manual_entry"] is True and "boom" not in r.content.decode()
    assert again.status_code == 503 and get.call_count == 1                                          # panne mémorisée 30 s


def test_outgoing_calls_are_limited_and_provider_none_makes_no_call(settings):
    settings.GEO_PROVIDER, settings.GEO_MAX_CALLS_PER_MINUTE = "nominatim", 2
    with mock.patch("handy.geo.requests.get", return_value=fake_response(NOMINATIM)) as get:
        for q in ("alpha", "bravo", "charlie"):
            try:
                geo.search(q)
            except geo.GeoUnavailable:
                pass
    assert get.call_count == 2
    settings.GEO_PROVIDER = "none"
    with mock.patch("handy.geo.requests.get") as get:
        assert client(member()).get(f"{GEO}/search/", {"q": "cocody"}).status_code == 503
    assert not get.called


def test_reverse_needs_consent_validates_and_never_caches_exact_coordinates(settings):
    settings.GEO_PROVIDER = "nominatim"
    one = {"address": {"road": "Rue 1", "suburb": "Plateau", "city": "Abidjan", "country": "Côte d'Ivoire"}, "display_name": "Rue 1"}
    c = client(member())
    assert c.get(f"{GEO}/reverse/", {"lat": 5.3, "lng": -4.0}).status_code == 400                     # pas de consentement
    assert c.get(f"{GEO}/reverse/", {"lat": 999, "lng": -4.0, "consent": "true"}).status_code == 400
    with mock.patch("handy.geo.requests.get", return_value=fake_response(one)):
        r1 = c.get(f"{GEO}/reverse/", {"lat": 5.30001, "lng": -4.00001, "consent": "true"}).json()["result"]
        r2 = c.get(f"{GEO}/reverse/", {"lat": 5.30002, "lng": -4.00002, "consent": "true"}).json()["result"]
    assert r1["commune"] == "Plateau" and r1["latitude"] == 5.30001 and r2["latitude"] == 5.30002   # chaque réponse garde SON point
    cached = cache.get(geo._key("reverse", "5.3,-4.0"))
    assert cached and "latitude" not in cached and "longitude" not in cached                         # le cache partagé ne garde aucun point exact


def test_dashboard_exposes_address_completeness_without_technical_username():
    u = User.objects.create_user("tech_username_xyz", None, "pass1234", is_verified=True, phone="+2250701000001")
    c = client(u)
    body = c.get("/handy/me/dashboard/").json()
    assert body["user"]["address_complete"] is False and body["user"]["display_name"] == "Membre Tratra"
    assert "tech_username_xyz" not in str(body["user"])
    c.post(ADDR, GOOD, format="json")
    assert c.get("/handy/me/dashboard/").json()["user"]["address_complete"] is True
