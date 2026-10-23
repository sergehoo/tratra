"""SMS / OTP : fournisseur configurable, aucun faux succès, aucun code fictif en production."""
import json
import logging
from datetime import timedelta
from unittest import mock

import pytest
import requests
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from handy import sms
from antifraud.models import SmsLog
from handy.models import OTPCode, User

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _locmem(settings, monkeypatch):
    # Isolation : les tests ne lisent jamais le `.env` du développeur (identifiants réels éventuels).
    import os

    monkeypatch.setattr(sms, "config", lambda name, default="": os.environ.get(name, default))
    for key in ("SMS_BACKEND", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "TWILIO_PHONE_NUMBER",
                "TWILIO_MESSAGING_SERVICE_SID", "AT_USERNAME", "AT_API_KEY", "AT_SENDER_ID", "AT_SANDBOX",
                "ORANGE_SMS_CLIENT_ID", "ORANGE_SMS_CLIENT_SECRET", "ORANGE_SMS_AUTHORIZATION_HEADER", "ORANGE_SMS_SENDER",
                "ORANGE_SMS_SENDER_NAME", "ORANGE_SMS_RESOURCE_TYPE", "SMS_FAILOVER_COOLDOWN"):
        monkeypatch.delenv(key, raising=False)
    settings.SMS_BACKEND = "locmem"
    sms.cache.clear()
    sms.outbox.clear()
    yield
    sms.cache.clear()
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
    SmsLog.objects.filter(user=user).update(created_at=timezone.now() - timedelta(minutes=2))   # envoi d'il y a 2 min
    assert c.post(reverse("otp-request")).status_code == 201
    assert OTPCode.objects.filter(user=user, used=False).count() == 1


def test_hourly_quota():
    user, c = _client()
    for _ in range(5):   # 5 SMS envoyés dans l'heure (journal des envois : source du délai et du quota)
        SmsLog.objects.create(user=user, purpose="otp_signup", status="sent")
    SmsLog.objects.filter(user=user).update(created_at=timezone.now() - timedelta(minutes=30))
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


# ---- Orange (HTTP simulé) -----------------------------------------------------------------------------------------

def _orange_env(monkeypatch, **extra):
    for k, v in {"ORANGE_SMS_CLIENT_ID": "cid", "ORANGE_SMS_CLIENT_SECRET": "csecret", **extra}.items():
        monkeypatch.setenv(k, v)


def _resp(status, payload=None):
    r = mock.Mock(status_code=status)
    r.json.return_value = payload if payload is not None else {}
    # `.text` / `.content` réalistes : une fuite du corps de la réponse dans une erreur ou un journal doit être VISIBLE des tests.
    r.text = json.dumps(payload) if payload is not None else ""
    r.content = r.text.encode()
    return r


def _net_error():
    """Erreur réseau réaliste : le texte d'un vrai ConnectionError de `requests` contient l'URL, donc l'identifiant de compte Twilio."""
    return requests.ConnectionError("HTTPSConnectionPool(host='api.twilio.com', port=443): Max retries exceeded with url: "
                                    "/2010-04-01/Accounts/ACxxx/Messages.json (Caused by NewConnectionError('Failed to establish'))")


_TOKEN_OK = {"token_type": "Bearer", "access_token": "tok-orange-1", "expires_in": "3600"}


def _orange_http(token=None, send=None):
    """Simule api.orange.com : renvoie la réponse du jeton pour /oauth/, celle de l'envoi pour /smsmessaging/."""
    sends = send if isinstance(send, list) else [send or _resp(201)]
    tokens = token if isinstance(token, list) else [token or _resp(200, _TOKEN_OK)]
    calls = {"oauth": [], "sms": []}

    def fake_post(url, **kwargs):
        if "/oauth/" in url:
            calls["oauth"].append((url, kwargs))
            return tokens.pop(0) if len(tokens) > 1 else tokens[0]
        calls["sms"].append((url, kwargs))
        return sends.pop(0) if len(sends) > 1 else sends[0]

    return mock.patch("handy.sms.requests.post", side_effect=fake_post), calls


