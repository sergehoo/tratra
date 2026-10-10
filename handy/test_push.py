"""Push mobile FCM : sans identifiants rien n'est envoyé (et rien ne plante) ; avec identifiants, appareils enregistrés
via /devices/, charge utile exacte, jeton OAuth mis en cache, jetons morts supprimés. FCM est simulé : aucune requête réelle."""
import json

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth import get_user_model
from django.test import override_settings

from handy import push
from handy.models import Device, Notification
from handy.tasks import _send_fcm

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset():
    push.reset_cache()
    yield
    push.reset_cache()


@pytest.fixture
def service_account(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    path = tmp_path / "sa.json"
    path.write_text(json.dumps({"type": "service_account", "project_id": "tratra-test", "client_email": "push@tratra-test.iam.test",
                                "private_key": pem, "token_uri": "https://oauth.test/token"}))
    return str(path), public


class FakeHTTP:
    """Simule le point d'accès OAuth et l'API FCM v1."""

    def __init__(self, fcm_status=200, fcm_body=None):
        self.calls, self.fcm_status, self.fcm_body = [], fcm_status, fcm_body or {"name": "projects/x/messages/1"}

    def post(self, url, **kw):
        self.calls.append((url, kw))
        r = type("R", (), {})()
        if url == "https://oauth.test/token":
            r.status_code, r.text, r.raise_for_status, r.json = 200, "", (lambda: None), (lambda: {"access_token": "tok-123", "expires_in": 3600})
        else:
            r.status_code, r.text, r.json = self.fcm_status, json.dumps(self.fcm_body), (lambda: self.fcm_body)
        return r


def user_with_devices():
    u = User.objects.create_user("push_u", "p@x.test", "pass1234")
    Device.objects.create(user=u, device_token="tok-android", device_type="android")
    Device.objects.create(user=u, device_token="tok-ios", device_type="ios")
    Device.objects.create(user=u, device_token="tok-web", device_type="web")
    return u


def test_without_credentials_nothing_is_sent_and_nothing_fails(monkeypatch):
    u = user_with_devices()
    monkeypatch.setattr(push.requests, "post", lambda *a, **k: pytest.fail("aucune requête sans identifiants"))
    with override_settings(FCM_CREDENTIALS_FILE="", FCM_CREDENTIALS_JSON=""):
        assert push.is_configured() is False
        assert push.send_to_user(u.id, "T", "B") == {"sent": 0, "removed": 0, "skipped": "not_configured"}
        _send_fcm(u.id, "T", "B", {"k": 1})  # le chemin complet des notifications ne lève rien
    assert Device.objects.count() == 3


def test_unreadable_credentials_disable_push_instead_of_crashing(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("pas du json")
    u = user_with_devices()
    with override_settings(FCM_CREDENTIALS_FILE=str(bad)):
        assert push.send_to_user(u.id, "T", "B")["skipped"] == "not_configured"
    with override_settings(FCM_CREDENTIALS_FILE=str(tmp_path / "absent.json")):
        assert push.send_to_user(u.id, "T", "B")["skipped"] == "not_configured"


def test_with_credentials_android_and_ios_devices_receive_the_exact_payload(service_account, monkeypatch):
    path, public = service_account
    u = user_with_devices()
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)
    with override_settings(FCM_CREDENTIALS_FILE=path):
        out = push.send_to_user(u.id, "Moussa est en route", "Suivez son arrivée.", {"t": "live", "id": 12})
    assert out["sent"] == 2 and out["removed"] == 0
    fcm = [(url, kw) for url, kw in http.calls if "fcm.googleapis.com" in url]
    assert {kw["json"]["message"]["token"] for _, kw in fcm} == {"tok-android", "tok-ios"}   # jamais l'appareil « web »
    url, kw = fcm[0]
    assert url == "https://fcm.googleapis.com/v1/projects/tratra-test/messages:send"
    assert kw["headers"]["Authorization"] == "Bearer tok-123"
    msg = kw["json"]["message"]
    assert msg["notification"] == {"title": "Moussa est en route", "body": "Suivez son arrivée."}
    assert msg["data"] == {"t": "live", "id": "12"}   # valeurs converties en texte (exigence FCM)
    # le jeton OAuth est signé par le compte de service (vérifiable avec sa clé publique)
    oauth = next(kw for url, kw in http.calls if url == "https://oauth.test/token")
    claims = jwt.decode(oauth["data"]["assertion"], public, algorithms=["RS256"], audience="https://oauth.test/token")
    assert claims["iss"] == "push@tratra-test.iam.test" and "firebase.messaging" in claims["scope"]


def test_the_oauth_token_is_cached_between_sends(service_account, monkeypatch):
    path, _ = service_account
    u = user_with_devices()
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)
    with override_settings(FCM_CREDENTIALS_FILE=path):
        push.send_to_user(u.id, "A", "a")
        push.send_to_user(u.id, "B", "b")
    assert sum(1 for url, _ in http.calls if url == "https://oauth.test/token") == 1


