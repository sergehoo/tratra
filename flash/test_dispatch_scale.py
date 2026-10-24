"""Smart Dispatch à grande échelle : la zone est préfiltrée par l'index spatial sans rien changer aux règles (position, centre de la zone
d'intervention, à défaut même commune), et le coût d'une vague ou d'une liste « choisir son pro » ne dépend plus du nombre de
professionnels de la zone (lectures groupées au lieu d'une dizaine de requêtes par professionnel)."""
from datetime import timedelta

import pytest
from django.contrib.gis.geos import Point
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from flash import hybrid, services
from flash.conftest import COCODY
from flash.models import DispatchConfig, MissionRequest
from handy.models import AvailabilitySlot, HandymanProfile, ServiceArea, TimeOff

pytestmark = pytest.mark.django_db


def _draft(client, category, *, located=True, commune="Cocody", hours=2):
    return MissionRequest(client=client, category=category, commune=commune, scheduled_for=timezone.now() + timedelta(hours=hours),
                          is_immediate=False, location=Point(COCODY[1], COCODY[0], srid=4326) if located else None)


def _queries(fn):
    fn()   # premier appel : réglages créés et références spatiales mises en cache une fois pour toutes (hors mesure)
    with CaptureQueriesContext(connection) as ctx:
        result = fn()
    return result, len(ctx)


def test_a_wave_costs_the_same_number_of_queries_whatever_the_number_of_pros(make_pro, client_user, plomberie):
    config = DispatchConfig.get_solo()
    req = _draft(client_user, plomberie)
    for _ in range(3):
        make_pro()
    (ranked, _), few = _queries(lambda: services.candidates(req, config, explain=True))
    assert len(ranked) == 3
    weekday = timezone.localtime(req.scheduled_for).weekday()
    for i in range(9):
        pro = make_pro()
        if i % 3 == 0:   # données réelles à lire : horaires couvrant le créneau, absence passée
            AvailabilitySlot.objects.create(handyman=pro.handyman_profile, weekday=weekday, start_time="00:00", end_time="23:59:59")
            TimeOff.objects.create(handyman=pro.handyman_profile, start=timezone.now() - timedelta(days=3),
                                   end=timezone.now() - timedelta(days=2))
    (ranked, _), many = _queries(lambda: services.candidates(req, config, explain=True))
    assert len(ranked) == 12
    assert many == few, "le coût d'une vague ne doit pas croître avec le nombre de professionnels"


def test_choosing_a_pro_costs_the_same_number_of_queries_whatever_the_number_of_pros(make_pro, client_user, plomberie):
    for _ in range(2):
        make_pro()
    rows, few = _queries(lambda: hybrid.direct_pros(client_user, plomberie, lat=COCODY[0], lng=COCODY[1], commune="Cocody"))
    assert len(rows) == 2
    for _ in range(8):
        make_pro()
    rows, many = _queries(lambda: hybrid.direct_pros(client_user, plomberie, lat=COCODY[0], lng=COCODY[1], commune="Cocody"))
    assert len(rows) == 10 and all(r["offers"] for r in rows)
    assert many == few


def test_zone_rules_are_unchanged_position_then_service_area_then_commune(make_pro, client_user, plomberie):
    config = DispatchConfig.get_solo()
    near, far = make_pro("pres", km=2), make_pro("loin", km=40)
    area_near, area_far = make_pro("zonepres"), make_pro("zoneloin")
    same_commune, other_commune = make_pro("commune"), make_pro("ailleurs")
    HandymanProfile.objects.filter(user__in=[area_near, area_far, same_commune, other_commune]).update(location=None)
    ServiceArea.objects.create(handyman=area_near.handyman_profile, center=Point(COCODY[1], COCODY[0] + 5 / 111, srid=4326), radius_km=10)
    ServiceArea.objects.create(handyman=area_far.handyman_profile, center=Point(COCODY[1], COCODY[0] + 60 / 111, srid=4326), radius_km=10)
    HandymanProfile.objects.filter(user=same_commune).update(commune="  cocody ")
    HandymanProfile.objects.filter(user=other_commune).update(commune="Yopougon", quartier="Niangon")

    ranked, rejected = services.candidates(_draft(client_user, plomberie), config, explain=True)
    reasons = {r["user_id"]: r["reason"] for r in rejected}
    assert {c.profile.user_id for c in ranked} == {near.pk, area_near.pk, same_commune.pk}
    assert reasons == {far.pk: "Hors zone", area_far.pk: "Hors zone", other_commune.pk: "Hors zone"}

    # Demande sans position : seule la commune compte (position du professionnel ignorée), exactement comme avant.
    ranked, rejected = services.candidates(_draft(client_user, plomberie, located=False), config, explain=True)
    assert {c.profile.user_id for c in ranked} == {p.pk for p in (near, far, area_near, area_far, same_commune)}
    assert {r["user_id"]: r["reason"] for r in rejected} == {other_commune.pk: "Hors zone"}


def test_scores_read_in_bulk_are_identical_to_scores_read_one_by_one(make_pro, client_user, plomberie, make_user):
    from handy.models import Booking, Review

    config = DispatchConfig.get_solo()
    pro = make_pro("note")
    for i in range(4):
        client = make_user(f"noteur{i}", phone=f"+22507000003{i:02d}")
        booking = Booking.objects.create(client=client, handyman=pro, status="completed", address="x", city="Abidjan",
                                         booking_date=timezone.now() - timedelta(days=i + 1))
        Review.objects.create(booking=booking, rating=3 + i % 3, revealed_at=timezone.now())
    make_pro("sans_historique")
    req = _draft(client_user, plomberie)
    ranked = services.candidates(req, config)
    assert ranked
    for cand in ranked:
        alone = services.score(cand.profile, cand.distance_km, config, timezone.now())
        assert alone["score"] == cand.detail["score"]
        assert [c["detail"] for c in alone["criteria"]] == [c["detail"] for c in cand.detail["criteria"]]
