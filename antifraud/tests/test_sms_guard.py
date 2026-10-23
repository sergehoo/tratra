"""Garde des SMS : interrupteurs, destinations, quotas atomiques (concurrence comprise), journal sans code, alertes, et la demande
de code OTP (délai croissant, code renvoyé tant qu'il est valide, numéro déjà vérifié, essais). Aucun SMS réel : backend locmem."""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from antifraud import limits, sms_guard
from antifraud.models import SmsLog
from handy import sms
from handy.models import OTPCode

pytestmark = pytest.mark.django_db
User = get_user_model()
OTP = "/handy/auth/otp/request/"
VERIFY = "/handy/auth/otp/verify/"
RESET = "/handy/auth/password-reset/request/"


def account(n, phone=None, verified=False):
    return User.objects.create_user(f"af{n}", f"af{n}@x.test", "pass1234", phone=phone or f"+22507000{n:05d}", is_verified=verified)


def client(user, ip="10.0.0.1"):
    c = APIClient(REMOTE_ADDR=ip)
    c.force_authenticate(user)
    return c


# ── Interrupteurs (blocage des dépenses) ─────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("switch", ["SMS_ENABLED", "SMS_OTP_SIGNUP_ENABLED"])
def test_kill_switch_stops_every_verification_sms(antifraud_on, switch):
    setattr(antifraud_on, switch, False)
    u = account(1)
    r = client(u).post(OTP)
    assert r.status_code == 503 and "suspendu" in r.json()["detail"] and r.json()["code"] == "sms_kill_switch"
    assert sms.outbox == [] and not OTPCode.objects.filter(user=u, used=False).exists()
    log = SmsLog.objects.get()
    assert log.status == "blocked" and log.reason == "kill_switch" and log.user == u


def test_recovery_kill_switch_answers_the_same_for_known_and_unknown_numbers(antifraud_on):
    antifraud_on.SMS_RECOVERY_ENABLED = False
    account(2)
    known = APIClient().post(RESET, {"phone": "+2250700000002"}, format="json")
    unknown = APIClient().post(RESET, {"phone": "+2250700099999"}, format="json")
    assert known.status_code == unknown.status_code == 503 and known.json() == unknown.json()
    assert sms.outbox == []


def test_alerts_have_their_own_switch(antifraud_on):
    antifraud_on.SMS_ALERTS_ENABLED = False
    with pytest.raises(sms.SMSBlocked):
        sms.send_sms("+2250700000003", "Votre artisan arrive.")
    assert sms.outbox == []


# ── Destinations ────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("number, reason", [
    ("+33612345678", "destination_country"),        # hors des indicatifs autorisés (225 par défaut)
    ("+449012345678", "destination_country"),       # numéro surtaxé étranger
    ("+2252123456789", "destination_type"),         # fixe ivoirien : jamais de SMS
])
def test_only_mobile_numbers_of_allowed_countries_receive_sms(antifraud_on, number, reason):
    assert sms_guard.destination_issue(number) == reason
    with pytest.raises(sms.SMSBlocked) as exc:
        sms.send_sms(number, "x", purpose="otp_signup")
    assert exc.value.http_status == 400 and sms.outbox == []
    assert SmsLog.objects.get().reason == reason


def test_allowed_countries_are_configurable(antifraud_on):
    antifraud_on.SMS_ALLOWED_COUNTRY_CODES = "225,33"
    assert sms_guard.destination_issue("+33612345678") is None


# ── Quotas ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_per_number_quota(antifraud_on):
    for _ in range(3):
        sms.send_sms("+2250700000004", "x", purpose="otp_signup")
    with pytest.raises(sms.SMSBlocked) as exc:
        sms.send_sms("+2250700000004", "x", purpose="otp_signup")
    assert exc.value.reason == "quota_number" and exc.value.http_status == 429 and exc.value.retry_after
    assert len(sms.outbox) == 3


def test_per_ip_quota_across_many_accounts(antifraud_on):
    """Le scénario de l'attaque : un même client crée des comptes à la chaîne et demande un code pour chacun."""
    users = [account(100 + i) for i in range(7)]
    codes = [client(u, ip="203.0.113.9").post(OTP).status_code for u in users]
    assert codes[:5] == [201] * 5 and codes[5:] == [429, 429]
    assert len(sms.outbox) == 5
    assert SmsLog.objects.filter(status="blocked", reason="quota_ip").count() == 2


def test_global_quota_blocks_and_alerts_once(antifraud_on, caplog):
    antifraud_on.SMS_GLOBAL_HOURLY_LIMIT = 2
    with caplog.at_level(logging.CRITICAL, logger="antifraud.sms_guard"):
        sms.send_sms("+2250700000011", "x", purpose="otp_signup", ip="198.51.100.1")
        sms.send_sms("+2250700000012", "x", purpose="otp_signup", ip="198.51.100.2")
        for n in (13, 14):
            with pytest.raises(sms.SMSBlocked) as exc:
                sms.send_sms(f"+22507000000{n}", "x", purpose="otp_signup", ip=f"198.51.100.{n}")
            assert exc.value.reason == "quota_global"
    alerts = [r.getMessage() for r in caplog.records if r.levelno == logging.CRITICAL]
    assert any("QUOTA ATTEINT" in a for a in alerts) and sum("QUOTA ATTEINT" in a for a in alerts) == 1   # une alerte par fenêtre
    assert any("seuil d'alerte" in a for a in alerts)
    assert len(sms.outbox) == 2


