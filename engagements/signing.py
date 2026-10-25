"""Signature numérique des documents de contrat par la PLATEFORME (Ed25519) — scellement et vérification publique.

 - Les clés sont générées et gardées CÔTÉ SERVEUR : la clé privée n'est stockée que chiffrée (Fernet, clé dérivée de
   CONTRACT_SIGNING_KEK, à défaut de SECRET_KEY), n'est jamais renvoyée par une API ni écrite dans un journal.
 - Une seule clé active à la fois. Rotation : la nouvelle clé signe désormais, l'ancienne passe « retirée » et continue de vérifier
   les documents qu'elle a signés. Révocation (compromission) : les signatures de cette clé sont signalées « clé révoquée ».
 - Les clés PUBLIQUES sont publiées (`/handy/public/contracts/keys/`) : n'importe qui peut vérifier une signature hors de Tratra.
 - Gestion réservée au personnel ayant « contracts.keys » (Back-Office) ou à la commande `manage.py contract_keys`.

Ce scellement prouve l'origine (Tratra) et l'intégrité du document ; ce n'est PAS une signature électronique qualifiée des parties."""
import base64
import hashlib
import json
import secrets
from typing import Dict, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

ALGORITHM = "Ed25519"


class SigningError(Exception):
    pass


def _fernet() -> Fernet:
    material = getattr(settings, "CONTRACT_SIGNING_KEK", "") or settings.SECRET_KEY
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"tratra-contract-signing:{material}".encode()).digest()))


def canonical(payload: Dict) -> bytes:
    """Sérialisation canonique (clés triées, sans espace, UTF-8) : ce sont ces octets exacts qui sont signés."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def generate_key(*, actor=None):
    """Nouvelle clé ACTIVE ; la précédente devient « retirée » (elle vérifie encore ses documents). Atomique."""
    from engagements.models import SigningKey

    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    private_raw = private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    now = timezone.now()
    with transaction.atomic():
        SigningKey.objects.select_for_update().filter(status=SigningKey.ACTIVE).update(status=SigningKey.RETIRED, retired_at=now)
        key = SigningKey.objects.create(kid=f"ctr-{now:%Y%m%d}-{secrets.token_hex(4)}", algorithm=ALGORITHM, public_key=_b64(public_raw),
                                        private_key_encrypted=_fernet().encrypt(private_raw).decode("ascii"), status=SigningKey.ACTIVE,
                                        created_by=actor)
    return key


def active_key():
    """Clé active ; la première est créée à la première signature (aucune clé n'est jamais livrée avec le code)."""
    from engagements.models import SigningKey

    key = SigningKey.objects.filter(status=SigningKey.ACTIVE).first()
    if key is not None:
        return key
    try:
        return generate_key()
    except IntegrityError:          # création concurrente : l'autre a gagné
        return SigningKey.objects.get(status=SigningKey.ACTIVE)


def revoke_key(kid: str, *, actor=None, reason: str = ""):
    from engagements.models import SigningKey

    with transaction.atomic():
        key = SigningKey.objects.select_for_update().filter(kid=kid).first()
        if key is None:
            raise SigningError("Clé introuvable.")
        if key.status != SigningKey.REVOKED:
            was_active = key.status == SigningKey.ACTIVE
            key.status, key.revoked_at, key.revoked_reason, key.revoked_by = SigningKey.REVOKED, timezone.now(), reason[:300], actor
            key.save(update_fields=["status", "revoked_at", "revoked_reason", "revoked_by"])
            if was_active:
                generate_key(actor=actor)       # jamais sans clé active : les nouveaux documents sont signés par une clé saine
    return key


def sign(payload: Dict, key=None) -> Tuple[str, str]:
    """(identifiant de clé, signature base64) de la charge utile canonique, avec la clé active — ou la clé `key` déjà lue (celle dont
    l'identifiant est imprimé dans le document) : même algorithme, même charge utile."""
    key = key or active_key()
    private = Ed25519PrivateKey.from_private_bytes(_fernet().decrypt(key.private_key_encrypted.encode("ascii")))
    return key.kid, _b64(private.sign(canonical(payload)))


def verify(payload: Dict, signature_b64: str, kid: str) -> Dict:
    """{"valid": bool, "kid", "algorithm", "key_status"} — vérification avec la clé PUBLIQUE uniquement."""
    from engagements.models import SigningKey

    key: Optional[SigningKey] = SigningKey.objects.filter(kid=kid).first()
    out = {"valid": False, "kid": kid, "algorithm": ALGORITHM, "key_status": key.status if key else "unknown"}
    if key is None:
        return out
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key.public_key)).verify(base64.b64decode(signature_b64), canonical(payload))
        out["valid"] = True
    except (InvalidSignature, ValueError, TypeError):
        pass
    return out


def public_keys():
    from engagements.models import SigningKey

    return [{"kid": k.kid, "algorithm": k.algorithm, "public_key": k.public_key, "status": k.status, "created_at": k.created_at,
             "retired_at": k.retired_at, "revoked_at": k.revoked_at} for k in SigningKey.objects.order_by("-created_at")]
