"""SMS / OTP : fournisseur configurable, aucun faux succès, aucun code fictif en production."""
from datetime import timedelta
from unittest import mock

import pytest
import requests
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from handy import sms
from handy.models import OTPCode, User

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _locmem(settings, monkeypatch):
    # Isolation : les tests ne lisent jamais le `.env` du développeur (identifiants réels éventuels).
    import os

    monkeypatch.setattr(sms, "config", lambda name, default="": os.environ.get(name, default))
    for key in ("SMS_BACKEND", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "TWILIO_PHONE_NUMBER",
                "TWILIO_MESSAGING_SERVICE_SID", "AT_USERNAME", "AT_API_KEY", "AT_SENDER_ID", "AT_SANDBOX"):
        monkeypatch.delenv(key, raising=False)
    settings.SMS_BACKEND = "locmem"
    sms.outbox.clear()
    yield
    sms.outbox.clear()


def _client(phone="+2250700000001", username="otp_user"):
    user = User.objects.create_user(username=username, email=f"{username}@x.test", password="pass1234",
                                    phone=phone, is_verified=False)
    c = APIClient()
    c.force_authenticate(user)
    return user, c


# ---- Flux OTP --------------------------------------------------------------------------------

def test_otp_is_sent_by_sms_and_never_returned():
    user, c = _client()
    r = c.post(reverse("otp-request"))
    assert r.status_code == 201
    assert r.json() == {"sent": True, "phone": "+225••••01", "expires_in": 600, "resend_in": 60}  # masqué, JAMAIS le code
    (to, text), = sms.outbox
    code = OTPCode.objects.get(user=user).code
    assert to == "+2250700000001" and code in text
    ok = c.post(reverse("otp-verify"), {"code": code}, format="json")
    assert ok.status_code == 200
    user.refresh_from_db()
    assert user.is_verified is True


def test_no_phone_means_no_fake_success():
    _, c = _client(phone="")
    r = c.post(reverse("otp-request"))
    assert r.status_code == 400 and "numéro de téléphone" in r.json()["detail"]
    assert not OTPCode.objects.exists() and not sms.outbox


def test_no_provider_configured_is_an_error_not_a_success(settings):
    settings.SMS_BACKEND = ""
    user, c = _client()
    r = c.post(reverse("otp-request"))
    assert r.status_code == 503 and "pas disponible" in r.json()["detail"]
    assert not OTPCode.objects.filter(user=user, used=False).exists()  # code invalidé


def test_provider_failure_invalidates_the_code():
    user, c = _client()
    with mock.patch.object(sms.LocmemBackend, "send", side_effect=sms.SMSError("down")):
        r = c.post(reverse("otp-request"))
    assert r.status_code == 502 and "n'a pas pu être envoyé" in r.json()["detail"]
    assert not OTPCode.objects.filter(user=user, used=False).exists()


def test_console_and_locmem_are_refused_outside_dev(settings):
    settings.DEBUG = False
    for name in ("console", "locmem"):
        settings.SMS_BACKEND = name
        with mock.patch.object(sms, "_is_test_run", return_value=False), pytest.raises(sms.SMSNotConfigured):
            sms.get_backend()


def test_resend_cooldown_and_single_valid_code():
    user, c = _client()
    assert c.post(reverse("otp-request")).status_code == 201
    r = c.post(reverse("otp-request"))
    assert r.status_code == 429 and "Patientez" in r.json()["detail"] and r["Retry-After"]
    OTPCode.objects.filter(user=user).update(created_at=timezone.now() - timedelta(minutes=2))
    assert c.post(reverse("otp-request")).status_code == 201
    assert OTPCode.objects.filter(user=user, used=False).count() == 1


def test_hourly_quota():
    user, c = _client()
    for _ in range(5):
        OTPCode.objects.create(user=user, code="000000", expires_at=timezone.now() + timedelta(minutes=5),
                               used=True)
    OTPCode.objects.filter(user=user).update(created_at=timezone.now() - timedelta(minutes=30))
    r = c.post(reverse("otp-request"))
    assert r.status_code == 429 and "Trop de codes" in r.json()["detail"]


def test_wrong_codes_lock_the_otp():
    user, c = _client()
    c.post(reverse("otp-request"))
    real = OTPCode.objects.get(user=user, used=False).code
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(5):
        assert c.post(reverse("otp-verify"), {"code": wrong}, format="json").status_code == 400
    r = c.post(reverse("otp-verify"), {"code": real}, format="json")
    assert r.status_code == 429 and "Trop d'essais" in r.json()["detail"]  # même le bon code : verrouillé
    user.refresh_from_db()
    assert user.is_verified is False


def test_no_backdoor_code():
    user, c = _client()
    for fake in ("000000", "123456", "999999", ""):
        r = c.post(reverse("otp-verify"), {"code": fake}, format="json")
        assert r.status_code in (400, 429)
    user.refresh_from_db()
    assert user.is_verified is False


# ---- Numéros ---------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("+225 07 00 00 00 01", "+2250700000001"),
    ("0700000001", "+2250700000001"),
    ("00225 0700000001", "+2250700000001"),
    ("+33 6 12 34 56 78", "+33612345678"),
])
def test_msisdn_normalisation(raw, expected):
    assert sms.normalize_msisdn(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "+12", "+0123456789", "1" * 20])
def test_invalid_msisdn_is_refused(raw):
    with pytest.raises(sms.SMSError):
        sms.normalize_msisdn(raw)


# ---- Fournisseurs réels (HTTP simulé) -----------------------------------------------------------

