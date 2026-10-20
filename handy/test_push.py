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
        assert push.send_to_user(u.id, "T", "B") == {"sent": 0, "removed": 0, "failed": 0, "devices": 0, "skipped": "not_configured"}
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
    assert msg["android"] == {"priority": "high", "ttl": "86400s", "notification": {"channel_id": "tratra_default"}}
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


def test_live_notifications_use_registered_devices_and_keep_the_in_app_record(service_account, monkeypatch, django_capture_on_commit_callbacks):
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
    with override_settings(FCM_CREDENTIALS_FILE=path), django_capture_on_commit_callbacks(execute=True):
        assert c.post(f"/handy/bookings/{b.id}/live/en-route/", {"consent": True}, format="json").status_code == 200
    assert Notification.objects.filter(user=cli, notification_type="live_en_route").exists()
    sent = [kw["json"]["message"] for url, kw in http.calls if "fcm.googleapis.com" in url]
    assert len(sent) == 1 and sent[0]["token"] == "tok-client" and sent[0]["data"]["t"] == "live_en_route"
    assert sent[0]["data"]["deeplink"] == f"tratra://booking/{b.id}"


# ── Enregistrement des appareils : idempotent et toujours rattaché au dernier compte connecté ──

def _login(username):
    from rest_framework.test import APIClient
    from handy.test_booking_regression import _client
    _client(username)
    r = APIClient().post("/handy/auth/login/", {"username": username, "password": "pass1234"}, format="json")
    assert r.status_code == 200, r.content
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.json()['access']}")
    return c


def test_device_registration_needs_no_user_id_and_is_idempotent():
    a = _login("push_reg_a")
    r = a.post("/handy/devices/", {"device_token": "tok-reg", "device_type": "android"}, format="json")
    assert r.status_code == 201, r.content
    again = a.post("/handy/devices/", {"device_token": "tok-reg", "device_type": "android"}, format="json")
    assert again.status_code == 200 and again.json()["id"] == r.json()["id"]
    assert Device.objects.filter(device_token="tok-reg").count() == 1


def test_a_token_follows_the_last_account_signed_in_on_the_phone():
    a, b = _login("push_swap_a"), _login("push_swap_b")
    a.post("/handy/devices/", {"device_token": "tok-shared", "device_type": "android"}, format="json")
    r = b.post("/handy/devices/", {"device_token": "tok-shared", "device_type": "android"}, format="json")
    assert r.status_code == 200
    assert Device.objects.get(device_token="tok-shared").user.username == "push_swap_b"
    # l'ancien compte ne voit plus l'appareil, ne peut pas le supprimer, et ne reçoit plus de push dessus
    assert a.get("/handy/devices/").json()["results"] == []
    assert a.delete(f"/handy/devices/{r.json()['id']}/").status_code == 404
    assert [d.device_token for d in Device.objects.filter(user__username="push_swap_a")] == []


def test_registration_cannot_target_another_user_and_logout_removes_the_device():
    a, b = _login("push_own_a"), _login("push_own_b")
    other = b.get("/handy/users/me/").json()["id"]
    r = a.post("/handy/devices/", {"device_token": "tok-own", "device_type": "android", "user": other}, format="json")
    assert r.status_code == 201 and Device.objects.get(device_token="tok-own").user.username == "push_own_a"
    assert a.delete(f"/handy/devices/{r.json()['id']}/").status_code == 204
    assert not Device.objects.filter(device_token="tok-own").exists()


def test_registration_rejects_unknown_platforms_and_requires_authentication():
    from rest_framework.test import APIClient
    a = _login("push_val_a")
    assert a.post("/handy/devices/", {"device_token": "tok-x", "device_type": "toaster"}, format="json").status_code == 400
    assert APIClient().post("/handy/devices/", {"device_token": "tok-y", "device_type": "android"}, format="json").status_code == 401