def test_dead_tokens_are_removed_and_other_errors_keep_the_device(service_account, monkeypatch):
    path, _ = service_account
    u = user_with_devices()
    monkeypatch.setattr(push.requests, "post", FakeHTTP(404, {"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}).post)
    with override_settings(FCM_CREDENTIALS_FILE=path):
        out = push.send_to_user(u.id, "T", "B")
    assert out["removed"] == 2 and out["sent"] == 0
    assert list(Device.objects.values_list("device_type", flat=True)) == ["web"]
    other = User.objects.create_user("push_v", "v@x.test", "pass1234")
    Device.objects.create(user=other, device_token="tok-v", device_type="android")
    monkeypatch.setattr(push.requests, "post", FakeHTTP(500, {"error": {"status": "INTERNAL"}}).post)
    push.reset_cache()
    with override_settings(FCM_CREDENTIALS_FILE=path):
        assert push.send_to_user(other.id, "T", "B")["removed"] == 0
    assert Device.objects.filter(user=other).exists()


def test_network_failures_never_propagate(service_account, monkeypatch):
    path, _ = service_account
    u = user_with_devices()

    def boom(*a, **k):
        raise push.requests.ConnectionError("réseau coupé")

    monkeypatch.setattr(push.requests, "post", boom)
    with override_settings(FCM_CREDENTIALS_FILE=path):
        assert push.send_to_user(u.id, "T", "B")["sent"] == 0   # aucune exception
        _send_fcm(u.id, "T", "B")


def test_live_notifications_use_registered_devices_and_keep_the_in_app_record(service_account, monkeypatch):
    """Parcours réel : « Je suis en route » → notification in-app TOUJOURS créée, push envoyé au client s'il a un appareil."""
    from datetime import timedelta
    from django.utils import timezone
    from rest_framework.test import APIClient
    from handy.models import Booking
    from handy.test_booking_regression import _client
    from handy.test_eligibility import artisan, service
    path, _ = service_account
    art, cli = artisan("push_art"), _client("push_cli")
    Device.objects.create(user=cli, device_token="tok-client", device_type="android")
    b = Booking.objects.create(client=cli, handyman=art, service=service(art, "S"), status="confirmed", address="x", city="x",
                               booking_date=timezone.now() + timedelta(hours=1))
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)
    c = APIClient()
    c.force_authenticate(art)
    with override_settings(FCM_CREDENTIALS_FILE=path):
        assert c.post(f"/handy/bookings/{b.id}/live/en-route/", {"consent": True}, format="json").status_code == 200
    assert Notification.objects.filter(user=cli, notification_type="live_en_route").exists()
    sent = [kw["json"]["message"] for url, kw in http.calls if "fcm.googleapis.com" in url]
    assert len(sent) == 1 and sent[0]["token"] == "tok-client" and sent[0]["data"]["k"] == "en_route"