def test_orange_gets_a_token_then_sends_with_the_documented_request(settings, monkeypatch):
    settings.SMS_BACKEND = "orange"
    _orange_env(monkeypatch)
    patch, calls = _orange_http()
    with patch:
        backend = sms.send_sms("0700000001", "Votre code : 123456")
    assert isinstance(backend, sms.OrangeBackend)
    (token_url, token_kwargs), = calls["oauth"]
    assert token_url == "https://api.orange.com/oauth/v3/token"
    assert token_kwargs["data"] == {"grant_type": "client_credentials"}
    import base64
    assert token_kwargs["headers"]["Authorization"] == "Basic " + base64.b64encode(b"cid:csecret").decode()
    (url, kwargs), = calls["sms"]
    assert url == "https://api.orange.com/smsmessaging/v1/outbound/tel%3A%2B2250000/requests"
    assert kwargs["headers"]["Authorization"] == "Bearer tok-orange-1"
    assert kwargs["json"] == {"outboundSMSMessageRequest": {
        "address": "tel:+2250700000001", "senderAddress": "tel:+2250000",
        "outboundSMSTextMessage": {"message": "Votre code : 123456"}}}
    assert kwargs["params"] is None


def test_orange_optional_sender_name_resource_type_and_a_ready_made_authorization_header(settings, monkeypatch):
    settings.SMS_BACKEND = "orange"
    monkeypatch.setenv("ORANGE_SMS_AUTHORIZATION_HEADER", "abc123==")  # sans « Basic » : complété
    monkeypatch.setenv("ORANGE_SMS_SENDER", "+225 0000")
    monkeypatch.setenv("ORANGE_SMS_SENDER_NAME", "Tratra")
    monkeypatch.setenv("ORANGE_SMS_RESOURCE_TYPE", "SMS_OCB2")
    patch, calls = _orange_http()
    with patch:
        sms.send_sms("+2250700000001", "x")
    assert calls["oauth"][0][1]["headers"]["Authorization"] == "Basic abc123=="
    url, kwargs = calls["sms"][0]
    assert url.endswith("/outbound/tel%3A%2B2250000/requests")
    assert kwargs["params"] == {"resource_type_parameter_management": "SMS_OCB2"}
    assert kwargs["json"]["outboundSMSMessageRequest"]["senderName"] == "Tratra"


def test_orange_token_is_cached_between_sends_and_per_credentials(settings, monkeypatch):
    settings.SMS_BACKEND = "orange"
    _orange_env(monkeypatch)
    patch, calls = _orange_http()
    with patch:
        sms.send_sms("+2250700000001", "a")
        sms.send_sms("+2250700000002", "b")
    assert len(calls["oauth"]) == 1 and len(calls["sms"]) == 2
    monkeypatch.setenv("ORANGE_SMS_CLIENT_SECRET", "autre-secret")  # secret renouvelé : l'ancien jeton n'est jamais réutilisé
    patch, calls = _orange_http()
    with patch:
        sms.send_sms("+2250700000001", "c")
    assert len(calls["oauth"]) == 1


def test_orange_renews_an_expired_token_once_and_retries(settings, monkeypatch):
    settings.SMS_BACKEND = "orange"
    _orange_env(monkeypatch)
    patch, calls = _orange_http(token=[_resp(200, {**_TOKEN_OK, "access_token": "old"}),
                                       _resp(200, {**_TOKEN_OK, "access_token": "fresh"})],
                                send=[_resp(401, {"code": 42, "message": "Expired credentials"}), _resp(201)])
    with patch:
        sms.send_sms("+2250700000001", "x")
    assert [c[1]["headers"]["Authorization"] for c in calls["sms"]] == ["Bearer old", "Bearer fresh"]
    patch, calls = _orange_http(send=_resp(401, {"code": 42}))  # toujours 401 : un seul renouvellement, puis refus
    with patch, pytest.raises(sms.SMSNotConfigured):
        sms.send_sms("+2250700000001", "x")
    assert len(calls["sms"]) == 2


@pytest.mark.parametrize("status,expected", [
    (400, sms.SMSError), (403, sms.SMSNotConfigured), (429, sms.SMSProviderUnavailable),
    (500, sms.SMSProviderUnavailable), (503, sms.SMSProviderUnavailable)])
