"""Compte unique : inscription téléphone + mot de passe, OTP, connexion par téléphone et récupération."""
import re
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from handy import sms
from handy.models import OTPCode

User = get_user_model()
pytestmark = pytest.mark.django_db
PASSWORD = "Tr4tra!Essai-2026"
NEW_PASSWORD = "Nouveau!Mot2Passe-77"


@pytest.fixture(autouse=True)
def _sms(settings):
    settings.SMS_BACKEND = "locmem"
    sms.outbox.clear()
    cache.clear()
    yield
    sms.outbox.clear()


def _payload(**extra):
    base = {"first_name": "Ama", "last_name": "Diallo", "phone": "0700000010", "password": PASSWORD,
            "accept_terms": True}
    base.update(extra)
    return base


def _signup(**extra):
    return APIClient().post(reverse("users-list"), _payload(**extra), format="json")


def _login(identifier, password=PASSWORD, key="username"):
    return APIClient().post(reverse("jwt-login"), {key: identifier, "password": password}, format="json")


def _last_code():
    return re.search(r"\b(\d{6})\b", sms.outbox[-1][1]).group(1)


# ---- Inscription ------------------------------------------------------------------------------

@pytest.mark.parametrize("missing", ["first_name", "last_name", "phone", "password", "accept_terms"])
def test_signup_requires_identity_phone_password_and_terms(missing):
    payload = _payload()
    payload.pop(missing)
    r = APIClient().post(reverse("users-list"), payload, format="json")
    assert r.status_code == 400 and missing in r.json(), r.content
    assert not User.objects.exists()


def test_signup_refuses_unaccepted_terms():
    r = _signup(accept_terms=False)
    assert r.status_code == 400 and "accept_terms" in r.json()


def test_signup_creates_an_unverified_account_without_username_or_email():
    r = _signup()
    assert r.status_code == 201, r.content
    body = r.json()
    user = User.objects.get(pk=body["id"])
    assert user.phone == "+2250700000010"          # E.164, +225 par défaut
    assert user.is_verified is False and body["is_verified"] is False
    assert user.email is None and re.fullmatch(r"u[0-9a-f]{12}", user.username)
    assert user.user_type == "client" and user.terms_accepted_at is not None
    assert not user.is_staff and not user.is_superuser
    assert "password" not in body and user.check_password(PASSWORD)


def test_several_accounts_without_email_can_coexist():
    assert _signup(phone="0700000011").status_code == 201
    assert _signup(phone="0700000012").status_code == 201
    assert User.objects.filter(email__isnull=True).count() == 2


def test_phone_formats_are_normalised_and_invalid_ones_refused():
    for raw, expected in (("+225 07 00 00 00 13", "+2250700000013"), ("00225 0700000014", "+2250700000014"),
                          ("+33 6 12 34 56 78", "+33612345678")):
        r = _signup(phone=raw)
        assert r.status_code == 201, (raw, r.content)
        assert User.objects.get(pk=r.json()["id"]).phone == expected
    for bad in ("abc", "12", "+0123456789", "x" * 30):
        r = _signup(phone=bad)
        assert r.status_code == 400 and "phone" in r.json(), (bad, r.content)


def test_signup_cannot_self_verify_or_escalate():
    r = _signup(is_verified=True, is_staff=True, user_type="admin")
    assert r.status_code == 400  # rôle admin refusé
    r = _signup(is_verified=True, is_staff=True)
    user = User.objects.get(pk=r.json()["id"])
    assert user.is_verified is False and user.is_staff is False


def test_signup_conflicts_are_generic_for_phone_and_email():
    assert _signup(email="Ama@Example.test").status_code == 201
    by_phone = _signup(email="autre@example.test")
    by_email = _signup(phone="0700000099", email="ama@example.test")
    for r in (by_phone, by_email):
        assert r.status_code == 400 and r.json()["code"] == "signup_unavailable"
    assert by_phone.json() == by_email.json()
    text = by_phone.content.decode().lower()
    assert "téléphone" not in text and "email" not in text and "existe" not in text


def test_legacy_clients_can_still_send_username_email_and_role():
    r = _signup(username="ancien_client", email="ancien@example.test", user_type="handyman")
    assert r.status_code == 201, r.content
    assert User.objects.get(username="ancien_client").user_type == "handyman"


# ---- Connexion : téléphone, ancien identifiant, e-mail -----------------------------------------

