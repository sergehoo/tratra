"""Garde des inscriptions publiques (POST /users/) : interrupteur, anti-robot, puis limites atomiques et règles de motifs.

 - `SIGNUP_ENABLED` faux : inscriptions publiques suspendues (attaque en cours) ;
 - Turnstile pour le site ET pour les clients inconnus (ni site, ni application : script appelant l'API) — turnstile.py ;
 - par IP (heure, jour), par appareil si l'application envoie son identifiant d'installation (`X-Tratra-Device`, UUID — simple
   limite supplémentaire : un robot peut le changer, d'où les autres règles), global par heure ;
 - motifs de « SMS pumping » observés : même nom complet répété (« Rita Kamal »), numéros d'un même bloc de 1 000
   (+225 01 15 98 1xx) inscrits en rafale, puis (2ᵉ vague, noms aléatoires, un compte toutes les ~16 min depuis des connexions
   ivoiriennes différentes) numéros d'une même plage de 100 000 (+225 07 59 8x xx xx).
Le client ne reçoit qu'un code générique (`signup_limited`) : la règle exacte reste dans le journal, pour ne pas montrer au robot
quoi contourner (la 2ᵉ vague a changé de nom, de bloc et de rythme juste après les refus). Chaque décision est journalisée
(`SignupLog`) avec l'IP et le type de client : base du rapport des comptes suspects. Cache injoignable : l'inscription passe (les
SMS, eux, restent bloqués sans compteur fiable)."""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from django.conf import settings

from antifraud import limits, turnstile

logger = logging.getLogger(__name__)

HOUR, DAY = 3600, 86400
MSG_BUSY = "Les inscriptions sont momentanément limitées. Réessayez plus tard."
MSG_CLOSED = "Les inscriptions sont momentanément suspendues. Réessayez plus tard."
MSG_CAPTCHA = "Vérification anti-robot requise : rechargez la page et réessayez."


@dataclass
class Refusal:
    reason: str
    message: str
    http_status: int = 429
    retry_after: Optional[int] = None

    @property
    def public_code(self) -> str:
        """Code renvoyé au client : anti-robot et suspension sont explicites (l'utilisateur doit agir ou patienter) ; toute limite
        devient « signup_limited », sans dire laquelle."""
        return f"signup_{self.reason}" if self.reason in ("captcha", "closed") else "signup_limited"


@dataclass
class Context:
    ip: str
    device: str
    channel: str
    captcha: str
    name_key: str


def _int(name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def normalize_name(first: str, last: str) -> str:
    raw = f"{first or ''} {last or ''}".strip().lower()
    raw = "".join(c for c in unicodedata.normalize("NFKD", raw) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", raw).strip()


def phone_block(e164: str) -> str:
    """Bloc de 1 000 numéros (sans les 3 derniers chiffres) : « +2250115981 »."""
    digits = re.sub(r"\D", "", e164 or "")
    return digits[:-3] if len(digits) > 6 else ""


def phone_range(e164: str) -> str:
    """Plage de 100 000 numéros (sans les 5 derniers chiffres) : « +22507598 »."""
    digits = re.sub(r"\D", "", e164 or "")
    return digits[:-5] if len(digits) > 8 else ""


def device_id(request) -> str:
    raw = turnstile.installation_id(request)
    return limits.digest(raw) if raw else ""


def context(request, data) -> Context:
    from handy.security import client_ip

    ip = client_ip(request)
    return Context(ip=ip, device=device_id(request), channel=turnstile.client_kind(request),
                   captcha="", name_key=limits.digest(normalize_name(data.get("first_name", ""), data.get("last_name", ""))))


def check(request, data) -> tuple[Context, Optional[Refusal]]:
    """Décision AVANT la création du compte. `data` : champs validés (prénom, nom, téléphone E.164)."""
    ctx = context(request, data)
    if not getattr(settings, "SIGNUP_ENABLED", True):
        return ctx, Refusal("closed", MSG_CLOSED, 503)
    ctx.captcha = turnstile.check(request, ctx.ip)
    if ctx.captcha == "failed":
        return ctx, Refusal("captcha", MSG_CAPTCHA, 400)
    rules = []
    if ctx.ip:
        ip_key = limits.digest(ctx.ip)
        rules += [(f"signup_ip:h:{ip_key}", _int("SIGNUP_PER_IP_HOURLY_LIMIT", 5), HOUR),
                  (f"signup_ip:d:{ip_key}", _int("SIGNUP_PER_IP_DAILY_LIMIT", 20), DAY)]
    if ctx.device:
        rules.append((f"signup_device:d:{ctx.device}", _int("SIGNUP_PER_DEVICE_DAILY_LIMIT", 3), DAY))
    name = normalize_name(data.get("first_name", ""), data.get("last_name", ""))
    if name:
        rules.append((f"signup_name:d:{ctx.name_key}", _int("SIGNUP_SAME_NAME_DAILY_LIMIT", 3), DAY))
    phone = str(data.get("phone") or "")
    if phone_block(phone):
        rules.append((f"signup_block:h:{limits.digest(phone_block(phone))}", _int("SIGNUP_PHONE_BLOCK_HOURLY_LIMIT", 3), HOUR))
    if phone_range(phone):
        rules.append((f"signup_range:d:{limits.digest(phone_range(phone))}", _int("SIGNUP_PHONE_RANGE_DAILY_LIMIT", 5), DAY))
    rules.append(("signup_global:h", _int("SIGNUP_GLOBAL_HOURLY_LIMIT", 60), HOUR))
    try:
        for name_, limit, window in rules:
            ok, _ = limits.hit(name_, limit, window)
            if not ok:
                return ctx, Refusal(name_.split(":")[0].replace("signup_", ""), MSG_BUSY, 429, limits.retry_after(window))
    except limits.LimitUnavailable:
        logger.error("Limites d'inscription indisponibles (cache) : inscription acceptée, SMS toujours protégés.")
    return ctx, None


def record(ctx: Context, *, user=None, refusal: Optional[Refusal] = None) -> None:
    from antifraud.models import SignupLog

    try:
        SignupLog.objects.create(user=user, ip=ctx.ip or None, device=ctx.device, channel=ctx.channel, captcha=ctx.captcha or "off",
                                 accepted=refusal is None, reason=refusal.reason if refusal else "", name_key=ctx.name_key)
    except Exception:  # noqa: BLE001
        logger.warning("Journal d'inscription non enregistré.", exc_info=True)