def test_orange_classifies_provider_errors(settings, monkeypatch, status, expected):
    settings.SMS_BACKEND = "orange"
    _orange_env(monkeypatch)
    patch, _ = _orange_http(send=_resp(status, {"requestError": {"serviceException": {"messageId": "SVC0002", "text": "+2250700000001 654321"}}}))
    with patch, pytest.raises(sms.SMSError) as e:
        sms.send_sms("+2250700000001", "code 654321")
    assert type(e.value) is expected
    text = str(e.value)
    for secret in ("654321", "+2250700000001", "2250700000001", "0700000001", "csecret", "Y2lkOmNzZWNyZXQ=", "tok-orange"):
        assert secret not in text
    if status == 400:
        assert "SVC0002" in text  # le code d'erreur Orange, jamais son texte


def test_orange_token_endpoint_failures(settings, monkeypatch):
    settings.SMS_BACKEND = "orange"
    _orange_env(monkeypatch)
    for status, expected in ((401, sms.SMSNotConfigured), (400, sms.SMSNotConfigured), (503, sms.SMSProviderUnavailable)):
        sms.cache.clear()
        patch, _ = _orange_http(token=_resp(status))
        with patch, pytest.raises(expected):
            sms.send_sms("+2250700000001", "x")
    sms.cache.clear()
    patch, _ = _orange_http(token=_resp(200, {"unexpected": True}))
    with patch, pytest.raises(sms.SMSProviderUnavailable):
        sms.send_sms("+2250700000001", "x")
    sms.cache.clear()
    with mock.patch("handy.sms.requests.post", side_effect=requests.ConnectTimeout("x")), pytest.raises(sms.SMSProviderUnavailable) as e:
        sms.send_sms("+2250700000001", "code 654321")
    assert "654321" not in str(e.value)


def test_orange_requires_credentials_and_a_sender(settings, monkeypatch):
    settings.SMS_BACKEND = "orange"
    with pytest.raises(sms.SMSNotConfigured):
        sms.get_backend()
    _orange_env(monkeypatch, ORANGE_SMS_SENDER="abc")
    with pytest.raises(sms.SMSNotConfigured):
        sms.get_backend()


# ---- Relève automatique ------------------------------------------------------------------------------------------

def _chain_env(settings, monkeypatch, chain="twilio,orange"):
    settings.SMS_BACKEND = chain
    for k, v in {"TWILIO_ACCOUNT_SID": "ACxxx", "TWILIO_AUTH_TOKEN": "tok", "TWILIO_FROM": "+15005550006"}.items():
        monkeypatch.setenv(k, v)
    _orange_env(monkeypatch)


def _providers_http(twilio, orange=None):
    """Aiguille les appels : Twilio → `twilio` (réponse ou exception), Orange → réponses de jeton puis d'envoi."""
    calls = []

    def fake_post(url, **kwargs):
        if "twilio.com" in url:
            calls.append("twilio")
            if isinstance(twilio, Exception):
                raise twilio
            return twilio
        calls.append("orange-token" if "/oauth/" in url else "orange")
        return _resp(200, _TOKEN_OK) if "/oauth/" in url else (orange or _resp(201))

    return mock.patch("handy.sms.requests.post", side_effect=fake_post), calls


def test_backend_names_parse_the_ordered_list(settings):
    for raw, expected in (("twilio,orange", ["twilio", "orange"]), (" Orange , TWILIO ;orange", ["orange", "twilio"]),
                          ("twilio", ["twilio"]), ("twilio,,twilio", ["twilio"])):
        settings.SMS_BACKEND = raw
        assert sms.backend_names() == expected
    settings.SMS_BACKEND = "twilio,orange"
    assert sms.backend_name() == "twilio,orange"


def test_the_first_provider_is_used_when_it_works(settings, monkeypatch):
    _chain_env(settings, monkeypatch)
    patch, calls = _providers_http(_resp(201))
    with patch:
        backend = sms.send_sms("+2250700000001", "x")
    assert calls == ["twilio"] and isinstance(backend, sms.TwilioBackend)


