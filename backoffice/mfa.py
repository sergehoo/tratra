"""Double authentification (TOTP, RFC 6238) des comptes d'administration.

 * Concerne les comptes `is_staff` : Back-Office (`/handy/backoffice/…`), droits « personnel » de l'ancienne API et `/admin/`.
 * Le secret est chiffré au repos (Fernet) ; les codes de secours sont stockés hachés ; un code TOTP ne sert qu'UNE fois
   (anti-rejeu) ; 5 échecs verrouillent la vérification 15 minutes ; chaque événement sensible est journalisé.
 * La preuve de vérification voyage dans le jeton d'accès (revendications `mfa_at`, `mfa_c`) : une réinitialisation de
   l'appareil invalide immédiatement tous les jetons déjà vérifiés ; au-delà de `BACKOFFICE_MFA_MAX_AGE` il faut re-vérifier.
 * `BACKOFFICE_MFA_REQUIRED` : exigé en production par défaut ; désactivable seulement explicitement (jamais par oubli)."""
import base64
import hashlib
import hmac
import secrets
import time
from datetime import timedelta
from io import BytesIO
from typing import Optional, Tuple
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django_otp.oath import TOTP
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken

from backoffice.models import StaffMFA
from trust.models import audit

BACKUP_CODES = 10
TOLERANCE = 1                       # ± un pas de 30 s (dérive d'horloge)
MFA_CODE_REQUIRED = "mfa_required"
MFA_CODE_ENROLL = "mfa_enrollment_required"


def required() -> bool:
    return bool(getattr(settings, "BACKOFFICE_MFA_REQUIRED", False))


def max_age() -> int:
    return int(getattr(settings, "BACKOFFICE_MFA_MAX_AGE", 12 * 3600))


# ── Secret chiffré ──────────────────────────────────────────────────────────────────────────────────────────────────

def _fernet() -> Fernet:
    material = getattr(settings, "MFA_ENCRYPTION_KEY", "") or settings.SECRET_KEY
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"tratra-mfa:{material}".encode()).digest()))


def _seal(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def _open(token: str) -> Optional[str]:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None          # clé changée : l'appareil doit être ré-enrôlé


def _hash_code(code: str) -> str:
    pepper = (getattr(settings, "MFA_ENCRYPTION_KEY", "") or settings.SECRET_KEY).encode()
    return hmac.new(pepper, code.strip().lower().replace("-", "").encode(), hashlib.sha256).hexdigest()


def _totp(secret: str) -> TOTP:
    return TOTP(base64.b32decode(secret), step=30, digits=6)


def provisioning_uri(user, secret: str) -> str:
    issuer = getattr(settings, "MFA_ISSUER", "Tratra")
    label = quote(f"{issuer}:{user.get_username()}", safe=":")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"


def qr_svg_data_uri(uri: str) -> str:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buf = BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


# ── État ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def confirmed_device(user) -> Optional[StaffMFA]:
    return StaffMFA.objects.filter(user=user, confirmed_at__isnull=False).first()


def status(user) -> dict:
    dev = confirmed_device(user)
    return {"required": required(), "enrolled": dev is not None, "verified": satisfied(user), "backup_codes_remaining": len(dev.backup_hashes) if dev else 0,
            "locked_until": dev.locked_until if dev and dev.locked_until and dev.locked_until > timezone.now() else None}


def satisfied(user) -> bool:
    """MFA non exigée, compte hors personnel, ou jeton de la requête vérifié."""
    if not required() or not (getattr(user, "is_authenticated", False) and getattr(user, "is_staff", False)):
        return True
    return bool(getattr(user, "_mfa_ok", False))


def denial(user) -> dict:
    enrolled = confirmed_device(user) is not None
    return {"code": MFA_CODE_REQUIRED if enrolled else MFA_CODE_ENROLL,
            "detail": ("Vérification en deux étapes requise : saisissez le code de votre application d'authentification." if enrolled
                       else "Double authentification obligatoire pour les comptes d'administration : activez-la avant de continuer.")}


# ── Authentification JWT : porte la preuve MFA sur l'utilisateur de la requête ───────────────────────────────────────

class MFAJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        user._mfa_ok = _token_proves_mfa(user, token)
        return user, token


def _token_proves_mfa(user, token) -> bool:
    if not getattr(user, "is_staff", False):
        return False
    try:
        at, ref = int(token.get("mfa_at", 0)), int(token.get("mfa_c", 0))
    except (TypeError, ValueError):
        return False
    if not at or time.time() - at > max_age():
        return False
    dev = confirmed_device(user)
    return bool(dev and int(dev.confirmed_at.timestamp()) == ref)


def issue_tokens(user) -> dict:
    """Nouveaux jetons portant la preuve de vérification (après un code valide)."""
    dev = confirmed_device(user)
    refresh = RefreshToken.for_user(user)
    refresh["mfa_at"] = int(time.time())
    refresh["mfa_c"] = int(dev.confirmed_at.timestamp()) if dev else 0
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


# ── Enrôlement ──────────────────────────────────────────────────────────────────────────────────────────────────────

class MFAError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@transaction.atomic
def begin_enrollment(user) -> dict:
    existing = StaffMFA.objects.select_for_update().filter(user=user).first()
    if existing is not None and existing.confirmed_at is not None:
        raise MFAError("already_enrolled", "La double authentification est déjà activée. Demandez sa réinitialisation à un super administrateur.", 409)
    secret = base64.b32encode(secrets.token_bytes(20)).decode()
    if existing is None:
        StaffMFA.objects.create(user=user, secret_enc=_seal(secret))
    else:
        existing.secret_enc, existing.failed_attempts, existing.locked_until = _seal(secret), 0, None
        existing.save(update_fields=["secret_enc", "failed_attempts", "locked_until", "updated_at"])
    uri = provisioning_uri(user, secret)
    return {"secret": secret, "otpauth_uri": uri, "qr": qr_svg_data_uri(uri), "issuer": getattr(settings, "MFA_ISSUER", "Tratra")}


def _locked(dev: StaffMFA) -> Optional["MFAError"]:
    if dev.locked_until and dev.locked_until > timezone.now():
        return MFAError("mfa_locked", "Trop d'essais : vérification verrouillée quelques minutes.", 429)
    return None


def _record_failure(dev: StaffMFA, user, kind: str) -> None:
    dev.failed_attempts += 1
    limit = int(getattr(settings, "MFA_MAX_FAILURES", 5))
    if dev.failed_attempts >= limit:
        dev.locked_until = timezone.now() + timedelta(seconds=int(getattr(settings, "MFA_LOCK_SECONDS", 900)))
        dev.failed_attempts = 0
        audit("backoffice.mfa.locked", actor=user, target=user, kind=kind)
    dev.save(update_fields=["failed_attempts", "locked_until", "updated_at"])
    audit("backoffice.mfa.failed", actor=user, target=user, kind=kind)


def _verify_totp(dev: StaffMFA, code: str) -> bool:
    secret = _open(dev.secret_enc)
    if secret is None or not code.isdigit() or len(code) != 6:
        return False
    totp = _totp(secret)
    min_t = (dev.last_used_step + 1) if dev.last_used_step is not None else None       # un code ne sert qu'une fois
    if totp.verify(int(code), tolerance=TOLERANCE, min_t=min_t):
        dev.last_used_step = totp.t()
        return True
    return False


def _new_backup_codes() -> Tuple[list, list]:
    plain = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(BACKUP_CODES)]
    return plain, [_hash_code(c) for c in plain]


