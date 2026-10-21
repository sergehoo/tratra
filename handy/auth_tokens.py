"""Sessions JWT « Se souvenir de moi » (mêmes jetons SimpleJWT, rotation et liste noire inchangées).

- Le jeton de rafraîchissement porte le choix de l'utilisateur (`rmb` : 1 = se souvenir, 0 = session seule). Sa durée en dépend
  (`JWT_REMEMBER_REFRESH_LIFETIME`, `JWT_SESSION_REFRESH_LIFETIME`) et la ROTATION la conserve (`SessionAwareRefreshToken.set_exp`).
  Les jetons émis avant cette évolution (sans `rmb`) gardent exactement leur durée d'origine : aucune session existante n'est coupée.
- Toutes les autres revendications (dont la preuve de double authentification `mfa_at`/`mfa_c`) sont recopiées telles quelles.
- Site web : le jeton de rafraîchissement peut voyager dans un cookie HttpOnly + Secure + SameSite=Lax limité aux routes
  `/handy/auth/` (en-tête `X-Auth-Transport: cookie`, qui impose aussi un pré-contrôle CORS : aucune origine étrangère ne peut s'en
  servir). « Se souvenir de moi » → cookie persistant jusqu'à l'expiration du jeton ; sinon cookie de session (fermeture du navigateur).
  L'application mobile garde le jeton dans le corps (stockage sécurisé du téléphone).
"""
import time
from datetime import timedelta
from typing import Optional

from django.conf import settings
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.utils import datetime_from_epoch

REMEMBER_CLAIM = "rmb"
COOKIE_NAME = "tratra_refresh"
TRANSPORT_HEADER = "HTTP_X_AUTH_TRANSPORT"


def remembered_lifetime() -> timedelta:
    return getattr(settings, "JWT_REMEMBER_REFRESH_LIFETIME", timedelta(days=30))


def session_lifetime() -> timedelta:
    return getattr(settings, "JWT_SESSION_REFRESH_LIFETIME", timedelta(hours=12))


def wants_remember(value) -> bool:
    """`remember_me` absent = coché (choix par défaut des écrans de connexion)."""
    if value is None or value == "":
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("0", "false", "no", "off", "non")


class SessionAwareRefreshToken(RefreshToken):
    """Jeton de rafraîchissement dont la durée suit le choix « se souvenir de moi », y compris à chaque rotation."""

    def set_exp(self, claim: str = "exp", from_time=None, lifetime: Optional[timedelta] = None) -> None:
        if lifetime is None and claim == "exp" and REMEMBER_CLAIM in self.payload:
            lifetime = remembered_lifetime() if self.payload[REMEMBER_CLAIM] else session_lifetime()
        super().set_exp(claim=claim, from_time=from_time, lifetime=lifetime)

    @property
    def remembered(self) -> bool:
        return bool(self.payload.get(REMEMBER_CLAIM, 1))


def apply_remember(token: RefreshToken, remember: bool) -> RefreshToken:
    """Fixe le choix et la durée d'un jeton qui vient d'être émis (connexion) ; la liste des jetons émis est mise à jour."""
    token[REMEMBER_CLAIM] = 1 if remember else 0
    token.set_exp(from_time=token.current_time, lifetime=remembered_lifetime() if remember else session_lifetime())
    OutstandingToken.objects.filter(jti=token[api_settings.JTI_CLAIM]).update(
        expires_at=datetime_from_epoch(token["exp"]), token=str(token))
    return token


# ═══ Transport du jeton par cookie (site web) ══════════════════════════════════════════════════════════════════════════

def cookie_path() -> str:
    return getattr(settings, "JWT_REFRESH_COOKIE_PATH", "/handy/auth/")


def wants_cookie(request) -> bool:
    return request.META.get(TRANSPORT_HEADER, "").strip().lower() == "cookie"


def set_refresh_cookie(response, refresh: str) -> None:
    token = SessionAwareRefreshToken(refresh, verify=False)
    max_age = max(0, int(token["exp"] - time.time())) if token.remembered else None   # None : cookie de session
    response.set_cookie(
        COOKIE_NAME, refresh, max_age=max_age, path=cookie_path(), domain=getattr(settings, "JWT_REFRESH_COOKIE_DOMAIN", None),
        secure=getattr(settings, "JWT_REFRESH_COOKIE_SECURE", not settings.DEBUG), httponly=True, samesite="Lax")


def clear_refresh_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, path=cookie_path(), domain=getattr(settings, "JWT_REFRESH_COOKIE_DOMAIN", None), samesite="Lax")


def refresh_from(request) -> Optional[str]:
    """Jeton de rafraîchissement de la requête : corps (application, anciennes sessions web) sinon cookie (site, avec l'en-tête)."""
    body = request.data.get("refresh") if hasattr(request.data, "get") else None
    if body:
        return str(body)
    if wants_cookie(request):
        return request.COOKIES.get(COOKIE_NAME) or None
    return None
