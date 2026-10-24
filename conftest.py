"""Réglages de test communs à tout le dépôt."""
import pytest


@pytest.fixture(autouse=True)
def _evaluations_published_immediately(settings):
    """Les tests historiques créent des avis et en lisent aussitôt les statistiques : publication immédiate (délai 0).
    Le comportement de production (notes masquées jusqu'à réciprocité ou expiration) est couvert par reputation/test_reputation.py,
    qui rétablit explicitement le délai."""
    settings.EVALUATION_REVEAL_DAYS = 0


ANTIFRAUD_LIMITS = (
    "SMS_GLOBAL_HOURLY_LIMIT", "SMS_GLOBAL_DAILY_LIMIT", "SMS_PER_NUMBER_HOURLY_LIMIT", "SMS_PER_NUMBER_DAILY_LIMIT",
    "SMS_PER_IP_HOURLY_LIMIT", "SMS_PER_IP_DAILY_LIMIT", "SMS_PER_USER_DAILY_LIMIT", "SIGNUP_PER_IP_HOURLY_LIMIT",
    "SIGNUP_PER_IP_DAILY_LIMIT", "SIGNUP_PER_DEVICE_DAILY_LIMIT", "SIGNUP_GLOBAL_HOURLY_LIMIT", "SIGNUP_SAME_NAME_DAILY_LIMIT",
    "SIGNUP_PHONE_BLOCK_HOURLY_LIMIT", "SIGNUP_PHONE_RANGE_DAILY_LIMIT", "PHONE_CHANGES_DAILY_LIMIT",
)


@pytest.fixture(autouse=True)
def _antifraud_off_for_business_tests(settings):
    """Les tests métier créent de nombreux comptes non vérifiés depuis la même adresse (127.0.0.1) et envoient des SMS de test : les
    quotas anti-fraude (comptés dans le cache, partagé entre tests) et la restriction des comptes non vérifiés y sont neutralisés.
    Le comportement de production est couvert par antifraud/tests/ (fixture `antifraud_on`), qui rétablit les valeurs réelles.
    Restent actifs ici : interrupteurs et destinations autorisées. Turnstile neutralisé (indépendant du .env du poste)."""
    for name in ANTIFRAUD_LIMITS:
        setattr(settings, name, 0)
    settings.UNVERIFIED_RESTRICTIONS = False
    settings.TURNSTILE_SECRET_KEY = ""

