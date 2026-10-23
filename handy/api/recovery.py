"""Récupération du compte par OTP (téléphone) : `/auth/password-reset/request/` et `/confirm/`.

Un seul mécanisme d'OTP (handy.models.OTPCode + handy.sms) : aucun code fictif, aucun contournement.
- `request` ne révèle jamais si un numéro est inscrit (réponse 202 identique) ; un fournisseur SMS
  indisponible renvoie 503 pour TOUS les numéros ;
- `confirm` exige un code valide, limite les essais (5 puis verrouillage), valide le nouveau mot de passe,
  invalide les sessions existantes (jetons de rafraîchissement) et remet `is_verified` à vrai : la
  possession du téléphone vient d'être prouvée par le code.
"""
import hashlib
import logging
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from handy import sms
from handy.models import OTPCode

logger = logging.getLogger(__name__)
User = get_user_model()

TTL_MINUTES = 10
RESEND_COOLDOWN_S = 60
MAX_PER_HOUR = 5
MAX_FAILURES = 5
PHONE_INVALID = "Numéro de téléphone invalide. Choisissez le pays puis saisissez le numéro national, par exemple 07 00 00 00 00 pour la Côte d’Ivoire."
CODE_INVALID = "Code invalide ou expiré."


def _error(detail, http_status):
    return Response({"detail": detail}, status=http_status)


def _key(kind: str, phone: str) -> str:
    return f"recovery:{kind}:{hashlib.sha256(phone.encode()).hexdigest()[:24]}"


def _phone_or_error(request):
    """Numéro saisi (international, ou national avec `phone_country`) → E.164 ; même règle que l'envoi des SMS."""
    try:
        return sms.normalize_msisdn(request.data.get("phone"), request.data.get("phone_country")), None
    except sms.SMSError:
        return None, _error(PHONE_INVALID, status.HTTP_400_BAD_REQUEST)


def _account(request, phone: str):
    """Compte actif du numéro, y compris enregistré sous sa forme d'avant libphonenumber."""
    from handy.phone import lookup_candidates

    forms = [phone, *lookup_candidates(request.data.get("phone"), request.data.get("phone_country"))]
    return User.objects.filter(phone__in=list(dict.fromkeys(forms)), is_active=True).first()


def _blacklist_sessions(user):
    """Révoque les jetons de rafraîchissement du compte (si l'application de liste noire est installée)."""
    try:
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
    except Exception:  # application non installée : rien à révoquer
        return
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([ScopedRateThrottle])
def password_reset_request(request):
    """POST {phone} -> envoie un code de récupération par SMS (202, identique que le compte existe ou non)."""
    phone, bad = _phone_or_error(request)
    if bad:
        return bad
    from antifraud import limits, sms_guard, turnstile
    from handy.security import client_ip

    ip = client_ip(request)
    if turnstile.check(request, ip) == "failed":
        return _error("Vérification anti-robot requise : rechargez la page et réessayez.", status.HTTP_400_BAD_REQUEST)
    try:
        sms.get_backend()  # fournisseur absent/mal configuré : 503 pour tous les numéros (aucune fuite)
    except sms.SMSNotConfigured as exc:
        logger.error("Récupération : fournisseur SMS indisponible — %s", exc)
        return _error("L'envoi de SMS n'est pas disponible pour le moment.", status.HTTP_503_SERVICE_UNAVAILABLE)

    # Délai, quota par numéro et garde anti-fraude (interrupteur, destination, quotas IP / numéro / global) appliqués
    # UNIFORMÉMENT, AVANT de savoir si le compte existe : même réponse dans les deux cas, aucune énumération possible.
    try:
        if not cache.add(_key("cool", phone), 1, timeout=RESEND_COOLDOWN_S):
            resp = _error(f"Patientez {RESEND_COOLDOWN_S} s avant de demander un nouveau code.",
                          status.HTTP_429_TOO_MANY_REQUESTS)
            resp["Retry-After"] = str(RESEND_COOLDOWN_S)
            return resp
        if not limits.hit(f"recovery_number:h:{limits.digest(phone)}", MAX_PER_HOUR, 3600)[0]:
            return _error("Trop de codes demandés. Réessayez dans une heure.", status.HTTP_429_TOO_MANY_REQUESTS)
    except limits.LimitUnavailable:
        return _error("L'envoi de SMS n'est pas disponible pour le moment.", status.HTTP_503_SERVICE_UNAVAILABLE)
    try:
        sms_guard.admit(phone, "otp_recovery", ip=ip)
    except sms.SMSBlocked as exc:
        resp = _error(str(exc), exc.http_status)
        if exc.retry_after:
            resp["Retry-After"] = str(exc.retry_after)
        return resp

    accepted = Response({"sent": True, "phone": sms.mask(phone), "expires_in": TTL_MINUTES * 60,
                         "resend_in": RESEND_COOLDOWN_S}, status=status.HTTP_202_ACCEPTED)
    user = _account(request, phone)
    if user is None:
        return accepted
    recent = OTPCode.objects.filter(user=user, purpose="recovery", created_at__gte=timezone.now() - timedelta(hours=1))
    if recent.count() >= MAX_PER_HOUR:  # défense en profondeur (compteur en base, multi-processus)
        return accepted
    OTPCode.objects.filter(user=user, purpose="recovery", used=False).update(used=True)
    otp = OTPCode.issue(user, purpose="recovery", ttl_minutes=TTL_MINUTES)
    try:
        sms.send_sms(user.phone, f"Tratra : code de récupération de votre compte {otp.code}. Valable {TTL_MINUTES} minutes.",
                     purpose="otp_recovery", ip=ip, user_id=user.pk, admitted=True)
    except sms.SMSError as exc:
        otp.used = True
        otp.save(update_fields=["used"])
        logger.warning("Code de récupération non envoyé (user=%s) : %s", user.pk, exc)
        return _error("Le SMS n'a pas pu être envoyé. Vérifiez votre numéro puis réessayez.",
                      status.HTTP_502_BAD_GATEWAY)
    return accepted


