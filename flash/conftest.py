"""Fixtures Tratra Flash : réglages de test communs (médias temporaires, hachage rapide, cache vidé) repris de `handy`, FCM jamais réel."""
from datetime import timedelta

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone

from handy.conftest import (  # noqa: F401  (fixtures partagées)
    _private_kyc_in_tmp, _test_settings, api_client, make_category, make_handyman, make_service, make_user,
)

COCODY = (5.36, -3.99)          # lieu des missions de test (lat, lng)


@pytest.fixture(autouse=True)
def _no_real_push(settings):
    settings.FCM_CREDENTIALS_FILE = ""
    settings.FCM_CREDENTIALS_JSON = ""


@pytest.fixture
def plomberie(make_category):
    return make_category("plomberie-flash", name="Plomberie")


@pytest.fixture
def client_user(make_user):
    return make_user("flash_client", first_name="Awa", phone="+2250700000101")


@pytest.fixture
def make_pro(make_handyman, make_service, plomberie):
    """Professionnel ÉLIGIBLE (KYC, profil, validation), « Disponible », avec une offre de plomberie, à `km` au nord du lieu."""
    counter = {"n": 0}

    def _make(name=None, *, km=1.0, online=True, category=None, service=True, **profile):
        counter["n"] += 1
        name = name or f"pro{counter['n']}"
        lat = COCODY[0] + km / 111.0
        user = make_handyman(name, approved=True, user_extra={"first_name": name.title()},
                             location=Point(COCODY[1], lat, srid=4326), online=online, **profile)
        if service:
            make_service(user, category or plomberie, title=f"Plomberie {name}")
        return user
    return _make


@pytest.fixture
def make_request(client_user, plomberie):
    from flash import services

    def _make(*, mode="firm", amount=15000, minutes=0, client=None, category=None, **extra):
        return services.create_request(client or client_user, category=category or plomberie, address="Rue des Jardins, villa 12",
                                       commune="Cocody", mode=mode, amount=amount if mode == "firm" else None,
                                       scheduled_for=timezone.now() + timedelta(minutes=minutes) if minutes else None,
                                       lat=COCODY[0], lng=COCODY[1], **extra)
    return _make
