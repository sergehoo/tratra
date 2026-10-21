"""« Se souvenir de moi » : durée de session selon le choix, conservée par la rotation ; cookie HttpOnly pour le site ; révocation,
expiration, comptes désactivés, revendications MFA et sessions existantes préservées (handy/auth_tokens.py)."""
import time

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from handy.auth_tokens import COOKIE_NAME, REMEMBER_CLAIM
from handy.models import User

pytestmark = pytest.mark.django_db
DAY = 24 * 3600


@pytest.fixture
def awa():
    return User.objects.create_user(username="awa_rm", email="awa_rm@x.test", password="Motdepasse1", phone="+2250700000888")


def login(c, remember=None, cookie=False, **extra):
    body = {"phone": "+2250700000888", "password": "Motdepasse1"}
    if remember is not None:
        body["remember_me"] = remember
    headers = {"HTTP_X_AUTH_TRANSPORT": "cookie"} if cookie else {}
    return c.post("/handy/auth/login/", body, format="json", **headers, **extra)


def lifetime(token: str) -> float:
    t = RefreshToken(token)
    return t["exp"] - time.time()


def test_checked_by_default_long_session_and_unchecked_short_session(awa):
    r = login(APIClient())
    assert r.status_code == 200, r.content
    token = RefreshToken(r.json()["refresh"])
    assert token[REMEMBER_CLAIM] == 1 and 29 * DAY < lifetime(r.json()["refresh"]) <= 30 * DAY   # application : jeton dans le corps
    r = login(APIClient(), remember=False)
    assert RefreshToken(r.json()["refresh"])[REMEMBER_CLAIM] == 0
    assert 11 * 3600 < lifetime(r.json()["refresh"]) <= 12 * 3600
    assert "password" not in str(r.json()).lower()


def test_rotation_keeps_the_chosen_duration_and_revokes_the_previous_token(awa):
    short = login(APIClient(), remember=False).json()["refresh"]
    r = APIClient().post("/handy/auth/refresh/", {"refresh": short}, format="json")
    assert r.status_code == 200
    rotated = r.json()["refresh"]
    assert RefreshToken(rotated)[REMEMBER_CLAIM] == 0 and lifetime(rotated) <= 12 * 3600     # jamais allongée à 30 jours
    again = APIClient().post("/handy/auth/refresh/", {"refresh": short}, format="json")
    assert again.status_code == 401 and again.json()["code"] == "token_not_valid"           # ancien jeton : liste noire


def test_existing_sessions_keep_their_original_duration(awa):
    legacy = RefreshToken.for_user(awa)                                                     # émis avant « se souvenir de moi »
    r = APIClient().post("/handy/auth/refresh/", {"refresh": str(legacy)}, format="json")
    assert r.status_code == 200
    assert REMEMBER_CLAIM not in RefreshToken(r.json()["refresh"]).payload
    assert 6 * DAY < lifetime(r.json()["refresh"]) <= 7 * DAY


def test_double_authentication_proof_survives_the_refresh(awa):
    token = RefreshToken.for_user(awa)
    token["mfa_at"], token["mfa_c"] = 1_790_000_000, 3
    r = APIClient().post("/handy/auth/refresh/", {"refresh": str(token)}, format="json")
    access = AccessToken(r.json()["access"])
    assert (access["mfa_at"], access["mfa_c"]) == (1_790_000_000, 3)


def test_web_cookie_is_httponly_lax_scoped_and_persistent_only_when_remembered(awa):
    r = login(APIClient(), cookie=True)
    assert "refresh" not in r.json() and r.json()["access"]                                 # jamais lisible par le JavaScript
    cookie = r.cookies[COOKIE_NAME]
    assert cookie["httponly"] and cookie["samesite"] == "Lax" and cookie["path"] == "/handy/auth/"
    assert int(cookie["max-age"]) > 29 * DAY
    session = login(APIClient(), remember=False, cookie=True).cookies[COOKIE_NAME]
    assert session["max-age"] == "" and session["expires"] == ""                             # cookie de session : fermeture du navigateur


def test_web_refresh_through_the_cookie_rotates_it_and_a_revoked_cookie_is_cleared(awa):
    c = APIClient()
    first = login(c, cookie=True).cookies[COOKIE_NAME].value
    r = c.post("/handy/auth/refresh/", {}, format="json", HTTP_X_AUTH_TRANSPORT="cookie")
    assert r.status_code == 200 and "refresh" not in r.json()
    assert r.cookies[COOKIE_NAME].value != first                                             # rotation
    stolen = APIClient()
    stolen.cookies[COOKIE_NAME] = first
    bad = stolen.post("/handy/auth/refresh/", {}, format="json", HTTP_X_AUTH_TRANSPORT="cookie")
    assert bad.status_code == 401 and bad.cookies[COOKIE_NAME].value == ""                   # révoqué : le navigateur l'oublie


def test_cookie_is_ignored_without_the_transport_header(awa):
    c = APIClient()
    login(c, cookie=True)
    r = c.post("/handy/auth/refresh/", {}, format="json")                                    # pas d'en-tête (formulaire d'un autre site)
    assert r.status_code == 401


def test_logout_revokes_the_session_and_is_idempotent(awa):
    c = APIClient()
    login(c, cookie=True)
    r = c.post("/handy/auth/logout/", {}, format="json", HTTP_X_AUTH_TRANSPORT="cookie")
    assert r.status_code == 200 and r.cookies[COOKIE_NAME].value == ""
    mobile = login(APIClient()).json()["refresh"]
    assert APIClient().post("/handy/auth/logout/", {"refresh": mobile}, format="json").status_code == 200
    assert APIClient().post("/handy/auth/refresh/", {"refresh": mobile}, format="json").status_code == 401
    assert APIClient().post("/handy/auth/logout/", {"refresh": mobile}, format="json").status_code == 200   # déjà révoqué


def test_deactivated_or_deleted_account_cannot_refresh(awa):
    token = login(APIClient()).json()["refresh"]
    User.objects.filter(pk=awa.pk).update(is_active=False)
    assert APIClient().post("/handy/auth/refresh/", {"refresh": token}, format="json").status_code == 401
    assert APIClient().post("/handy/auth/refresh/", {"refresh": "pas-un-jeton"}, format="json").status_code == 401


def test_logout_revokes_both_a_body_token_and_the_cookie_during_migration(awa):
    c = APIClient()
    cookie_token = login(c, cookie=True).cookies[COOKIE_NAME].value
    body_token = login(APIClient()).json()["refresh"]               # ex. jeton reçu après la double authentification
    c.post("/handy/auth/logout/", {"refresh": body_token}, format="json", HTTP_X_AUTH_TRANSPORT="cookie")
    for token in (cookie_token, body_token):
        assert APIClient().post("/handy/auth/refresh/", {"refresh": token}, format="json").status_code == 401

