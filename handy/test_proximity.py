"""Recherche de proximité servie par l'index spatial : le préfiltre en degrés contient toujours le cercle demandé, les résultats sont
inchangés, et le rayon est plafonné (un rayon démesuré ne fait plus parcourir toutes les offres du pays)."""
import math

import pytest
from django.contrib.gis.geos import Point

from flash.services import haversine_km
from handy import proximity
from handy.api.views import NEARBY_MAX_RADIUS_KM

ABIDJAN = (5.36, -3.99)


def _destination(lat, lng, km, bearing_deg):
    """Point à `km` de (lat, lng) dans la direction donnée, sur la sphère de rayon 6 371 km."""
    d, b = km / 6371.0, math.radians(bearing_deg)
    p1, l1 = math.radians(lat), math.radians(lng)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


@pytest.mark.parametrize("lat", [5.36, 9.45, -33.9, 48.85, 64.0])
@pytest.mark.parametrize("km", [0.5, 15, 50, 100])
def test_the_index_prefilter_always_contains_the_requested_circle(lat, km):
    deg = proximity.radius_degrees(lat, km)
    for bearing in range(0, 360, 10):
        lat2, lng2 = _destination(lat, 10.0, km, bearing)
        assert haversine_km(Point(10.0, lat, srid=4326), Point(lng2, lat2, srid=4326)) == pytest.approx(km, rel=1e-6)
        assert math.hypot(lat2 - lat, lng2 - 10.0) <= deg


@pytest.mark.django_db
def test_nearby_results_are_unchanged_and_the_radius_is_capped(api_client, make_handyman, make_service, make_category):
    category = make_category("plomberie-proximite")
    expected = {}
    for name, km in (("a9", 9.0), ("a11", 11.0), ("a45", 45.0), ("a80", 80.0)):
        pro = make_handyman(name, approved=True, location=Point(ABIDJAN[1], ABIDJAN[0] + km / 111.2, srid=4326))
        expected[name] = make_service(pro, category, title=f"Offre {name}").pk

    def ids(radius):
        r = api_client.get(f"/handy/services/nearby/?lat={ABIDJAN[0]}&lng={ABIDJAN[1]}&radius_km={radius}&page_size=100")
        assert r.status_code == 200
        return {row["id"] for row in r.json()["results"]}

    assert ids(10) == {expected["a9"]}
    assert ids(12) == {expected["a9"], expected["a11"]}
    assert NEARBY_MAX_RADIUS_KM == 50
    assert ids(20000) == {expected["a9"], expected["a11"], expected["a45"]}   # plafonné à 50 km : 80 km reste hors résultats