@pytest.mark.parametrize("twilio_fails", [
    _net_error(), _resp(500), _resp(429), _resp(401, {"code": 20003}), _resp(400, {"code": 21211}),
], ids=["injoignable", "5xx", "quota", "identifiants-refusés", "message-refusé"])
def test_when_twilio_fails_orange_takes_over_automatically(settings, monkeypatch, twilio_fails):
    _chain_env(settings, monkeypatch)
    patch, calls = _providers_http(twilio_fails)
    with patch:
        backend = sms.send_sms("+2250700000001", "Votre code : 123456")
    assert calls == ["twilio", "orange-token", "orange"]
    assert isinstance(backend, sms.OrangeBackend)  # le fournisseur qui a RÉELLEMENT livré est renvoyé
    assert sms.FailoverBackend.exposes_code is False


def test_the_order_is_configurable_and_orange_can_be_first(settings, monkeypatch):
    _chain_env(settings, monkeypatch, chain="orange,twilio")
    patch, calls = _providers_http(_resp(201), orange=_resp(503))
    with patch:
        backend = sms.send_sms("+2250700000001", "x")
    assert calls == ["orange-token", "orange", "twilio"] and isinstance(backend, sms.TwilioBackend)


def test_a_failed_provider_is_sidelined_so_the_next_sends_go_straight_to_the_other(settings, monkeypatch):
    _chain_env(settings, monkeypatch)
    patch, calls = _providers_http(_net_error())
    with patch:
        sms.send_sms("+2250700000001", "un")
        sms.send_sms("+2250700000002", "deux")
        sms.send_sms("+2250700000003", "trois")
    assert calls == ["twilio", "orange-token", "orange", "orange", "orange"]  # Twilio n'est plus attendu à chaque envoi


def test_a_sidelined_provider_is_still_the_last_resort_and_cooldown_zero_disables_sidelining(settings, monkeypatch):
    _chain_env(settings, monkeypatch)
    patch, calls = _providers_http(_net_error())
    with patch:
        sms.send_sms("+2250700000001", "un")  # Twilio tombe : mis de côté, Orange livre
    assert calls == ["twilio", "orange-token", "orange"]
    patch, calls = _providers_http(_resp(201), orange=_resp(503))  # Twilio rétabli mais encore écarté ; Orange tombe à son tour
    with patch:
        backend = sms.send_sms("+2250700000001", "deux")
    assert calls == ["orange", "twilio"] and isinstance(backend, sms.TwilioBackend)  # jamais d'impasse : le dernier recours est tenté
    sms.cache.clear()
    monkeypatch.setenv("SMS_FAILOVER_COOLDOWN", "0")
    patch, calls = _providers_http(_net_error())
    with patch:
        sms.send_sms("+2250700000001", "a")
        sms.send_sms("+2250700000002", "b")
    assert calls.count("twilio") == 2  # sans mise à l'écart, Twilio est essayé à chaque envoi


def test_a_message_level_refusal_does_not_sideline_the_provider(settings, monkeypatch):
    _chain_env(settings, monkeypatch)
    patch, calls = _providers_http(_resp(400, {"code": 21211}))  # numéro refusé : la relève envoie, mais Twilio n'est pas « en panne »
    with patch:
        sms.send_sms("+2250700000001", "a")
        sms.send_sms("+2250700000002", "b")
    assert calls.count("twilio") == 2


def test_when_every_provider_fails_the_error_is_a_clean_sms_error_without_secrets(settings, monkeypatch):
    _chain_env(settings, monkeypatch)
    patch, _ = _providers_http(_resp(500), orange=_resp(500))
    with patch, pytest.raises(sms.SMSError) as e:
        sms.send_sms("+2250700000001", "code 654321")
    assert type(e.value) is sms.SMSError  # 502 pour l'utilisateur, pas 503
    text = str(e.value)
    assert "twilio" in text.lower() and "orange" in text.lower()
    for secret in ("654321", "+2250700000001", "2250700000001", "ACxxx", "csecret", "Y2lkOmNzZWNyZXQ=", "tok-orange"):
        assert secret not in text


def test_when_every_provider_refuses_its_credentials_the_error_is_a_configuration_error(settings, monkeypatch):
    _chain_env(settings, monkeypatch)
    patch, _ = _providers_http(_resp(401, {"code": 20003}), orange=_resp(403))
    with patch, pytest.raises(sms.SMSNotConfigured):
        sms.send_sms("+2250700000001", "x")


