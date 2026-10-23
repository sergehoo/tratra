"""Inscriptions (limites par IP / appareil / global, motifs de rafale, Turnstile), comptes non vérifiés, rapport des comptes suspects
et désactivation en lot réversible. Reproduit l'attaque observée : « Rita Kamal » × N, numéros +225 01 15 98 1xx."""
import io
import json
import uuid
from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.utils import timezone
from rest_framework.test import APIClient

from antifraud import report
from antifraud.models import AccountSuspension, SignupLog
from handy.conftest import STRONG_PASSWORD
from handy.test_eligibility import artisan, service

pytestmark = pytest.mark.django_db
User = get_user_model()
SIGNUP = "/handy/users/"
SITE = "https://tratra.net"


def signup(first="Ama", last="Diallo", phone="0700000010", ip="192.0.2.1", **headers):
    c = APIClient(REMOTE_ADDR=ip)
    return c.post(SIGNUP, {"first_name": first, "last_name": last, "phone": phone, "password": STRONG_PASSWORD, "accept_terms": True,
                           **headers.pop("extra", {})}, format="json", **headers)


# ── Inscriptions ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_mass_signup_from_one_ip_is_stopped(antifraud_on):
    codes = [signup(first=f"P{i}", last=f"N{i}", phone=f"07{i:02d}123456", ip="203.0.113.5").status_code for i in range(7)]
    assert codes == [201] * 5 + [429, 429]
    refused = SignupLog.objects.filter(accepted=False)
    assert refused.count() == 2 and set(refused.values_list("reason", flat=True)) == {"ip"}
    assert SignupLog.objects.filter(accepted=True, ip="203.0.113.5").count() == 5


def test_same_name_and_consecutive_numbers_are_stopped_even_from_many_ips(antifraud_on):
    """L'attaque : même nom, numéros consécutifs, adresses variées."""
    codes = [signup(first="Rita", last="Kamal", phone=f"+225011598{i:04d}"[:14], ip=f"198.51.100.{i}").status_code for i in range(6)]
    assert codes[:3] == [201, 201, 201] and set(codes[3:]) == {429}
    r = signup(first="Rita", last="Kamal", phone="+2250700123456", ip="198.51.100.77")
    assert r.status_code == 429 and r.json()["code"] == "signup_name"


def test_consecutive_number_blocks_are_limited(antifraud_on):
    codes = [signup(first=f"Nom{i}", last=f"Autre{i}", phone=f"+2250115981{i:03d}", ip=f"192.0.2.{10 + i}").status_code for i in range(5)]
    assert codes == [201, 201, 201, 429, 429]


def test_device_identifier_adds_a_limit(antifraud_on):
    device = str(uuid.uuid4())
    codes = [signup(first=f"D{i}", last=f"E{i}", phone=f"05{i:02d}654321", ip=f"192.0.2.{100 + i}", HTTP_X_TRATRA_DEVICE=device).status_code
             for i in range(4)]
    assert codes == [201, 201, 201, 429]
    assert signup(first="D9", last="E9", phone="0599654321", ip="192.0.2.199", HTTP_X_TRATRA_DEVICE="pas-un-uuid").status_code == 201


def test_global_signup_ceiling(antifraud_on):
    antifraud_on.SIGNUP_GLOBAL_HOURLY_LIMIT = 2
    codes = [signup(first=f"G{i}", last=f"H{i}", phone=f"01{i:02d}777888", ip=f"192.0.2.{i + 1}").status_code for i in range(3)]
    assert codes == [201, 201, 429]


def test_legitimate_signups_are_unaffected(antifraud_on):
    people = [("Ama", "Diallo", "0700000011"), ("Koffi", "Yao", "0500000012"), ("Awa", "Koné", "0100000013")]
    for i, (first, last, phone) in enumerate(people):
        assert signup(first=first, last=last, phone=phone, ip=f"192.0.2.{i + 1}").status_code == 201


