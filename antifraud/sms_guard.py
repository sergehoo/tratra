"""Garde des envois de SMS : AUCUN SMS ne part sans passer ici (handy.sms.send_sms).

Ordre des contrôles (le premier refus arrête tout, rien n'est dépensé) :
 1. interrupteurs : `SMS_ENABLED` (tous les SMS) puis un interrupteur par usage — `SMS_OTP_SIGNUP_ENABLED` (codes de vérification
    à l'inscription), `SMS_RECOVERY_ENABLED` (récupération de compte), `SMS_ALERTS_ENABLED` (alertes de service) ;
 2. destination : indicatif autorisé (`SMS_ALLOWED_COUNTRY_CODES`, 225 par défaut) et numéro MOBILE (jamais surtaxé, partagé,
    gratuit, VoIP ou spécial — vecteurs classiques de « SMS pumping ») ;
 3. quotas atomiques (Redis) : par IP, par numéro, par compte, puis global horaire et journalier — le global n'est consommé que
    par un envoi qui a passé tous les autres contrôles ;
 4. journal : chaque tentative (envoyée, bloquée, en échec) dans `SmsLog`, sans texte ni code, numéro masqué + empreinte.
Cache injoignable : refus (jamais de dépense sans compteur fiable). Alerte (journal critique + e-mail aux administrateurs) quand
le quota global atteint `SMS_ALERT_RATIO` puis quand il est épuisé, une fois par fenêtre."""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.core.cache import cache

from antifraud import limits

logger = logging.getLogger(__name__)

HOUR, DAY = 3600, 86400
SWITCHES = {"otp_signup": "SMS_OTP_SIGNUP_ENABLED", "otp_recovery": "SMS_RECOVERY_ENABLED", "alert": "SMS_ALERTS_ENABLED"}

MSG_SUSPENDED = "L’envoi de codes par SMS est momentanément suspendu. Réessayez plus tard."
MSG_DESTINATION = "Ce numéro ne peut pas recevoir de code par SMS."
MSG_QUOTA = "Trop de demandes de code. Réessayez plus tard."


@dataclass
class Verdict:
    reason: str
    http_status: int
    message: str
    retry_after: Optional[int] = None


def _int(name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool = True) -> bool:
    value = getattr(settings, name, default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def number_hash(number: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), (number or "").encode(), hashlib.sha256).hexdigest()


def country_code(number: str) -> str:
    try:
        import phonenumbers

        return str(phonenumbers.parse(number, None).country_code)
    except Exception:  # noqa: BLE001
        return ""


def destination_issue(number: str) -> Optional[str]:
    """Raison du refus de la destination, ou None. Indicatif hors liste ou numéro non mobile."""
    import phonenumbers
    from phonenumbers import PhoneNumberType as T

    allowed = [c.strip().lstrip("+") for c in str(getattr(settings, "SMS_ALLOWED_COUNTRY_CODES", "225")).split(",") if c.strip()]
    try:
        parsed = phonenumbers.parse(number, None)
    except Exception:  # noqa: BLE001
        return "destination_invalid"
    if allowed and str(parsed.country_code) not in allowed:
        return "destination_country"
    if not phonenumbers.is_valid_number(parsed):
        # Comptes ivoiriens d'avant la numérotation à 10 chiffres (2021) : +225 + 8 chiffres, mobiles 0x/4x/5x/6x/7x. Jamais
        # accepté à l'inscription (numéro strict) : seulement pour les comptes historiques (connexion, récupération).
        national = phonenumbers.national_significant_number(parsed)   # zéro initial conservé (« 07123456 »)
        if parsed.country_code == 225 and len(national) == 8 and national[0] in "0124567":
            return None
        return "destination_invalid"
    if phonenumbers.number_type(parsed) not in (T.MOBILE, T.FIXED_LINE_OR_MOBILE):
        return "destination_type"
    return None


def log(number: str, purpose: str, status: str, *, reason: str = "", provider: str = "", ip: Optional[str] = None,
        user_id: Optional[int] = None) -> None:
    from antifraud.models import SmsLog
    from handy.sms import mask

    try:
        SmsLog.objects.create(purpose=purpose, status=status, reason=reason[:40], provider=provider[:40], ip=ip or None,
                              user_id=user_id, number_masked=mask(number), number_hash=number_hash(number),
                              country_code=country_code(number))
    except Exception:  # noqa: BLE001 - le journal ne doit jamais faire échouer la protection elle-même
        logger.warning("Journal SMS non enregistré.", exc_info=True)


