"""Garde des inscriptions publiques (POST /users/) : anti-robot puis limites atomiques et règles de motifs.

 - Turnstile pour le site (turnstile.py) ;
 - par IP (heure, jour), par appareil si l'application envoie son identifiant d'installation (`X-Tratra-Device`, UUID — simple
   limite supplémentaire : un robot peut le changer, d'où les autres règles), global par heure ;
 - motifs de « SMS pumping » observés : même nom complet répété (« Rita Kamal ») et numéros d'un même bloc de 1 000 (+225 01 15 98 1xx)
   inscrits en rafale.
Chaque décision est journalisée (`SignupLog`) avec l'IP : base du rapport des comptes suspects. Cache injoignable : l'inscription
passe (les SMS, eux, restent bloqués sans compteur fiable)."""
from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Optional

from django.conf import settings

from antifraud import limits, turnstile

logger = logging.getLogger(__name__)

HOUR, DAY = 3600, 86400
MSG_RATE = "Trop d’inscriptions depuis cette connexion. Réessayez plus tard."
MSG_BUSY = "Les inscriptions sont momentanément limitées. Réessayez dans quelques minutes."
MSG_CAPTCHA = "Vérification anti-robot requise : rechargez la page et réessayez."


@dataclass
class Refusal:
    reason: str
    message: str
    http_status: int = 429
    retry_after: Optional[int] = None


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


def device_id(request) -> str:
    raw = (request.META.get("HTTP_X_TRATRA_DEVICE") or "").strip()
    try:
        return limits.digest(str(uuid.UUID(raw)))
    except (ValueError, AttributeError):
        return ""


def context(request, data) -> Context:
    from handy.security import client_ip

    ip = client_ip(request)
    return Context(ip=ip, device=device_id(request), channel="web" if turnstile.is_browser(request) else "app",
                   captcha="", name_key=limits.digest(normalize_name(data.get("first_name", ""), data.get("last_name", ""))))


def check(request, data) -> tuple[Context, Optional[Refusal]]:
    """Décision AVANT la création du compte. `data` : champs validés (prénom, nom, téléphone E.164)."""
    ctx = context(request, data)
    ctx.captcha = turnstile.check(request, ctx.ip)
    if ctx.captcha == "failed":
        return ctx, Refusal("captcha", MSG_CAPTCHA, 400)
    rules = []
    if ctx.ip:
        ip_key = limits.digest(ctx.ip)
        rules += [(f"signup_ip:h:{ip_key}", _int("SIGNUP_PER_IP_HOURLY_LIMIT", 5), HOUR, MSG_RATE),
                  (f"signup_ip:d:{ip_key}", _int("SIGNUP_PER_IP_DAILY_LIMIT", 20), DAY, MSG_RATE)]
    if ctx.device:
        rules.append((f"signup_device:d:{ctx.device}", _int("SIGNUP_PER_DEVICE_DAILY_LIMIT", 3), DAY, MSG_RATE))
    name = normalize_name(data.get("first_name", ""), data.get("last_name", ""))
    if name:
        rules.append((f"signup_name:d:{ctx.name_key}", _int("SIGNUP_SAME_NAME_DAILY_LIMIT", 3), DAY, MSG_BUSY))
    block = phone_block(str(data.get("phone") or ""))
    if block:
        rules.append((f"signup_block:h:{limits.digest(block)}", _int("SIGNUP_PHONE_BLOCK_HOURLY_LIMIT", 3), HOUR, MSG_BUSY))
    rules.append(("signup_global:h", _int("SIGNUP_GLOBAL_HOURLY_LIMIT", 60), HOUR, MSG_BUSY))
    try:
        for name_, limit, window, message in rules:
            ok, _ = limits.hit(name_, limit, window)
            if not ok:
                return ctx, Refusal(name_.split(":")[0].replace("signup_", ""), message, 429, limits.retry_after(window))
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