def test_a_chain_needs_every_provider_configured_and_rejects_local_or_unknown_names(settings, monkeypatch):
    settings.SMS_BACKEND = "twilio,orange"
    for k, v in {"TWILIO_ACCOUNT_SID": "ACxxx", "TWILIO_AUTH_TOKEN": "tok", "TWILIO_FROM": "+1500"}.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(sms.SMSNotConfigured):  # Orange non configuré : jamais de relève « fantôme »
        sms.get_backend()
    for chain in ("console,twilio", "locmem,orange", "twilio,inconnu"):
        settings.SMS_BACKEND = chain
        _orange_env(monkeypatch)
        with pytest.raises(sms.SMSNotConfigured):
            sms.get_backend()


def test_a_single_provider_is_not_wrapped_in_a_failover(settings, monkeypatch):
    _chain_env(settings, monkeypatch, chain="orange")
    assert isinstance(sms.get_backend(), sms.OrangeBackend)


def test_otp_request_survives_a_twilio_outage_and_reports_both_down(settings, monkeypatch):
    _chain_env(settings, monkeypatch)
    user, c = _client()
    patch, calls = _providers_http(_net_error())
    with patch:
        r = c.post(reverse("otp-request"))
    assert r.status_code == 201 and calls == ["twilio", "orange-token", "orange"]
    assert r.json()["sent"] is True and "code" not in r.json()
    assert OTPCode.objects.filter(user=user, used=False).exists()
    sms.cache.clear()
    OTPCode.objects.all().delete()
    user2, c2 = _client(phone="+2250700000002", username="otp_user2")
    patch, _ = _providers_http(_net_error(), orange=_resp(500))
    with patch:
        r = c2.post(reverse("otp-request"))
    assert r.status_code == 502 and not OTPCode.objects.filter(user=user2, used=False).exists()


# ---- Délais d'attente : sans eux, un fournisseur qui accepte la connexion puis se tait bloque la relève ------------------------

@pytest.mark.parametrize("env,expected", [({}, 10), ({"SMS_TIMEOUT": "3"}, 3), ({"SMS_TIMEOUT": "abc"}, 10), ({"SMS_TIMEOUT": "0"}, 1)])
def test_every_provider_call_carries_the_configured_timeout(settings, monkeypatch, env, expected):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Orange : jeton ET envoi
    settings.SMS_BACKEND = "orange"
    _orange_env(monkeypatch)
    patch, calls = _orange_http()
    with patch:
        sms.send_sms("+2250700000001", "x")
    assert calls["oauth"][0][1]["timeout"] == expected and calls["sms"][0][1]["timeout"] == expected
    # Twilio
    settings.SMS_BACKEND = "twilio"
    for k, v in {"TWILIO_ACCOUNT_SID": "ACxxx", "TWILIO_AUTH_TOKEN": "tok", "TWILIO_FROM": "+1500"}.items():
        monkeypatch.setenv(k, v)
    with mock.patch("handy.sms.requests.post", return_value=_resp(201)) as post:
        sms.send_sms("+2250700000001", "x")
    assert post.call_args.kwargs["timeout"] == expected
    # Africa's Talking
    settings.SMS_BACKEND = "africastalking"
    monkeypatch.setenv("AT_USERNAME", "tratra")
    monkeypatch.setenv("AT_API_KEY", "key")
    good = _resp(201, {"SMSMessageData": {"Recipients": [{"statusCode": 101}]}})
    with mock.patch("handy.sms.requests.post", return_value=good) as post:
        sms.send_sms("+2250700000001", "x")
    assert post.call_args.kwargs["timeout"] == expected


# ---- Aucune fuite, ni dans les erreurs ni dans les journaux --------------------------------------------------------------

