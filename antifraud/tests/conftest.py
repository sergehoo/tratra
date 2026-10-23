import pytest
from django.core.cache import cache

from conftest import ANTIFRAUD_LIMITS
from handy import sms
from tratra.settings import base


@pytest.fixture
def antifraud_on(settings):
    """Valeurs RÉELLES (tratra/settings/base.py) des limites anti-fraude, neutralisées pour les tests métier par le conftest racine ;
    SMS de test en mémoire (aucun envoi réel) ; cache vidé."""
    for name in ANTIFRAUD_LIMITS:
        setattr(settings, name, getattr(base, name))
    settings.UNVERIFIED_RESTRICTIONS = True
    settings.UNVERIFIED_RESTRICTIONS_SINCE = ""
    settings.SMS_BACKEND = "locmem"
    settings.TURNSTILE_SECRET_KEY = ""
    cache.clear()
    sms.outbox.clear()
    yield settings
    cache.clear()
    sms.outbox.clear()