def _alert(kind: str, total: int, limit: int, label: str, window: int) -> None:
    """Une alerte par fenêtre et par niveau (seuil, épuisement) : journal critique (Sentry) + e-mail aux administrateurs."""
    try:
        if not cache.add(f"sms:alert:{kind}:{window}:{int(time.time() // window)}", 1, timeout=window + 60):
            return
    except Exception:  # noqa: BLE001 - sans cache, l'alerte part quand même
        pass
    text = (f"Tratra SMS : {total}/{limit} SMS sur la {label} en cours"
            + (" — QUOTA ATTEINT, envois bloqués." if kind == "exhausted" else " — seuil d'alerte atteint."))
    logger.critical(text)
    try:
        from django.core.mail import mail_admins

        mail_admins("Alerte SMS Tratra", text, fail_silently=True)
    except Exception:  # noqa: BLE001
        pass


def _quota(name: str, limit: int, window: int) -> Optional[Verdict]:
    ok, _ = limits.hit(name, limit, window)
    return None if ok else Verdict(name.split(":")[0], 429, MSG_QUOTA, limits.retry_after(window))


def public_code(reason: str) -> str:
    """Code renvoyé au client. Le quota exact (IP, numéro, compte, global) reste dans `SmsLog` : le révéler montrerait à un robot
    quelle limite contourner."""
    if reason in ("kill_switch", "limits_unavailable"):
        return "sms_suspended"
    if reason.startswith("destination"):
        return "sms_destination"
    return "sms_limited"


def check(number: str, purpose: str, *, ip: Optional[str] = None, user_id: Optional[int] = None) -> Optional[Verdict]:
    """Décision d'envoi (et consommation des quotas si autorisé jusqu'au global). None = envoi autorisé."""
    if not _bool("SMS_ENABLED") or not _bool(SWITCHES.get(purpose, "SMS_ENABLED")):
        return Verdict("kill_switch", 503, MSG_SUSPENDED)
    issue = destination_issue(number)
    if issue:
        return Verdict(issue, 400, MSG_DESTINATION)
    digest = limits.digest(number)
    try:
        rules = []
        if ip:
            ip_key = limits.digest(ip)
            rules += [(f"quota_ip:h:{ip_key}", _int("SMS_PER_IP_HOURLY_LIMIT", 5), HOUR),
                      (f"quota_ip:d:{ip_key}", _int("SMS_PER_IP_DAILY_LIMIT", 15), DAY)]
        rules += [(f"quota_number:h:{digest}", _int("SMS_PER_NUMBER_HOURLY_LIMIT", 3), HOUR),
                  (f"quota_number:d:{digest}", _int("SMS_PER_NUMBER_DAILY_LIMIT", 6), DAY)]
        if user_id:
            rules.append((f"quota_user:d:{user_id}", _int("SMS_PER_USER_DAILY_LIMIT", 8), DAY))
        for name, limit, window in rules:
            verdict = _quota(name, limit, window)
            if verdict:
                return verdict
        ratio = float(getattr(settings, "SMS_ALERT_RATIO", 0.8) or 0.8)
        for window, label, setting, default in ((HOUR, "heure", "SMS_GLOBAL_HOURLY_LIMIT", 30), (DAY, "journée", "SMS_GLOBAL_DAILY_LIMIT", 150)):
            limit = _int(setting, default)
            ok, total = limits.hit(f"quota_global:{window}", limit, window)
            if not ok:
                _alert("exhausted", total, limit, label, window)
                return Verdict("quota_global", 429, MSG_QUOTA, limits.retry_after(window))
            if limit > 0 and total >= ratio * limit:
                _alert("threshold", total, limit, label, window)
    except limits.LimitUnavailable:
        return Verdict("limits_unavailable", 503, MSG_SUSPENDED)
    return None


def admit(number: str, purpose: str, *, ip: Optional[str] = None, user_id: Optional[int] = None) -> None:
    """Autorise l'envoi ou lève handy.sms.SMSBlocked (tentative bloquée journalisée)."""
    from handy.sms import SMSBlocked

    verdict = check(number, purpose, ip=ip, user_id=user_id)
    if verdict is None:
        return
    log(number, purpose, "blocked", reason=verdict.reason, ip=ip, user_id=user_id)
    if verdict.reason.startswith("quota") or verdict.reason == "kill_switch":
        logger.warning("SMS %s bloqué : %s.", purpose, verdict.reason)
    raise SMSBlocked(verdict.message, reason=verdict.reason, http_status=verdict.http_status, retry_after=verdict.retry_after)