def test_logs_and_errors_across_a_failover_never_contain_the_code_the_number_or_credentials(settings, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    _chain_env(settings, monkeypatch)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "twauth-S3CRET-9")
    secrets = ("Votre code : 987654", "987654", "2250700000001", "0700000001", "twauth-S3CRET-9", "csecret",
               "Y2lkOmNzZWNyZXQ=", "tok-orange-1", "ACxxx")
    patch, _ = _providers_http(_net_error())  # Twilio injoignable, Orange livre
    with patch:
        sms.send_sms("+2250700000001", "Votre code : 987654")
    sms.cache.clear()
    patch, _ = _providers_http(  # tous en panne ; les corps de réponse REPRENNENT le numéro et le code
        _resp(500, {"detail": "+2250700000001 987654 twauth-S3CRET-9"}),
        orange=_resp(500, {"requestError": {"serviceException": {"messageId": "SVC0001", "text": "+2250700000001 987654"}}}))
    with patch, pytest.raises(sms.SMSError) as e:
        sms.send_sms("+2250700000001", "Votre code : 987654")
    haystack = caplog.text + str(e.value)
    assert "twilio" in caplog.text and "orange" in caplog.text  # les journaux existent bien : le test n'est pas vide
    for secret in secrets:
        assert secret not in haystack, secret