def confirm_enrollment(user, code: str) -> dict:
    # Les échecs (compteur, verrouillage) doivent être VALIDÉS même si l'appel se solde par une erreur : on lève après la transaction.
    error: Optional[MFAError] = None
    with transaction.atomic():
        dev = StaffMFA.objects.select_for_update().filter(user=user).first()
        if dev is None or dev.confirmed_at is not None:
            error = MFAError("not_pending", "Aucune activation en cours : recommencez la configuration.", 409)
        elif (error := _locked(dev)) is None:
            if _verify_totp(dev, (code or "").strip()):
                plain, hashed = _new_backup_codes()
                dev.confirmed_at, dev.backup_hashes, dev.failed_attempts, dev.locked_until = timezone.now(), hashed, 0, None
                dev.save()
                audit("backoffice.mfa.enrolled", actor=user, target=user)
            else:
                _record_failure(dev, user, "enroll")
                error = MFAError("invalid_code", "Code incorrect. Vérifiez l'heure de votre téléphone et réessayez.", 400)
    if error is not None:
        raise error
    return {**issue_tokens(user), "backup_codes": plain}


def verify(user, *, code: str = "", backup_code: str = "") -> dict:
    error: Optional[MFAError] = None
    with transaction.atomic():
        dev = StaffMFA.objects.select_for_update().filter(user=user, confirmed_at__isnull=False).first()
        if dev is None:
            error = MFAError(MFA_CODE_ENROLL, "Double authentification non activée pour ce compte.", 409)
        elif (error := _locked(dev)) is None:
            ok, kind = False, "totp"
            if backup_code.strip():
                kind, digest = "backup", _hash_code(backup_code)
                match = next((h for h in dev.backup_hashes if hmac.compare_digest(h, digest)), None)
                if match is not None:
                    dev.backup_hashes = [h for h in dev.backup_hashes if h != match]
                    ok = True
            else:
                ok = _verify_totp(dev, (code or "").strip())
            if ok:
                dev.failed_attempts, dev.locked_until = 0, None
                dev.save()
                audit("backoffice.mfa.verified", actor=user, target=user, kind=kind, backup_codes_left=len(dev.backup_hashes))
            else:
                _record_failure(dev, user, kind)
                error = MFAError("invalid_code", "Code incorrect ou déjà utilisé.", 400)
    if error is not None:
        raise error
    return issue_tokens(user)


@transaction.atomic
def reset(user, *, by, reason: str) -> bool:
    """Réinitialisation par un super administrateur (appareil perdu) : l'appareil est supprimé, les jetons vérifiés s'invalident."""
    deleted, _ = StaffMFA.objects.filter(user=user).delete()
    audit("backoffice.mfa.reset", actor=by, target=user, reason=reason[:300], had_device=bool(deleted))
    return bool(deleted)