def test_login_by_phone_in_every_format_and_by_legacy_identifiers():
    user = User.objects.create_user("vieux_compte", "vieux@example.test", PASSWORD, phone="+2250700000020")
    for identifier in ("+2250700000020", "0700000020", "+225 07 00 00 00 20", "vieux_compte", "vieux@example.test"):
        r = _login(identifier)
        assert r.status_code == 200, (identifier, r.content)
        assert r.json()["access"] and r.json()["user"]["id"] == user.id
    assert _login("0700000020", key="phone").status_code == 200  # champ « phone » accepté aussi


def test_login_refuses_wrong_credentials_without_revealing_which():
    User.objects.create_user("exist", "exist@example.test", PASSWORD, phone="+2250700000021")
    wrong_password = _login("0700000021", "mauvais")
    unknown = _login("0700000999")
    assert wrong_password.status_code == unknown.status_code == 400  # contrat historique : 400 « identifiants invalides »
    assert wrong_password.json() == unknown.json()


def test_new_account_logs_in_by_phone_only():
    assert _signup(phone="0700000022").status_code == 201
    r = _login("+225 07 00 00 00 22")
    assert r.status_code == 200 and r.json()["user"]["is_verified"] is False


# ---- OTP : jamais vérifié avant la validation effective du code ----------------------------------

