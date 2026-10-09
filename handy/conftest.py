"""Fixtures et réglages de test partagés de l'application `handy` (§9.1, créé en L1a).

Chaque lot l'enrichit (SMS locmem et OTP en L3a, KYC en L5a…). Les modules de
test existants qui déclarent leur propre `api_client` gardent le leur (une
fixture de module masque celle du conftest).
"""
import io
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

# Mot de passe conforme aux AUTH_PASSWORD_VALIDATORS (désormais appliqués par l'API).
STRONG_PASSWORD = "Tr4tra!Essai-2026"
TEST_MEDIA_HOST = "media.tratra.test"


@pytest.fixture(autouse=True)
def _test_settings(settings, tmp_path):
    """Réglages communs : médias écrits dans un dossier temporaire (jamais dans
    `media/` du dépôt), hôte d'images publiques de test, cache vidé (throttles),
    hachage de mot de passe rapide (les validateurs restent ceux de la prod)."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    settings.MEDIA_PUBLIC_HOSTS = [TEST_MEDIA_HOST]
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client(db):
    return APIClient()


@pytest.fixture
def make_user(db):
    """`make_user("awa", first_name="Awa", last_name="Koné", **champs_user)`."""
    from handy.models import User

    def _make(username, user_type="client", password=STRONG_PASSWORD, **extra):
        extra.setdefault("email", f"{username}@example.test")
        return User.objects.create_user(username=username, password=password,
                                        user_type=user_type, **extra)
    return _make


@pytest.fixture
def make_handyman(make_user):
    """Artisan legacy : profil créé par le signal `user_type='handyman'`.

    `approved` écrit directement `is_approved` (donnée de test, aucune API ne le
    permet) ; remplacé par `kyc_status=` via KycService en L5a.
    """
    def _make(username, *, approved=False, active=True, user_extra=None, **profile_fields):
        user = make_user(username, "handyman", is_active=active, **(user_extra or {}))
        profile = user.handyman_profile
        profile.is_approved = approved
        for name, value in profile_fields.items():
            setattr(profile, name, value)
        profile.save()
        if approved:
            from handy.testing import make_eligible

            make_eligible(profile)  # KYC approuvé + profil complet (règle d'éligibilité)
        return user
    return _make


@pytest.fixture
def make_category(db):
    from handy.models import ServiceCategory

    def _make(slug="plomberie-test", name=None, **extra):
        return ServiceCategory.objects.create(slug=slug, name=name or slug.replace("-", " ").title(), **extra)
    return _make


@pytest.fixture
def make_service(db):
    from handy.models import Service

    def _make(handyman, category, title="Réparation", price="5000", active=True, **extra):
        price_type = extra.pop("price_type", "quote" if price is None else "fixed")
        return Service.objects.create(
            handyman=handyman, category=category, title=title, description="Description",
            price_type=price_type, price=Decimal(price) if price is not None else None,
            is_active=active, **extra)
    return _make


def _image_bytes(fmt, width, height, mode, color, exif=None):
    img = Image.new(mode, (width, height), color)
    buffer = io.BytesIO()
    kwargs = {"exif": exif} if exif is not None else {}
    img.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def gps_exif(orientation=None):
    """EXIF contenant une position GPS (Abidjan) et un modèle d'appareil."""
    exif = Image.Exif()
    exif[0x010F] = "SpyCam"  # Make
    if orientation is not None:
        exif[0x0112] = orientation
    exif[0x8825] = {1: "N", 2: (5.0, 21.0, 0.0), 3: "W", 4: (4.0, 1.0, 0.0)}  # GPSInfo
    return exif


@pytest.fixture
def jpeg_bytes():
    def _make(width=64, height=48, exif=None):
        return _image_bytes("JPEG", width, height, "RGB", (200, 30, 30), exif)
    return _make


@pytest.fixture
def png_bytes():
    def _make(width=64, height=48, alpha=False):
        mode, color = ("RGBA", (0, 128, 0, 100)) if alpha else ("RGB", (0, 128, 0))
        return _image_bytes("PNG", width, height, mode, color)
    return _make


@pytest.fixture
def pdf_bytes():
    def _make():
        return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    return _make


@pytest.fixture
def upload():
    """`upload("photo.jpg", data, "image/jpeg")` -> fichier multipart."""
    def _make(name, data, content_type="image/jpeg"):
        return SimpleUploadedFile(name, data, content_type=content_type)
    return _make