@api_view(["POST"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([ScopedRateThrottle])
def password_reset_confirm(request):
    """POST {phone, code, password} -> définit un nouveau mot de passe si le code est valide."""
    phone, bad = _phone_or_error(request)
    if bad:
        return bad
    code = str(request.data.get("code") or "").strip()
    password = request.data.get("password")
    from antifraud import limits

    fail_key = _key("fail", phone)
    try:
        failures = limits.attempt(fail_key, 600)      # essai compté AVANT la vérification : atomique, même en parallèle
    except limits.LimitUnavailable:
        return _error("La vérification est momentanément indisponible. Réessayez dans un instant.", status.HTTP_503_SERVICE_UNAVAILABLE)
    if failures > MAX_FAILURES:
        return _error("Trop d'essais. Demandez un nouveau code.", status.HTTP_429_TOO_MANY_REQUESTS)

    user = _account(request, phone)
    otp = (OTPCode.objects.filter(user=user, purpose="recovery", used=False).order_by("-created_at").first()
           if user else None)
    if not (user and otp and otp.is_valid() and secrets.compare_digest(otp.code, code)):
        if failures >= MAX_FAILURES and user:
            OTPCode.objects.filter(user=user, purpose="recovery", used=False).update(used=True)
            return _error("Code invalide. Trop d'essais : demandez un nouveau code.", status.HTTP_400_BAD_REQUEST)
        left = max(0, MAX_FAILURES - failures)
        return _error(f"{CODE_INVALID} Il vous reste {left} essai{'s' if left > 1 else ''}.",
                      status.HTTP_400_BAD_REQUEST)

    try:  # le code n'est consommé qu'une fois le mot de passe accepté
        validate_password(password or "", user=user)
    except DjangoValidationError as exc:
        limits.reset(fail_key)        # bon code, mot de passe refusé : ce n'est pas un essai de code raté
        return Response({"password": list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
    user.set_password(password)
    user.is_verified = True  # la possession du téléphone vient d'être prouvée par le code
    user.save(update_fields=["password", "is_verified"])
    OTPCode.objects.filter(user=user, purpose="recovery", used=False).update(used=True)
    limits.reset(fail_key)
    _blacklist_sessions(user)
    try:  # lève un éventuel verrouillage Axes (échecs de connexion antérieurs)
        from axes.utils import reset
        reset(username=user.get_username())
    except Exception:
        pass
    return Response({"reset": True})


password_reset_request.cls.throttle_scope = "recovery"
password_reset_confirm.cls.throttle_scope = "recovery"
