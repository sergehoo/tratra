"""Garde-fous des tests de charge : jamais la production, jamais une base réelle, jamais un SMS ni un push."""
import importlib.util
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from loadtest import guard

ROOT = Path(__file__).resolve().parent.parent


def _http_load():
    spec = importlib.util.spec_from_file_location("http_load", ROOT / "scripts" / "loadtest" / "http_load.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_measurements_refuse_any_environment_that_is_not_the_throwaway_one(settings, monkeypatch):
    monkeypatch.setenv("DJANGO_ENV", "dev")
    settings.DEBUG = True
    settings.SMS_ENABLED = True
    issues = " ".join(guard.problems())
    assert "DJANGO_ENV" in issues and "DEBUG" in issues and "SMS_ENABLED" in issues and "tratra_loadtest" in issues
    with pytest.raises(ImproperlyConfigured):
        guard.assert_safe()


@pytest.mark.filterwarnings("ignore:Overriding setting DATABASES")   # aucune base n'est ouverte dans ce test
def test_an_sms_provider_or_a_push_account_blocks_the_measurements(settings, monkeypatch):
    from handy import push

    monkeypatch.setenv("DJANGO_ENV", "loadtest")
    settings.DATABASES = {"default": {**settings.DATABASES["default"], "NAME": "tratra_loadtest", "HOST": "127.0.0.1"}}
    settings.DEBUG, settings.SMS_ENABLED = False, False
    settings.SMS_BACKEND, settings.FCM_CREDENTIALS_JSON, settings.FCM_CREDENTIALS_FILE = "", "", ""
    monkeypatch.delenv("SMS_BACKEND", raising=False)
    assert guard.problems() == []
    settings.SMS_BACKEND = "twilio"
    assert any("SMS" in p for p in guard.problems())
    settings.SMS_BACKEND = ""
    settings.FCM_CREDENTIALS_JSON = '{"private_key": "x", "client_email": "y@z", "project_id": "mesure"}'
    push.reset_cache()
    try:
        assert any("FCM" in p for p in guard.problems())
    finally:
        settings.FCM_CREDENTIALS_JSON = ""
        push.reset_cache()


@pytest.mark.parametrize("url", ["https://api.tratra.net", "https://tratra.net", "https://www.tratra.net/x", "https://minioapi.tratra.net"])
def test_production_is_never_a_load_target(url):
    with pytest.raises(ValueError):
        guard.check_target(url, allow_hosts={"api.tratra.net", "tratra.net", "www.tratra.net", "minioapi.tratra.net"})
    with pytest.raises(SystemExit):
        _http_load().check_target(url, {"api.tratra.net", "tratra.net", "www.tratra.net", "minioapi.tratra.net"})


def test_local_targets_pass_and_a_staging_host_must_be_named():
    assert guard.check_target("http://127.0.0.1:8101") == "127.0.0.1"
    with pytest.raises(ValueError):
        guard.check_target("https://staging.tratra.net")
    assert guard.check_target("https://staging.tratra.net", allow_hosts={"staging.tratra.net"}) == "staging.tratra.net"
    assert _http_load().check_target("http://localhost:8102", set()) == "localhost"
