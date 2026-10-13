"""Chiffrement applicatif (Fernet) des captures biométriques : même si le stockage objet est exposé, les octets restent illisibles sans la clé."""
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class BiometricUnavailable(Exception):
    """Fonction non disponible (désactivée, mal configurée) : le message est destiné à l'utilisateur."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code, self.detail = code, detail


def _fernet() -> Fernet:
    key = getattr(settings, "BIOMETRIC_ENCRYPTION_KEY", "")
    if not key:
        raise BiometricUnavailable("not_configured", "La vérification faciale n'est pas configurée sur ce serveur.")
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError):
        raise BiometricUnavailable("not_configured", "La vérification faciale n'est pas configurée sur ce serveur.")


def encrypt(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt(blob: bytes) -> bytes:
    try:
        return _fernet().decrypt(blob)
    except InvalidToken:
        raise BiometricUnavailable("undecryptable", "Capture illisible (clé de chiffrement différente ou données altérées).")


def ensure_configured() -> None:
    _fernet()
