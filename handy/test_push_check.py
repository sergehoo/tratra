"""Contrôles de configuration FCM (`push_check`) et validation sans remise — FCM est simulé."""
import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from handy import push
from handy.models import Device
from handy.test_push import FakeHTTP, service_account, user_with_devices  # noqa: F401  (fixtures partagées)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset():
    push.reset_cache()
    yield
    push.reset_cache()


def run(*args, **kwargs):
    out = StringIO()
    call_command("push_check", *args, stdout=out, **kwargs)
    return out.getvalue()


def test_without_configuration_the_command_says_so_and_exits_with_an_error():
    with override_settings(FCM_CREDENTIALS_FILE="", FCM_CREDENTIALS_JSON=""):
        with pytest.raises(SystemExit) as exit_info:
            run()
    assert exit_info.value.code == 1


def test_configured_report_shows_project_and_devices_but_never_a_secret(service_account):
    path, _ = service_account
    user_with_devices()
    with override_settings(FCM_CREDENTIALS_FILE=path):
        report = run()
    assert "chargée" in report and "tratra-test" in report and "android=1, ios=1, web=1" in report
    assert "PRIVATE KEY" not in report and "client_email" not in report and "push@tratra-test" not in report


def test_token_option_proves_the_service_account_by_getting_an_oauth_token(service_account, monkeypatch):
    path, _ = service_account
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)
    with override_settings(FCM_CREDENTIALS_FILE=path):
        assert "obtenu" in run(token=True)
    assert [c[0] for c in http.calls] == ["https://oauth.test/token"]


def test_validate_sends_a_validate_only_message_and_send_delivers_a_real_one(service_account, monkeypatch):
    path, _ = service_account
    u = user_with_devices()
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)
    with override_settings(FCM_CREDENTIALS_FILE=path):
        assert "validation seule" in run(user=u.pk, validate=True)
        fcm = [kw["json"] for url, kw in http.calls if "fcm.googleapis.com" in url]
        assert len(fcm) == 2 and all(m.get("validate_only") is True for m in fcm)                   # un message par appareil mobile, jamais remis
        http.calls.clear()
        assert "envoi réel" in run(user=u.pk, send=True)
        fcm = [kw["json"] for url, kw in http.calls if "fcm.googleapis.com" in url]
        assert len(fcm) == 2 and all("validate_only" not in m for m in fcm)
        assert fcm[0]["message"]["android"]["priority"] == "high" and fcm[0]["message"]["data"]["deeplink"] == "tratra://notifications"
        with pytest.raises(CommandError):
            run(validate=True)                                                                      # --user obligatoire


def test_a_user_without_device_gets_an_actionable_hint(service_account, monkeypatch):
    path, _ = service_account
    from django.contrib.auth import get_user_model

    u = get_user_model().objects.create_user("pc_nodev", "pc@x.test", "pass1234")
    monkeypatch.setattr(push.requests, "post", FakeHTTP().post)
    with override_settings(FCM_CREDENTIALS_FILE=path):
        assert "aucun appareil" in run(user=u.pk, validate=True)
    assert Device.objects.filter(user=u).count() == 0