@mock.patch("antifraud.turnstile.requests.post")
def test_turnstile_is_verified_server_side_for_the_website(post, antifraud_on):
    antifraud_on.TURNSTILE_SECRET_KEY = "secret-test"
    antifraud_on.CORS_ALLOWED_ORIGINS = [SITE]
    missing = signup(phone="0700000020", HTTP_ORIGIN=SITE)
    assert missing.status_code == 400 and missing.json()["code"] == "signup_captcha" and not post.called
    post.return_value = mock.Mock(status_code=200, json=lambda: {"success": False})
    assert signup(phone="0700000021", HTTP_ORIGIN=SITE, extra={"turnstile_token": "faux"}).status_code == 400
    post.return_value = mock.Mock(status_code=200, json=lambda: {"success": True})
    ok = signup(phone="0700000022", HTTP_ORIGIN=SITE, extra={"turnstile_token": "jeton"}, ip="192.0.2.42")
    assert ok.status_code == 201
    sent = post.call_args.kwargs["data"]
    assert sent == {"secret": "secret-test", "response": "jeton", "remoteip": "192.0.2.42"}
    assert SignupLog.objects.get(user__phone="+2250700000022").captcha == "ok"
    # Application mobile (pas d'en-tête Origin) : protections serveur seulement, sauf mode « all ».
    assert signup(first="App", last="Mobile", phone="0700000023", ip="192.0.2.43").status_code == 201
    antifraud_on.TURNSTILE_MODE = "all"
    assert signup(first="App", last="Deux", phone="0700000024", ip="192.0.2.44").status_code == 400


@mock.patch("antifraud.turnstile.requests.post", side_effect=OSError("injoignable"))
def test_turnstile_outage_never_lets_robots_through(post, antifraud_on):
    antifraud_on.TURNSTILE_SECRET_KEY = "secret-test"
    antifraud_on.CORS_ALLOWED_ORIGINS = [SITE]
    assert signup(phone="0700000030", HTTP_ORIGIN=SITE, extra={"turnstile_token": "jeton"}).status_code == 400


# ── Comptes non vérifiés ────────────────────────────────────────────────────────────────────────────────────────────────

def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def test_unverified_accounts_cannot_book_order_message_or_pay(antifraud_on):
    u = User.objects.create_user("unv", "unv@x.test", "pass1234", phone="+2250700000040")
    c = _api(u)
    for method, path, body in [("post", "/handy/bookings/", {}), ("post", "/handy/flash/requests/", {}), ("post", "/handy/payments/initiate/", {}),
                               ("post", "/handy/messages/", {}), ("post", "/handy/reviews/", {}), ("post", "/handy/me/kyc/send/", {}),
                               ("post", "/handy/engagements/postings/", {})]:
        r = getattr(c, method)(path, body, format="json")
        assert r.status_code == 403 and r.json()["code"] == "phone_not_verified", path
    # Lecture, profil, vérification du numéro : toujours possibles.
    assert c.get("/handy/users/me/").status_code == 200
    assert c.post("/handy/auth/otp/request/").status_code == 201


def test_verified_staff_and_historical_accounts_pass_the_gate(antifraud_on):
    verified = User.objects.create_user("ver", "ver@x.test", "pass1234", phone="+2250700000041", is_verified=True)
    assert _api(verified).post("/handy/bookings/", {}, format="json").status_code == 400            # validation métier, pas le verrou
    staff = User.objects.create_user("stf", "stf@x.test", "pass1234", is_staff=True)
    assert _api(staff).post("/handy/bookings/", {}, format="json").json().get("code") != "phone_not_verified"
    old = User.objects.create_user("old", "old@x.test", "pass1234", phone="+2250700000042")
    User.objects.filter(pk=old.pk).update(date_joined=timezone.now() - timedelta(days=30))
    antifraud_on.UNVERIFIED_RESTRICTIONS_SINCE = (timezone.now() - timedelta(days=1)).date().isoformat()
    old.refresh_from_db()
    assert _api(old).post("/handy/bookings/", {}, format="json").status_code == 400
    antifraud_on.UNVERIFIED_RESTRICTIONS = False
    fresh = User.objects.create_user("fresh", "fresh@x.test", "pass1234", phone="+2250700000043")
    assert _api(fresh).post("/handy/bookings/", {}, format="json").status_code == 400


