"""Cloudflare Turnstile (anti-robot) : vérification CÔTÉ SERVEUR du jeton produit par le widget du site.

Configuration :
  TURNSTILE_SECRET_KEY  clé secrète (serveur) ; vide = désactivé.
  TURNSTILE_MODE        « web » (défaut) : exigé pour les requêtes d'un navigateur (en-tête Origin d'un site autorisé) ;
                        « all » : exigé pour tous les clients (quand l'application mobile intégrera le widget) ; « off ».
  TURNSTILE_UNKNOWN_CLIENTS  (vrai par défaut) en mode « web », exigé AUSSI des clients inconnus : ni site autorisé, ni
                        identifiant d'installation de l'application (`X-Tratra-Device`). C'est le cas d'un script qui appelle
                        l'API directement (attaque du 23 oct. 2026 : sans en-tête Origin, il passait pour l'application).
Le jeton arrive dans le champ `turnstile_token` ou l'en-tête `X-Turnstile-Token`. Il est à usage unique et vérifié auprès de
Cloudflare avec l'IP du client ; Cloudflare injoignable = refus (jamais de contournement silencieux).
L'application mobile n'affiche pas encore le widget : elle s'identifie par son identifiant d'installation et reste soumise aux
protections serveur (limites par IP, appareil, numéro, plage, global). Ce n'est qu'une présomption (un robot peut imiter l'en-tête) :
la vraie preuve viendra du widget dans l'application (mode « all ») ou d'une attestation de l'appareil (Play Integrity)."""
from __future__ import annotations

import logging
import uuid

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def secret() -> str:
    return str(getattr(settings, "TURNSTILE_SECRET_KEY", "") or "").strip()


def mode() -> str:
    value = str(getattr(settings, "TURNSTILE_MODE", "web") or "web").strip().lower()
    return value if value in ("off", "web", "all") else "web"


def is_browser(request) -> bool:
    """Requête d'un navigateur sur le site (en-tête Origin d'une origine autorisée)."""
    origin = (request.META.get("HTTP_ORIGIN") or "").rstrip("/")
    allowed = [o.rstrip("/") for o in getattr(settings, "CORS_ALLOWED_ORIGINS", [])]
    return bool(origin) and origin in allowed


def installation_id(request) -> str:
    """Identifiant d'installation envoyé par l'application (`X-Tratra-Device`, UUID normalisé) ; vide s'il manque ou est invalide."""
    raw = (request.META.get("HTTP_X_TRATRA_DEVICE") or "").strip()
    try:
        return str(uuid.UUID(raw))
    except (ValueError, AttributeError):
        return ""


def client_kind(request) -> str:
    """« web » (site autorisé), « app » (identifiant d'installation) ou « unknown » (ni l'un ni l'autre : script, robot)."""
    if is_browser(request):
        return "web"
    return "app" if installation_id(request) else "unknown"


def required(request) -> bool:
    if not secret() or mode() == "off":
        return False
    if mode() == "all":
        return True
    kind = client_kind(request)
    return kind == "web" or (kind == "unknown" and bool(getattr(settings, "TURNSTILE_UNKNOWN_CLIENTS", True)))


def token_of(request) -> str:
    data = getattr(request, "data", {}) or {}
    raw = data.get("turnstile_token") if hasattr(data, "get") else None
    return str(raw or request.META.get("HTTP_X_TURNSTILE_TOKEN") or "").strip()


def verify(token: str, ip: str = "") -> bool:
    if not token or len(token) > 2048:
        return False
    try:
        r = requests.post(VERIFY_URL, data={"secret": secret(), "response": token, **({"remoteip": ip} if ip else {})}, timeout=5)
        return bool(r.status_code == 200 and r.json().get("success") is True)
    except Exception as exc:  # noqa: BLE001 - Cloudflare injoignable : refus
        logger.warning("Turnstile injoignable (%s) : vérification refusée.", type(exc).__name__)
        return False


def check(request, ip: str = "") -> str:
    """« off » (non exigé), « ok » (jeton valide) ou « failed » (absent ou refusé)."""
    if not required(request):
        return "off"
    return "ok" if verify(token_of(request), ip) else "failed"