def _authed(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def test_otp_verification_is_the_only_way_to_a_verified_phone():
    user = User.objects.get(pk=_signup(phone="0700000030").json()["id"])
    api = _authed(user)
    r = api.post(reverse("otp-request"))
    assert r.status_code == 201
    assert r.json()["expires_in"] == 600 and r.json()["resend_in"] == 60 and "code" not in r.json()
    assert sms.outbox[-1][0] == "+2250700000030"
    user.refresh_from_db()
    assert user.is_verified is False            # code envoyé ≠ téléphone vérifié
    wrong = "000000" if _last_code() != "000000" else "111111"
    bad = api.post(reverse("otp-verify"), {"code": wrong}, format="json")
    assert bad.status_code == 400 and "4 essais" in bad.json()["detail"]
    user.refresh_from_db()
    assert user.is_verified is False
    ok = api.post(reverse("otp-verify"), {"code": _last_code()}, format="json")
    assert ok.status_code == 200
    user.refresh_from_db()
    assert user.is_verified is True


def test_sms_failure_is_reported_and_the_account_stays_unverified(settings):
    settings.SMS_BACKEND = ""  # aucun fournisseur (ou identifiants refusés)
    user = User.objects.get(pk=_signup(phone="0700000031").json()["id"])
    r = _authed(user).post(reverse("otp-request"))
    assert r.status_code == 503 and "pas disponible" in r.json()["detail"]
    user.refresh_from_db()
    assert user.is_verified is False and not OTPCode.objects.filter(user=user, used=False).exists()


def test_expired_code_never_verifies():
    user = User.objects.get(pk=_signup(phone="0700000032").json()["id"])
    api = _authed(user)
    api.post(reverse("otp-request"))
    OTPCode.objects.filter(user=user).update(expires_at=timezone.now() - timedelta(seconds=1))
    r = api.post(reverse("otp-verify"), {"code": _last_code()}, format="json")
    assert r.status_code == 400
    user.refresh_from_db()
    assert user.is_verified is False


def test_changing_the_phone_requires_a_new_verification():
    user = User.objects.get(pk=_signup(phone="0700000033").json()["id"])
    User.objects.filter(pk=user.pk).update(is_verified=True)
    user.refresh_from_db()
    r = _authed(user).patch(reverse("users-detail", args=[user.pk]), {"phone": "0700000034"}, format="json")
    assert r.status_code == 200 and r.json()["phone"] == "+2250700000034" and r.json()["is_verified"] is False
    user.refresh_from_db()
    assert user.is_verified is False


def test_email_is_added_after_login_and_conflicts_stay_generic():
    other = User.objects.create_user("autre", "pris@example.test", PASSWORD, phone="+2250700000040")
    user = User.objects.get(pk=_signup(phone="0700000035").json()["id"])
    api = _authed(user)
    r = api.patch(reverse("users-detail", args=[user.pk]), {"email": "Moi@Example.test"}, format="json")
    assert r.status_code == 200 and r.json()["email"] == "moi@example.test"
    r = api.patch(reverse("users-detail", args=[user.pk]), {"email": "pris@example.test"}, format="json")
    assert r.status_code == 400 and "existe" not in r.content.decode().lower()
    assert User.objects.get(pk=other.pk).email == "pris@example.test"


# ---- Récupération du compte par OTP --------------------------------------------------------------

def _recovery_user(phone="+2250700000050"):
    return User.objects.create_user("recup", None, PASSWORD, phone=phone, is_verified=False)


def _request(phone):
    return APIClient().post(reverse("password-reset-request"), {"phone": phone}, format="json")


def _confirm(phone, code, password=NEW_PASSWORD):
    return APIClient().post(reverse("password-reset-confirm"),
                            {"phone": phone, "code": code, "password": password}, format="json")


def test_recovery_by_otp_resets_the_password_and_proves_the_phone():
    user = _recovery_user()
    r = _request("0700000050")
    assert r.status_code == 202 and r.json()["phone"] == "+225••••50"
    assert sms.outbox[-1][0] == "+2250700000050"
    r = _confirm("0700000050", _last_code())
    assert r.status_code == 200 and r.json() == {"reset": True}
    user.refresh_from_db()
    assert user.is_verified is True and user.check_password(NEW_PASSWORD)
    assert _login("0700000050", PASSWORD).status_code == 400
    assert _login("0700000050", NEW_PASSWORD).status_code == 200
    # un code ne sert qu'une fois
    assert _confirm("0700000050", _last_code(), "Encore!Un-Autre-88").status_code == 400


def test_recovery_request_does_not_reveal_whether_a_number_is_registered():
    _recovery_user()
    known, unknown = _request("0700000050"), _request("0700000777")
    assert known.status_code == unknown.status_code == 202
    assert set(known.json()) == set(unknown.json())
    assert len(sms.outbox) == 1                       # un SMS seulement, pour le compte existant


def test_recovery_request_validates_the_number_and_reports_an_unavailable_provider(settings):
    assert _request("abc").status_code == 400
    settings.SMS_BACKEND = ""
    _recovery_user()
    for phone in ("0700000050", "0700000777"):        # même réponse que le compte existe ou non
        r = _request(phone)
        assert r.status_code == 503 and "pas disponible" in r.json()["detail"]
        cache.clear()
    assert not OTPCode.objects.filter(purpose="recovery", used=False).exists()


def test_recovery_cooldown_and_wrong_codes_are_limited():
    _recovery_user()
    assert _request("0700000050").status_code == 202
    again = _request("0700000050")
    assert again.status_code == 429 and again["Retry-After"]
    wrong = "000000" if _last_code() != "000000" else "111111"
    for i in range(4):
        r = _confirm("0700000050", wrong)
        assert r.status_code == 400 and "essai" in r.json()["detail"]
    assert _confirm("0700000050", wrong).status_code == 400   # 5e échec : code invalidé
    assert _confirm("0700000050", _last_code()).status_code == 429  # même le bon code : verrouillé
    assert User.objects.get(username="recup").check_password(PASSWORD)


def test_recovery_unknown_number_gets_the_same_error_as_a_wrong_code():
    _recovery_user()
    a, b = _confirm("0700000777", "123456"), _confirm("0700000050", "123456")
    assert a.status_code == b.status_code == 400
    assert a.json()["detail"].split(" Il vous reste")[0] == b.json()["detail"].split(" Il vous reste")[0]


def test_recovery_weak_password_is_refused_without_consuming_the_code():
    _recovery_user()
    _request("0700000050")
    code = _last_code()
    r = _confirm("0700000050", code, "12345678")
    assert r.status_code == 400 and "password" in r.json()
    assert _confirm("0700000050", code).status_code == 200


def test_recovery_revokes_existing_sessions():
    pytest.importorskip("rest_framework_simplejwt.token_blacklist")
    _recovery_user()
    refresh = _login("0700000050").json()["refresh"]
    _request("0700000050")
    assert _confirm("0700000050", _last_code()).status_code == 200
    r = APIClient().post(reverse("jwt-refresh"), {"refresh": refresh}, format="json")
    assert r.status_code == 401


# ---- Dashboard : espace entreprise lié au MÊME compte ---------------------------------------------

def test_company_space_is_created_on_the_current_account():
    user = User.objects.get(pk=_signup(phone="0700000060").json()["id"])
    api = _authed(user)
    assert api.get("/handy/me/dashboard/").json()["capabilities"]["company"] is False
    r = api.post("/handy/companies/me/", {"company_name": "Ama Bâtiment", "city": "Abidjan"}, format="json")
    assert r.status_code == 201, r.content
    caps = api.get("/handy/me/dashboard/").json()["capabilities"]
    assert caps["company"] is True and caps["client"] is True
    user.refresh_from_db()
    assert user.user_type == "client"                         # aucun second compte, aucun changement de rôle
    assert User.objects.count() == 1