def test_phone_changes_are_limited(antifraud_on):
    u = User.objects.create_user("chg", "chg@x.test", "pass1234", phone="+2250700000050", is_verified=True)
    c = _api(u)
    codes = [c.patch(f"/handy/users/{u.pk}/", {"phone": f"+22507000001{i:02d}"}, format="json").status_code for i in range(4)]
    assert codes == [200, 200, 200, 400]
    u.refresh_from_db()
    assert not u.is_verified


# ── Rapport et désactivation réversible ─────────────────────────────────────────────────────────────────────────────────

def _bots(n, start=0):
    out = []
    for i in range(start, start + n):
        out.append(User.objects.create_user(f"bot{i}", f"bot{i}@x.test", "pass1234", first_name="Rita", last_name="Kamal",
                                            phone=f"+2250115981{i:03d}"))
    return out


def test_report_lists_bots_and_never_legitimate_or_active_accounts(antifraud_on):
    bots = _bots(6)
    twin = User.objects.create_user("vraie_rita", "vraie@x.test", "pass1234", first_name="Rita", last_name="Kamal", phone="+2250707070707",
                                    is_verified=True)                                    # homonyme vérifiée
    busy = User.objects.create_user("rita_cliente", "cliente@x.test", "pass1234", first_name="Rita", last_name="Kamal", phone="+2250115981900")
    pro = artisan("rita_pro")
    service(pro)
    User.objects.filter(pk=pro.pk).update(first_name="Rita", last_name="Kamal")       # artisane avec une offre : activité réelle
    from handy.models import Booking
    Booking.objects.create(client=busy, handyman=pro, service=pro.services.first(), booking_date=timezone.now() + timedelta(days=1),
                           address="x", status="pending", total_price=5000)
    data = report.build(timezone.now() - timedelta(hours=1))
    ids = {c["id"] for c in data["candidates"]}
    assert ids == {b.pk for b in bots}
    assert twin.pk not in ids and busy.pk not in ids and pro.pk not in ids
    assert data["summary"]["excluded_verified"] >= 1 and data["summary"]["excluded_active"] >= 2
    assert ["rita kamal", 9] in data["summary"]["top_names"]
    candidate = data["candidates"][0]
    assert "•" in candidate["phone"] and any(r.startswith("nom répété") for r in candidate["reasons"])


def test_suspension_is_reviewed_reversible_and_rechecks_each_account(antifraud_on, tmp_path):
    bots = _bots(5)
    out = tmp_path / "rapport.json"
    call_command("antifraud_accounts", "report", "--since", (timezone.now() - timedelta(hours=1)).isoformat(timespec="minutes"),
                 "--out", str(out), stdout=io.StringIO())
    assert out.exists() and out.with_suffix(".csv").exists()
    with pytest.raises(CommandError):
        call_command("antifraud_accounts", "suspend", "--report", str(out), stdout=io.StringIO())     # confirmation exigée
    User.objects.filter(pk=bots[0].pk).update(is_verified=True)                                   # vérifié entre-temps : écarté
    msg = io.StringIO()
    call_command("antifraud_accounts", "suspend", "--report", str(out), "--confirm", "DESACTIVER-COMPTES", stdout=msg)
    assert "4 compte(s) désactivé(s), 1 écarté(s)" in msg.getvalue()
    assert User.objects.filter(pk__in=[b.pk for b in bots[1:]], is_active=False).count() == 4
    assert User.objects.get(pk=bots[0].pk).is_active and User.objects.count() >= 5                 # rien n'est supprimé
    batch_id = AccountSuspension.objects.first().batch_id
    assert report.restore_one(batch_id, bots[1].pk) and User.objects.get(pk=bots[1].pk).is_active
    call_command("antifraud_accounts", "revert", "--batch", str(batch_id), "--confirm", "REACTIVER-COMPTES", stdout=io.StringIO())
    assert User.objects.filter(pk__in=[b.pk for b in bots], is_active=True).count() == 5
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["candidates"]) == 5


def test_a_suspended_account_can_no_longer_use_its_tokens(antifraud_on):
    bot = _bots(1)[0]
    login = APIClient().post("/handy/auth/login/", {"username": bot.username, "password": "pass1234"}, format="json")
    token = login.json().get("access")
    assert token
    report.suspend([{"id": bot.pk, "reasons": ["test"]}], label="test", criteria={})
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert c.get("/handy/users/me/").status_code == 401
