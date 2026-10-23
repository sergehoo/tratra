"""Cloudflare Turnstile (anti-robot) : vérification CÔTÉ SERVEUR du jeton produit par le widget du site.

Configuration :
  TURNSTILE_SECRET_KEY  clé secrète (serveur) ; vide = désactivé.
  TURNSTILE_MODE        « web » (défaut) : exigé pour les requêtes d'un navigateur (en-tête Origin d'un site autorisé) ;
                        « all » : exigé pour tous les clients (quand l'application mobile intégrera le widget) ; « off ».
Le jeton arrive dans le champ `turnstile_token` ou l'en-tête `X-Turnstile-Token`. Il est à usage unique et vérifié auprès de
Cloudflare avec l'IP du client ; Cloudflare injoignable = refus (jamais de contournement silencieux).
L'application mobile n'envoie pas d'en-tête Origin : elle reste soumise aux protections serveur (limites par IP, appareil, numéro,
global, règles de motifs) — qui s'appliquent d'ailleurs à TOUS les clients, un robot pouvant omettre l'en-tête Origin."""
from __future__ import annotations

import logging

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


def required(request) -> bool:
    if not secret() or mode() == "off":
        return False
    return mode() == "all" or is_browser(request)


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