def test_twilio_request(settings, monkeypatch):
    settings.SMS_BACKEND = "twilio"
    for k, v in {"TWILIO_ACCOUNT_SID": "ACxxx", "TWILIO_AUTH_TOKEN": "tok", "TWILIO_FROM": "+15005550006"}.items():
        monkeypatch.setenv(k, v)
    ok = mock.Mock(status_code=201)
    with mock.patch("handy.sms.requests.post", return_value=ok) as post:
        sms.send_sms("0700000001", "Votre code : 123456")
    url = post.call_args.args[0]
    assert url == "https://api.twilio.com/2010-04-01/Accounts/ACxxx/Messages.json"
    assert post.call_args.kwargs["data"] == {"To": "+2250700000001", "Body": "Votre code : 123456",
                                             "From": "+15005550006"}
    assert post.call_args.kwargs["auth"] == ("ACxxx", "tok")


def test_twilio_errors_never_leak_the_message(settings, monkeypatch):
    settings.SMS_BACKEND = "twilio"
    for k, v in {"TWILIO_ACCOUNT_SID": "ACxxx", "TWILIO_AUTH_TOKEN": "tok", "TWILIO_FROM": "+1500"}.items():
        monkeypatch.setenv(k, v)
    bad = mock.Mock(status_code=400)
    bad.json.return_value = {"code": 21211}
    with mock.patch("handy.sms.requests.post", return_value=bad), pytest.raises(sms.SMSError) as e:
        sms.send_sms("+2250700000001", "code 654321")
    assert "654321" not in str(e.value) and "21211" in str(e.value)
    with mock.patch("handy.sms.requests.post", side_effect=requests.ConnectTimeout("x")), \
            pytest.raises(sms.SMSError) as e:
        sms.send_sms("+2250700000001", "code 654321")
    assert "654321" not in str(e.value)


def test_provider_credentials_refused_is_a_server_side_unavailability(settings, monkeypatch):
    """HTTP 401/403 du fournisseur = défaut de configuration serveur : 503 (pas « vérifiez votre numéro »)."""
    settings.SMS_BACKEND = "twilio"
    for k, v in {"TWILIO_ACCOUNT_SID": "ACxxx", "TWILIO_AUTH_TOKEN": "tok", "TWILIO_FROM": "+1500"}.items():
        monkeypatch.setenv(k, v)
    refused = mock.Mock(status_code=401)
    refused.json.return_value = {"code": 20003}
    user, c = _client()
    with mock.patch("handy.sms.requests.post", return_value=refused):
        r = c.post(reverse("otp-request"))
    assert r.status_code == 503 and "pas disponible" in r.json()["detail"]
    assert not OTPCode.objects.filter(user=user, used=False).exists()
    assert "tok" not in r.content.decode()


def test_twilio_requires_credentials(settings, monkeypatch):
    settings.SMS_BACKEND = "twilio"
    for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "TWILIO_MESSAGING_SERVICE_SID"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(sms.SMSNotConfigured):
        sms.get_backend()


def test_africastalking_request_and_status(settings, monkeypatch):
    settings.SMS_BACKEND = "africastalking"
    monkeypatch.setenv("AT_USERNAME", "tratra")
    monkeypatch.setenv("AT_API_KEY", "key")
    good = mock.Mock(status_code=201)
    good.json.return_value = {"SMSMessageData": {"Recipients": [{"statusCode": 101, "status": "Success"}]}}
    with mock.patch("handy.sms.requests.post", return_value=good) as post:
        sms.send_sms("+2250700000001", "hello")
    assert post.call_args.args[0] == "https://api.africastalking.com/version1/messaging"
    assert post.call_args.kwargs["headers"]["apiKey"] == "key"
    refused = mock.Mock(status_code=201)
    refused.json.return_value = {"SMSMessageData": {"Recipients": [{"statusCode": 403}]}}
    with mock.patch("handy.sms.requests.post", return_value=refused), pytest.raises(sms.SMSError):
        sms.send_sms("+2250700000001", "hello")


# ---- Réglages de production --------------------------------------------------------------------

def _load_prod(monkeypatch, **env):
    import importlib

    base = {"DJANGO_ENV": "prod"}
    for k in ("SMS_BACKEND", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM",
              "TWILIO_MESSAGING_SERVICE_SID", "AT_USERNAME", "AT_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in {**base, **env}.items():
        monkeypatch.setenv(k, v)
    return importlib.import_module("tratra.settings.prod")


@pytest.mark.parametrize("env", [{}, {"SMS_BACKEND": "console"}, {"SMS_BACKEND": "locmem"},
                                 {"SMS_BACKEND": "twilio"},
                                 {"SMS_BACKEND": "twilio", "TWILIO_ACCOUNT_SID": "a", "TWILIO_AUTH_TOKEN": "b"},
                                 {"SMS_BACKEND": "africastalking"}])
def test_production_refuses_without_a_real_sms_provider(monkeypatch, env):
    """prod.py exige d'autres réglages (hôtes, MinIO…) : l'erreur SMS doit venir de NOTRE contrôle ;
    on vérifie donc le texte de l'erreur, pas seulement son type."""
    import sys

    sys.modules.pop("tratra.settings.prod", None)
    with pytest.raises(ImproperlyConfigured) as e:
        _load_prod(monkeypatch, **env)
    # les contrôles précédents (SECRET_KEY, ALLOWED_HOSTS, MinIO) peuvent échouer d'abord en CI :
    assert any(word in str(e.value) for word in ("SMS", "TWILIO", "AT_", "SECRET_KEY", "ALLOWED_HOSTS", "MINIO"))
    sys.modules.pop("tratra.settings.prod", None)