def test_the_otp_endpoint_never_returns_or_logs_the_real_code_when_every_provider_fails(settings, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    _chain_env(settings, monkeypatch)
    user, c = _client()
    patch, _ = _providers_http(_net_error(), orange=_resp(500, {"x": 1}))
    with patch:
        r = c.post(reverse("otp-request"))
    code = OTPCode.objects.filter(user=user).latest("id").code  # le VRAI code (tirage aléatoire), pas un littéral
    assert r.status_code == 502
    assert code not in r.content.decode() and f"vérification Tratra : {code}" not in caplog.text
    assert not OTPCode.objects.filter(user=user, used=False).exists()


# ---- Exceptions inattendues : jamais de relève interrompue, jamais de 500 qui laisse le code valide -------------------------

@pytest.mark.parametrize("boom", [
    UnicodeEncodeError("latin-1", "\u2019", 0, 1, "ordinal not in range(256)"), AttributeError("secret ACxxx"), KeyError("ACxxx"),
    RuntimeError("https://api.twilio.com/ACxxx twauth"),
], ids=["caractère-hors-latin1", "attribute", "key", "runtime"])
def test_an_unexpected_exception_in_a_provider_does_not_stop_the_failover_nor_leak_its_text(settings, monkeypatch, boom):
    _chain_env(settings, monkeypatch)
    patch, calls = _providers_http(boom)
    with patch:
        backend = sms.send_sms("+2250700000001", "x")
    assert calls == ["twilio", "orange-token", "orange"] and isinstance(backend, sms.OrangeBackend)
    sms.cache.clear()
    with mock.patch("handy.sms.requests.post", side_effect=boom), pytest.raises(sms.SMSError) as e:
        sms.send_sms("+2250700000001", "x")
    assert "ACxxx" not in str(e.value) and "twauth" not in str(e.value) and type(boom).__name__ in str(e.value)


def test_a_single_provider_with_an_unexpected_exception_is_a_clean_502_and_invalidates_the_otp(settings, monkeypatch):
    settings.SMS_BACKEND = "twilio"
    for k, v in {"TWILIO_ACCOUNT_SID": "ACxxx", "TWILIO_AUTH_TOKEN": "tok", "TWILIO_FROM": "+1500"}.items():
        monkeypatch.setenv(k, v)
    user, c = _client()
    with mock.patch("handy.sms.requests.post", side_effect=RuntimeError("ACxxx fuite")):
        r = c.post(reverse("otp-request"))
    assert r.status_code == 502 and "ACxxx" not in r.content.decode()
    assert not OTPCode.objects.filter(user=user, used=False).exists()  # pas de 500 : le code créé est invalidé


def test_twilio_and_africastalking_tolerate_unexpected_json_shapes(settings, monkeypatch):
    settings.SMS_BACKEND = "twilio"
    for k, v in {"TWILIO_ACCOUNT_SID": "ACxxx", "TWILIO_AUTH_TOKEN": "tok", "TWILIO_FROM": "+1500"}.items():
        monkeypatch.setenv(k, v)
    with mock.patch("handy.sms.requests.post", return_value=_resp(400, ["pas", "un", "objet"])), pytest.raises(sms.SMSError) as e:
        sms.send_sms("+2250700000001", "x")
    assert type(e.value) is sms.SMSError
    settings.SMS_BACKEND = "africastalking"
    monkeypatch.setenv("AT_USERNAME", "tratra")
    monkeypatch.setenv("AT_API_KEY", "key")
    with mock.patch("handy.sms.requests.post", return_value=_resp(201, {"SMSMessageData": {"Recipients": ["ok"]}})), \
            pytest.raises(sms.SMSError) as e:
        sms.send_sms("+2250700000001", "x")
    assert type(e.value) is sms.SMSError


# ---- Classification des erreurs de chaque fournisseur (qui est « en panne » ?) ---------------------------------------------

def _at_env(monkeypatch):
    monkeypatch.setenv("AT_USERNAME", "tratra")
    monkeypatch.setenv("AT_API_KEY", "key")


@pytest.mark.parametrize("provider", ["twilio", "africastalking"])
@pytest.mark.parametrize("outcome,expected", [
    ("network", sms.SMSProviderUnavailable), (429, sms.SMSProviderUnavailable), (500, sms.SMSProviderUnavailable),
    (503, sms.SMSProviderUnavailable), (401, sms.SMSNotConfigured), (403, sms.SMSNotConfigured), (400, sms.SMSError)])
def test_provider_errors_are_classified_exactly(settings, monkeypatch, provider, outcome, expected):
    settings.SMS_BACKEND = provider
    if provider == "twilio":
        for k, v in {"TWILIO_ACCOUNT_SID": "ACxxx", "TWILIO_AUTH_TOKEN": "tok", "TWILIO_FROM": "+1500"}.items():
            monkeypatch.setenv(k, v)
    else:
        _at_env(monkeypatch)
    kwargs = {"side_effect": _net_error()} if outcome == "network" else {"return_value": _resp(outcome, {"code": 1})}
    with mock.patch("handy.sms.requests.post", **kwargs), pytest.raises(sms.SMSError) as e:
        sms.send_sms("+2250700000001", "code 654321")
    assert type(e.value) is expected and "654321" not in str(e.value) and "ACxxx" not in str(e.value)


def test_twilio_then_africastalking_chain_relays(settings, monkeypatch):
    settings.SMS_BACKEND = "twilio,africastalking"
    for k, v in {"TWILIO_ACCOUNT_SID": "ACxxx", "TWILIO_AUTH_TOKEN": "tok", "TWILIO_FROM": "+1500"}.items():
        monkeypatch.setenv(k, v)
    _at_env(monkeypatch)
    seen = []

    def fake_post(url, **kwargs):
        seen.append("twilio" if "twilio" in url else "at")
        return _resp(503) if "twilio" in url else _resp(201, {"SMSMessageData": {"Recipients": [{"statusCode": 101}]}})

    with mock.patch("handy.sms.requests.post", side_effect=fake_post):
        backend = sms.send_sms("+2250700000001", "x")
    assert seen == ["twilio", "at"] and isinstance(backend, sms.AfricasTalkingBackend)


# ---- Mise à l'écart : durée, motifs, jeton Orange -------------------------------------------------------------------------

def test_sidelining_lasts_the_configured_cooldown_and_a_credentials_refusal_also_sidelines(settings, monkeypatch):
    _chain_env(settings, monkeypatch)
    monkeypatch.setenv("SMS_FAILOVER_COOLDOWN", "7")
    patch, calls = _providers_http(_resp(401, {"code": 20003}))
    with patch, mock.patch("handy.sms._cache_set", wraps=sms._cache_set) as cache_set:
        sms.send_sms("+2250700000001", "un")
    ttls = {c.args[0]: c.args[2] for c in cache_set.call_args_list}
    assert ttls["sms:down:twilio"] == 7  # la durée configurée, pas « pour toujours »
    assert ttls[next(k for k in ttls if k.startswith("sms:orange:token:"))] == 3480  # expires_in 3600 − 120 s de marge
    patch, calls = _providers_http(_resp(201))  # Twilio écarté (identifiants refusés) : le second envoi va directement à Orange
    with patch:
        sms.send_sms("+2250700000002", "deux")
    assert calls == ["orange"]


# ---- Orange : cas limites ------------------------------------------------------------------------------------------------

def test_orange_authorization_header_already_prefixed_is_used_as_is_and_missing_expires_in_defaults_to_one_hour(settings, monkeypatch):
    settings.SMS_BACKEND = "orange"
    monkeypatch.setenv("ORANGE_SMS_AUTHORIZATION_HEADER", "Basic abc123==")
    patch, calls = _orange_http(token=_resp(200, {"token_type": "Bearer", "access_token": "t"}))
    with patch, mock.patch("handy.sms._cache_set", wraps=sms._cache_set) as cache_set:
        sms.send_sms("+2250700000001", "x")
    assert calls["oauth"][0][1]["headers"]["Authorization"] == "Basic abc123=="
    assert [c.args[2] for c in cache_set.call_args_list] == [3480]


@pytest.mark.parametrize("status,expected", [(403, sms.SMSNotConfigured), (429, sms.SMSProviderUnavailable), (302, sms.SMSError)])
def test_orange_token_endpoint_other_statuses(settings, monkeypatch, status, expected):
    settings.SMS_BACKEND = "orange"
    _orange_env(monkeypatch)
    patch, _ = _orange_http(token=_resp(status))
    with patch, pytest.raises(sms.SMSError) as e:
        sms.send_sms("+2250700000001", "x")
    assert type(e.value) is expected


@pytest.mark.parametrize("token_response", [
    "valeur-non-json", _resp(200, {"access_token": "t", "expires_in": float("inf")}), _resp(200, ["pas", "un", "objet"])])
def test_orange_unreadable_token_responses_are_a_provider_outage_not_a_crash(settings, monkeypatch, token_response):
    settings.SMS_BACKEND = "orange"
    _orange_env(monkeypatch)
    if token_response == "valeur-non-json":
        token_response = _resp(200)
        token_response.json.side_effect = ValueError("pas du JSON")
    patch, _ = _orange_http(token=token_response)
    with patch, pytest.raises(sms.SMSProviderUnavailable):
        sms.send_sms("+2250700000001", "x")


def test_an_orange_outage_with_a_non_json_body_still_relays_to_twilio(settings, monkeypatch):
    _chain_env(settings, monkeypatch, chain="orange,twilio")
    html = _resp(502)
    html.json.side_effect = ValueError("<html>Bad gateway</html>")
    patch, calls = _providers_http(_resp(201), orange=html)
    with patch:
        backend = sms.send_sms("+2250700000001", "x")
    assert calls == ["orange-token", "orange", "twilio"] and isinstance(backend, sms.TwilioBackend)


def test_orange_error_codes_are_echoed_only_when_they_look_like_codes(settings, monkeypatch):
    settings.SMS_BACKEND = "orange"
    _orange_env(monkeypatch)
    for message_id, shown in (("SVC0002", True), ("POL1009", True), ("boom 0700000001", False), ("svc0002", False)):
        sms.cache.clear()
        patch, _ = _orange_http(send=_resp(400, {"requestError": {"serviceException": {"messageId": message_id}}}))
        with patch, pytest.raises(sms.SMSError) as e:
            sms.send_sms("+2250700000001", "x")
        assert ("(code " in str(e.value)) is shown and "0700000001" not in str(e.value)


@pytest.mark.parametrize("raw,expected", [
    ("", "2250000"), ("2250000", "2250000"), ("+225 0000", "2250000"), ("tel:+2250000", "2250000"),
    ("tel%3A%2B2250000", "2250000"), ("TEL:+2250000", "2250000"), ("%2B2250000", "2250000"), ("22500", "22500")])
def test_orange_sender_accepts_the_documented_forms_and_a_blank_means_the_default(settings, monkeypatch, raw, expected):
    settings.SMS_BACKEND = "orange"
    _orange_env(monkeypatch, ORANGE_SMS_SENDER=raw)
    assert sms.orange_sender(raw) == expected
    patch, calls = _orange_http()
    with patch:
        sms.send_sms("+2250700000001", "x")
    assert calls["sms"][0][0].endswith(f"/outbound/tel%3A%2B{expected}/requests")
    assert calls["sms"][0][1]["json"]["outboundSMSMessageRequest"]["senderAddress"] == f"tel:+{expected}"


@pytest.mark.parametrize("raw", ["abc", "12", "tel:+", "+" * 3, "1" * 20])
def test_orange_sender_that_is_not_a_country_number_is_refused(settings, monkeypatch, raw):
    settings.SMS_BACKEND = "orange"
    _orange_env(monkeypatch, ORANGE_SMS_SENDER=raw)
    with pytest.raises(sms.SMSNotConfigured):
        sms.get_backend()
