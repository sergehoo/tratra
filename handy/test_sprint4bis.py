"""Tests Sprint 4-bis — KYC artisans.

- Téléversement de documents par l'artisan (sur SON profil)
- Revue admin : approbation / rejet -> statut + KYC requis satisfait
- Revue réservée au staff
- Mise en ligne (présence) bloquée tant que le profil n'est pas vérifié
"""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from handy.models import User, HandymanProfile, HandymanDocument

# Stockage en mémoire pour les tests (évite MinIO/S3 non disponible en local)
INMEM_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@pytest.fixture
def api_client(db):
    return APIClient()


def _user(username, utype="client"):
    return User.objects.create_user(
        username=username, email=f"{username}@ex.com",
        password="pass1234", user_type=utype, is_verified=True,
    )


def _admin(username):
    u = _user(username, "admin")
    u.is_staff = True
    u.save(update_fields=["is_staff"])
    return u


def _doc(profile, dtype="id_card"):
    return HandymanDocument.objects.create(
        handyman=profile, document_type=dtype,
        file=SimpleUploadedFile(f"{dtype}.pdf", b"%PDF-1.4 fake"),
    )


@pytest.mark.django_db
@override_settings(STORAGES=INMEM_STORAGES)
def test_artisan_televerse_sur_son_profil(api_client):
    h = _user("h_k1", "handyman")  # profil auto-créé par signal
    api_client.force_authenticate(user=h)
    f = SimpleUploadedFile("id.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
    r = api_client.post(
        reverse("handyman-docs-list"),
        {"document_type": "id_card", "file": f, "description": "CNI"},
        format="multipart",
    )
    assert r.status_code == 201, r.content
    assert r.json()["status"] == "pending"
    prof = HandymanProfile.objects.get(user=h)
    assert HandymanDocument.objects.filter(handyman=prof).count() == 1


@pytest.mark.django_db
@override_settings(STORAGES=INMEM_STORAGES)
def test_admin_approuve_document_valide_kyc(api_client):
    h, admin = _user("h_k2", "handyman"), _admin("adm_k2")
    prof = HandymanProfile.objects.get(user=h)
    doc = _doc(prof)
    assert prof.has_required_kyc() is False

    api_client.force_authenticate(user=admin)
    r = api_client.post(reverse("handyman-docs-review", kwargs={"pk": doc.id}),
                        {"action": "approve"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert prof.has_required_kyc() is True


@pytest.mark.django_db
@override_settings(STORAGES=INMEM_STORAGES)
def test_admin_rejette_document(api_client):
    h, admin = _user("h_k3", "handyman"), _admin("adm_k3")
    prof = HandymanProfile.objects.get(user=h)
    doc = _doc(prof)

    api_client.force_authenticate(user=admin)
    r = api_client.post(reverse("handyman-docs-review", kwargs={"pk": doc.id}),
                        {"action": "reject", "reason": "document illisible"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    doc.refresh_from_db()
    assert doc.rejection_reason == "document illisible"
    assert prof.has_required_kyc() is False


@pytest.mark.django_db
@override_settings(STORAGES=INMEM_STORAGES)
def test_revue_reservee_admin(api_client):
    h = _user("h_k4", "handyman")
    prof = HandymanProfile.objects.get(user=h)
    doc = _doc(prof)
    api_client.force_authenticate(user=h)  # non-admin (le propriétaire)
    r = api_client.post(reverse("handyman-docs-review", kwargs={"pk": doc.id}),
                        {"action": "approve"}, format="json")
    assert r.status_code == 403


@pytest.mark.django_db
def test_presence_bloquee_si_non_verifie(api_client):
    h = _user("h_k5", "handyman")
    prof = HandymanProfile.objects.get(user=h)  # is_approved=False par défaut
    api_client.force_authenticate(user=h)

    r = api_client.post(reverse("handymen-presence"), {"online": True}, format="json")
    assert r.status_code == 403  # non vérifié -> interdit

    prof.is_approved = True
    prof.save(update_fields=["is_approved"])
    r2 = api_client.post(reverse("handymen-presence"), {"online": True}, format="json")
    assert r2.status_code == 200 and r2.json()["online"] is True
