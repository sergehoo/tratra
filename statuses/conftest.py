import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _tmp_media(settings, tmp_path):
    """Médias de test dans un dossier temporaire (jamais dans `media/` du dépôt) ; cache vidé entre les tests."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    cache.clear()
    yield
    cache.clear()