def test_token_renewal_removes_the_previous_token_of_the_same_account_only():
    a, b = _login("push_renew_a"), _login("push_renew_b")
    a.post("/handy/devices/", {"device_token": "tok-old", "device_type": "android"}, format="json")
    b.post("/handy/devices/", {"device_token": "tok-b", "device_type": "android"}, format="json")
    # a renouvelle son jeton ; une tentative de supprimer le jeton d'un autre compte via previous_token est sans effet
    r = a.post("/handy/devices/", {"device_token": "tok-new", "device_type": "android", "previous_token": "tok-old"}, format="json")
    assert r.status_code == 201
    a.post("/handy/devices/", {"device_token": "tok-new2", "device_type": "android", "previous_token": "tok-b"}, format="json")
    tokens = set(Device.objects.values_list("device_token", flat=True))
    assert "tok-old" not in tokens and {"tok-new", "tok-new2", "tok-b"} <= tokens



# ── Écran verrouillé : aucun contenu sensible dans le push, pastille numérique Android ──

def _push_for(user, ntype, message, title, http, path, monkeypatch, django_capture_on_commit_callbacks, **settings_kw):
    from handy.notifications import notify

    monkeypatch.setattr(push.requests, "post", http.post)
    with override_settings(FCM_CREDENTIALS_FILE=path, **settings_kw), django_capture_on_commit_callbacks(execute=True):
        notify(user.id, ntype, message, title=title)
    return [kw["json"]["message"] for url, kw in http.calls if "fcm.googleapis.com" in url][-1]


@pytest.mark.parametrize("ntype,message,title,expected_title,hidden", [
    ("message_received", "Mon code d'accès est 4821", "Awa K.", "Nouveau message", "4821"),
    ("kyc_rejected", "Votre document « Carte nationale d’identité » a été refusé. Motif : photo floue.", "Document refusé", "Votre compte Tratra", "floue"),
    ("payment_received", "Paiement de 15000 FCFA disponible pour « Fuite ».", "Paiement reçu", "Paiement", "15000"),
])
def test_sensitive_pushes_show_neutral_text_on_the_lock_screen(service_account, monkeypatch, django_capture_on_commit_callbacks,
                                                               ntype, message, title, expected_title, hidden):
    path, _ = service_account
    u = user_with_devices()
    msg = _push_for(u, ntype, message, title, FakeHTTP(), path, monkeypatch, django_capture_on_commit_callbacks)
    assert msg["notification"]["title"] == expected_title
    assert hidden not in json.dumps(msg["notification"], ensure_ascii=False)
    assert msg["android"]["notification"]["visibility"] == "PRIVATE"
    # le détail reste dans l'application (notification enregistrée intacte)
    assert Notification.objects.filter(user=u, notification_type=ntype, message=message).exists()


def test_message_preview_can_be_enabled_by_the_operator_and_ordinary_pushes_stay_complete(service_account, monkeypatch, django_capture_on_commit_callbacks):
    path, _ = service_account
    u = user_with_devices()
    msg = _push_for(u, "message_received", "On se voit demain ?", "Awa K.", FakeHTTP(), path, monkeypatch, django_capture_on_commit_callbacks,
                    PUSH_MESSAGE_PREVIEW=True)
    assert msg["notification"] == {"title": "Awa K.", "body": "On se voit demain ?"}
    live = _push_for(u, "booking_confirmed", "Votre réservation « Fuite » est confirmée.", "Réservation confirmée", FakeHTTP(), path,
                     monkeypatch, django_capture_on_commit_callbacks)
    assert live["notification"]["body"] == "Votre réservation « Fuite » est confirmée."
    assert "visibility" not in live["android"]["notification"]


def test_android_shows_the_unread_count_as_a_badge(service_account, monkeypatch, django_capture_on_commit_callbacks):
    path, _ = service_account
    u = user_with_devices()
    Notification.objects.create(user=u, notification_type="system", message="déjà là")
    msg = _push_for(u, "booking_confirmed", "Confirmée.", "Réservation confirmée", FakeHTTP(), path, monkeypatch, django_capture_on_commit_callbacks)
    assert msg["android"]["notification"]["notification_count"] == 2
    assert msg["apns"]["payload"]["aps"]["badge"] == 2
