"""Réglages de test communs à tout le dépôt."""
import pytest


@pytest.fixture(autouse=True)
def _evaluations_published_immediately(settings):
    """Les tests historiques créent des avis et en lisent aussitôt les statistiques : publication immédiate (délai 0).
    Le comportement de production (notes masquées jusqu'à réciprocité ou expiration) est couvert par reputation/test_reputation.py,
    qui rétablit explicitement le délai."""
    settings.EVALUATION_REVEAL_DAYS = 0