def test_quota_alert_is_emailed_to_admins(antifraud_on, mailoutbox):
    antifraud_on.SMS_GLOBAL_HOURLY_LIMIT = 1
    antifraud_on.ADMINS = [("Equipe Tratra", "alertes@tratra.test")]
    antifraud_on.SERVER_EMAIL = "alertes@tratra.test"
    sms.send_sms("+2250700000016", "x", purpose="otp_signup")
    with pytest.raises(sms.SMSBlocked):
        sms.send_sms("+2250700000017", "x", purpose="otp_signup")
    assert {tuple(m.to) for m in mailoutbox} == {("alertes@tratra.test",)}
    bodies = [m.body for m in mailoutbox]
    assert sum("seuil d'alerte" in b for b in bodies) == 1 and sum("QUOTA ATTEINT" in b for b in bodies) == 1
    assert not any("+225" in b for b in bodies)             # ni numéro ni code dans l'alerte


def test_blocked_attempts_do_not_consume_the_global_quota(antifraud_on):
    antifraud_on.SMS_GLOBAL_HOURLY_LIMIT = 1
    for _ in range(5):                                      # numéro étranger : refusé avant tout quota
        with pytest.raises(sms.SMSBlocked):
            sms.send_sms("+33612345678", "x", purpose="otp_signup")
    sms.send_sms("+2250700000015", "x", purpose="otp_signup")   # le quota global reste intact pour un vrai utilisateur
    assert len(sms.outbox) == 1


def test_counters_are_atomic_under_concurrency(antifraud_on):
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: limits.hit("concurrence:test", 5, 3600)[0], range(40)))
    assert results.count(True) == 5
    ranks = []
    lock = threading.Lock()

    def attempt(_):
        r = limits.attempt("essais:test", 600)
        with lock:
            ranks.append(r)
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(attempt, range(30)))
    assert sorted(ranks) == list(range(1, 31))             # chaque essai a son propre rang : jamais deux à la fois


def test_without_a_working_cache_no_sms_is_spent(antifraud_on, monkeypatch):
    def broken(*a, **k):
        raise ConnectionError("redis down")
    monkeypatch.setattr(cache, "add", broken)
    with pytest.raises(sms.SMSBlocked) as exc:
        sms.send_sms("+2250700000016", "x", purpose="otp_signup", ip="10.1.1.1")
    assert exc.value.reason == "limits_unavailable" and sms.outbox == []


def test_the_journal_never_stores_the_code_or_the_full_number(antifraud_on):
    u = account(17)
    client(u).post(OTP)
    code = OTPCode.objects.get(user=u, used=False).code
    log = SmsLog.objects.get()
    values = " ".join(str(getattr(log, f.name)) for f in SmsLog._meta.fields)
    assert code not in values and "+2250700000017" not in values
    assert log.status == "sent" and log.number_masked.startswith("+225") and "•" in log.number_masked and log.provider == "locmem"
    assert log.number_hash == sms_guard.number_hash("+2250700000017") and log.ip == "10.0.0.1"


# ── Demande et saisie du code ───────────────────────────────────────────────────────────────────────────────────────────

def test_verified_numbers_never_get_a_code(antifraud_on):
    r = client(account(18, verified=True)).post(OTP)
    assert r.status_code == 409 and r.json()["code"] == "already_verified" and sms.outbox == []


def test_cooldown_grows_and_a_valid_code_is_resent_not_replaced(antifraud_on):
    u = account(19)
    c = client(u)
    first = c.post(OTP)
    assert first.status_code == 201 and first.json()["resend_in"] == 60
    assert c.post(OTP).status_code == 429
    SmsLog.objects.filter(user=u).update(created_at=timezone.now() - timedelta(seconds=61))
    resend = c.post(OTP)
    assert resend.status_code == 201 and resend.json()["resend_in"] == 120   # délai suivant : 2 min
    assert OTPCode.objects.filter(user=u).count() == 1                       # même code, renvoyé (pas un nouveau)
    assert sms.outbox[0][1] == sms.outbox[1][1]
    SmsLog.objects.filter(user=u).update(created_at=timezone.now() - timedelta(seconds=61))
    assert c.post(OTP).status_code == 429                                    # 3e envoi : 120 s exigées
    SmsLog.objects.filter(user=u).update(created_at=timezone.now() - timedelta(seconds=121))
    OTPCode.objects.filter(user=u).update(expires_at=timezone.now() + timedelta(seconds=60))   # bientôt expiré : nouveau code
    assert c.post(OTP).status_code == 201
    assert OTPCode.objects.filter(user=u, used=False).count() == 1 and OTPCode.objects.filter(user=u).count() == 2


def test_wrong_codes_are_counted_before_checking_and_lock_the_code(antifraud_on):
    u = account(20)
    c = client(u)
    c.post(OTP)
    real = OTPCode.objects.get(user=u, used=False).code
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(5):
        assert c.post(VERIFY, {"code": wrong}, format="json").status_code == 400
    assert c.post(VERIFY, {"code": real}, format="json").status_code == 429     # même le bon code : trop d'essais
    u.refresh_from_db()
    assert not u.is_verified and not OTPCode.objects.filter(user=u, used=False).exists()


def test_a_code_is_single_use(antifraud_on):
    u = account(21)
    c = client(u)
    c.post(OTP)
    code = OTPCode.objects.get(user=u, used=False).code
    assert c.post(VERIFY, {"code": code}, format="json").status_code == 200
    User.objects.filter(pk=u.pk).update(is_verified=False)
    assert c.post(VERIFY, {"code": code}, format="json").status_code == 400


def test_legitimate_user_flow_is_unchanged(antifraud_on):
    u = account(22)
    c = client(u, ip="192.0.2.50")
    assert c.post(OTP).status_code == 201
    code = OTPCode.objects.get(user=u, used=False).code
    assert c.post(VERIFY, {"code": code}, format="json").json() == {"verified": True}
    u.refresh_from_db()
    assert u.is_verified and len(sms.outbox) == 1
