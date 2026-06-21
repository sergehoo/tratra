"""Phase 1 — découplage backend : profil Entreprise (B2B) + OpenAPI."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from handy.models import User, CompanyProfile


@pytest.fixture
def api_client(db):
    return APIClient()


@pytest.mark.django_db
def test_inscription_entreprise_cree_profil(api_client):
    r = api_client.post(reverse("users-list"), {
        "username": "acme", "email": "acme@ex.com",
        "password": "pass1234", "user_type": "entreprise",
    }, format="json")
    assert r.status_code == 201, r.content
    u = User.objects.get(username="acme")
    assert u.user_type == "entreprise"
    assert u.is_staff is False
    # profil entreprise auto-créé par signal
    assert CompanyProfile.objects.filter(user=u).exists()


@pytest.mark.django_db
def test_profil_entreprise_upsert(api_client):
    u = User.objects.create_user(username="biz", email="biz@ex.com",
                                 password="pass1234", user_type="entreprise", is_verified=True)
    api_client.force_authenticate(user=u)

    g = api_client.get(reverse("company-profile"))
    assert g.status_code == 200  # profil auto-créé présent

    r = api_client.post(reverse("company-profile"), {
        "company_name": "ACME SARL", "registration_number": "CI-RCCM-123",
        "industry": "BTP", "city": "Abidjan",
    }, format="json")
    assert r.status_code in (200, 201), r.content
    assert r.json()["company_name"] == "ACME SARL"
    assert r.json()["verified"] is False  # vérification réservée à l'admin


@pytest.mark.django_db
def test_openapi_schema_et_docs(api_client):
    s = api_client.get("/api/schema/")
    assert s.status_code == 200
    body = s.content.decode("utf-8", "replace")
    assert "Tratra API" in body and "/handy/" in body

    d = api_client.get("/api/docs/")        # Swagger UI (AllowAny)
    assert d.status_code == 200
