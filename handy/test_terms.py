"""Conditions d'utilisation : version enregistrée à l'inscription, refus sans consentement, version périmée, comptes existants
préservés (aucune acceptation supposée), acceptation explicite d'une nouvelle version, page publique et concordance site/serveur."""
import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from handy import legal, sms
from trust.models import AuditEvent

User = get_user_model()
pytestmark = pytest.mark.django_db
PASSWORD = "Tr4tra!Essai-2026"


@pytest.fixture(autouse=True)
def _sms(settings):
    settings.SMS_BACKEND = "locmem"
    cache.clear()
    yield
    sms.outbox.clear()


def _signup(phone="0700000310", **extra):
    data = {"first_name": "Ama", "last_name": "Diallo", "phone": phone, "password": PASSWORD, "accept_terms": True,
            "terms_version": legal.TERMS_VERSION}
    data.update(extra)
    return APIClient().post(reverse("users-list"), {k: v for k, v in data.items() if v is not None}, format="json")


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def test_signup_records_the_accepted_version_and_its_date():
    before = timezone.now()
    r = _signup()
    assert r.status_code == 201, r.content
    user = User.objects.get(pk=r.json()["id"])
    assert user.terms_version == legal.TERMS_VERSION and user.terms_accepted_at >= before
    event = AuditEvent.objects.get(action="account.terms_accepted", target_id=user.pk)
    assert event.data == {"version": legal.TERMS_VERSION, "source": "signup"}
    assert "terms_version" not in r.json()                          # écriture seule


@pytest.mark.parametrize("accept", [False, None])
def test_signup_without_explicit_consent_is_refused_and_creates_nothing(accept):
    r = _signup(accept_terms=accept)
    assert r.status_code == 400 and "accept_terms" in r.json()
    assert not User.objects.exists() and not AuditEvent.objects.filter(action="account.terms_accepted").exists()


def test_signup_announcing_an_outdated_version_is_refused():
    r = _signup(terms_version="2020-01-01")
    body = r.json()
    assert r.status_code == 400 and body["code"] == "terms_outdated" and body["current_version"] == legal.TERMS_VERSION
    assert "accept_terms" in body["fields"] and not User.objects.exists()


def test_signup_from_a_client_without_version_records_the_date_but_no_supposed_version():
    """Application antérieure (aucune version annoncée) : l'inscription reste possible avec la case cochée, mais aucune version
    n'est supposée — elle sera proposée explicitement plus tard."""
    r = _signup(terms_version=None)
    assert r.status_code == 201, r.content
    user = User.objects.get(pk=r.json()["id"])
    assert user.terms_accepted_at is not None and user.terms_version == ""
    assert legal.status(user)["needs_acceptance"] is True


def test_existing_account_is_preserved_and_must_accept_a_new_version_explicitly():
    accepted_at = timezone.now() - timezone.timedelta(days=40)
    user = User.objects.create_user(username="ancien", password=PASSWORD, phone="+2250700000311", terms_accepted_at=accepted_at)
    c = _client(user)

    body = c.get(reverse("me-terms")).json()
    assert body["accepted_version"] is None and body["needs_acceptance"] is True and body["current"]["version"] == legal.TERMS_VERSION
    user.refresh_from_db()
    assert user.terms_version == "" and user.terms_accepted_at == accepted_at        # la lecture ne change rien

    for payload, code in (({"version": legal.TERMS_VERSION}, "consent_required"), ({"version": legal.TERMS_VERSION, "accept": "true"}, "consent_required"),
                          ({"version": "2020-01-01", "accept": True}, "terms_outdated"), ({"accept": True}, "terms_outdated")):
        r = c.post(reverse("me-terms"), payload, format="json")
        assert r.status_code == 400 and r.json()["code"] == code
    user.refresh_from_db()
    assert user.terms_version == "" and user.terms_accepted_at == accepted_at

    r = c.post(reverse("me-terms"), {"version": legal.TERMS_VERSION, "accept": True, "source": "app"}, format="json")
    assert r.status_code == 200 and r.json()["up_to_date"] is True and r.json()["needs_acceptance"] is False
    user.refresh_from_db()
    assert user.terms_version == legal.TERMS_VERSION and user.terms_accepted_at > accepted_at
    event = AuditEvent.objects.get(action="account.terms_accepted", target_id=user.pk)
    assert event.data["version"] == legal.TERMS_VERSION and event.data["previous_version"] is None
    assert event.data["previous_accepted_at"] == accepted_at.isoformat() and event.data["source"] == "app"

    first = user.terms_accepted_at                                                   # rejeu : rien ne change, aucun nouvel audit
    assert c.post(reverse("me-terms"), {"version": legal.TERMS_VERSION, "accept": True}, format="json").status_code == 200
    user.refresh_from_db()
    assert user.terms_accepted_at == first and AuditEvent.objects.filter(action="account.terms_accepted").count() == 1


def test_terms_endpoints_access():
    assert APIClient().get(reverse("me-terms")).status_code == 401
    r = APIClient().get(reverse("public-terms"))
    assert r.status_code == 200 and r.json()["version"] == legal.TERMS_VERSION
    assert r.json()["url"].endswith("/conditions-utilisation") and r.json()["updated_on"] == legal.TERMS_UPDATED_ON


def test_profile_update_cannot_set_a_terms_version():
    user = User.objects.create_user(username="maj", password=PASSWORD, phone="+2250700000312")
    r = _client(user).patch(reverse("users-detail", args=[user.pk]), {"first_name": "Awa", "terms_version": legal.TERMS_VERSION}, format="json")
    assert r.status_code == 200
    user.refresh_from_db()
    assert user.first_name == "Awa" and user.terms_version == "" and user.terms_accepted_at is None


def test_public_page_shows_the_same_version_as_the_server():
    source = Path(__file__).resolve().parent.parent / "frontend" / "src" / "lib" / "legal.ts"
    if not source.exists():
        pytest.skip("site absent de cette copie")
    text = source.read_text(encoding="utf-8")
    assert re.search(r'TERMS_VERSION\s*=\s*"([^"]+)"', text).group(1) == legal.TERMS_VERSION
    assert re.search(r'TERMS_UPDATED_ON\s*=\s*"([^"]+)"', text).group(1) == legal.TERMS_UPDATED_ON
    assert re.search(r'TERMS_PATH\s*=\s*"([^"]+)"', text).group(1) == legal.TERMS_PATH
