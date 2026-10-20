"""Blocage de connexion lisible : après trop d'échecs, l'utilisateur voit « bloqué, patientez mm:ss ou contactez le support » (429, `login_locked`)
au lieu du même « identifiants incorrects » qu'un mauvais mot de passe, et ses nouveaux essais ne prolongent pas l'attente."""
import re
from datetime import timedelta

import pytest
from axes.models import AccessAttempt
from django.core.cache import cache
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from handy.auth_lockout import countdown, remaining_lock_seconds
from handy.models import User

pytestmark = pytest.mark.django_db
LOGIN = "/handy/auth/login/"
GOOD = "Secret-Ok-123"


@pytest.fixture(autouse=True)
def _fresh():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def member():
    return User.objects.create_user("lock_member", password=GOOD, phone="+2250700777111")


def attempt(password, who="lock_member", ip="203.0.113.10"):
    cache.clear()                                    # compteurs de débit (10/min) remis à zéro : ces tests portent sur le blocage Axes, pas sur la limitation de débit
    return APIClient().post(LOGIN, {"username": who, "password": password}, format="json", REMOTE_ADDR=ip)


def lock(ip="203.0.113.10"):
    for _ in range(5):
        assert attempt("faux", ip=ip).status_code == 400


def test_wrong_passwords_stay_an_ordinary_refusal_until_the_limit_is_reached(member):
    for _ in range(4):
        r = attempt("faux")
        assert r.status_code == 400 and "non_field_errors" in r.json() and "code" not in r.json()      # refus ordinaire, jamais un faux message de blocage


def test_once_locked_the_user_gets_a_clear_message_with_the_remaining_time(member):
    lock()
    r = attempt(GOOD)                                                                    # même le BON mot de passe est refusé pendant le blocage
    body = r.json()
    assert r.status_code == 429 and body["code"] == "login_locked" and "access" not in body
    assert 3500 <= body["retry_after"] <= 3601 and r["Retry-After"] == str(body["retry_after"])
    assert re.search(r"Patientez (59|60):\d\d ou contactez le support \(support@tratra\.net\)", body["detail"])
    assert body["support_email"] == "support@tratra.net" and body["locked_until"]


def test_the_countdown_follows_the_real_lock_and_blocked_attempts_do_not_extend_it(member):
    lock()
    row = AccessAttempt.objects.get(ip_address="203.0.113.10")
    AccessAttempt.objects.filter(pk=row.pk).update(attempt_time=timezone.now() - timedelta(minutes=24, seconds=30))
    before = AccessAttempt.objects.get(pk=row.pk)
    first = attempt(GOOD).json()["retry_after"]
    assert 2125 <= first <= 2135                                                         # 60 min − 24:30 = 35:30
    for _ in range(3):                                                                   # l'utilisateur insiste : rien ne repart à zéro
        assert attempt("encore faux").json()["code"] == "login_locked"
    after = AccessAttempt.objects.get(pk=row.pk)
    assert (after.failures_since_start, after.attempt_time) == (before.failures_since_start, before.attempt_time)
    assert attempt(GOOD).json()["retry_after"] <= first
    assert re.search(r"Patientez 3[45]:\d\d ", attempt(GOOD).json()["detail"])


def test_the_lock_ends_by_itself_and_the_right_password_works_again(member):
    lock()
    AccessAttempt.objects.update(attempt_time=timezone.now() - timedelta(minutes=61))
    r = attempt(GOOD)
    assert r.status_code == 200 and "access" in r.json()


def test_another_client_is_not_told_it_is_locked_and_can_sign_in(member):
    lock()
    assert attempt(GOOD, ip="198.51.100.77").status_code == 200
    r = attempt("faux", ip="198.51.100.78")
    assert r.status_code == 400 and "non_field_errors" in r.json()


def test_helpers():
    assert countdown(3330) == "55:30" and countdown(3600) == "60:00" and countdown(7) == "00:07" and countdown(-5) == "00:00"
    assert remaining_lock_seconds(None) is None
    request = RequestFactory().post(LOGIN, REMOTE_ADDR="192.0.2.5")
    assert remaining_lock_seconds(request, "personne") is None                            # source sans échec : pas bloquée
