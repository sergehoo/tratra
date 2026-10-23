"""Liens des applications mobiles sur les stores officiels (badges du site).

Un lien n'est accepté que s'il pointe EXACTEMENT vers la fiche d'une application sur Google Play ou l'App Store : HTTPS, hôte
officiel exact (ni sous-domaine piégé, ni identifiant `user@hôte`, ni port), chemin de fiche reconnu. Il est ensuite réécrit sous
sa forme canonique : les paramètres inconnus et le fragment sont retirés, si bien qu'aucun paramètre de redirection ne peut
voyager avec lui. La même fonction sert à l'administration (validation à l'enregistrement) et à l'API publique (contrôle à la
lecture : une ligne modifiée hors administration n'est jamais exposée).
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit

from django.core.exceptions import ValidationError

PLAY_HOST = "play.google.com"
PLAY_PATH = "/store/apps/details"
APPLE_HOST = "apps.apple.com"

_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
_LOCALE = re.compile(r"^[A-Za-z]{2,3}([_-][A-Za-z]{2})?$")
# /app/id123, /fr/app/id123, /fr/app/tratra/id123 (le nom de l'application peut être encodé en %XX)
_APPLE_PATH = re.compile(r"^/(?:(?P<cc>[a-z]{2})/)?app/(?:(?!\.{1,2}/)(?P<slug>[A-Za-z0-9\-._~%]{1,120})/)?id(?P<id>\d{6,12})/?$")

PLAY_EXAMPLE = "https://play.google.com/store/apps/details?id=com.tratra"
APPLE_EXAMPLE = "https://apps.apple.com/ci/app/tratra/id1234567890"


def _split(url: str, host: str, example: str):
    value = (url or "").strip()
    if any(ch.isspace() or ord(ch) < 32 for ch in value):
        raise ValidationError(f"Le lien ne doit contenir ni espace ni caractère invisible. Exemple : {example}")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise ValidationError(f"Lien illisible. Exemple : {example}")
    if parts.scheme.lower() != "https":
        raise ValidationError(f"Le lien doit commencer par https://. Exemple : {example}")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValidationError("Le lien ne doit pas contenir d'identifiant (« …@ »).")
    if port is not None:
        raise ValidationError("Le lien ne doit pas préciser de port.")
    if (parts.hostname or "") != host or parts.netloc.lower() != host:
        raise ValidationError(f"Seuls les liens {host} sont acceptés. Exemple : {example}")
    return parts


def normalize_play_store_url(url: str) -> str:
    """Forme canonique d'une fiche Google Play, ou ValidationError."""
    parts = _split(url, PLAY_HOST, PLAY_EXAMPLE)
    if parts.path.rstrip("/") != PLAY_PATH:
        raise ValidationError(f"Le lien doit ouvrir la fiche de l'application ({PLAY_PATH}?id=…). Exemple : {PLAY_EXAMPLE}")
    params: dict[str, list[str]] = {}
    for key, val in parse_qsl(parts.query, keep_blank_values=True):
        params.setdefault(key, []).append(val)
    ids = params.get("id") or []
    if len(ids) != 1 or not _PACKAGE.match(ids[0]):
        raise ValidationError(f"Identifiant d'application manquant ou invalide (id=com.exemple.app). Exemple : {PLAY_EXAMPLE}")
    query = [("id", ids[0])]
    for key in ("hl", "gl"):  # langue et pays d'affichage de la fiche, seuls paramètres conservés
        values = params.get(key) or []
        if len(values) == 1 and _LOCALE.match(values[0]):
            query.append((key, values[0]))
    return f"https://{PLAY_HOST}{PLAY_PATH}?{urlencode(query)}"


def normalize_app_store_url(url: str) -> str:
    """Forme canonique d'une fiche App Store, ou ValidationError."""
    parts = _split(url, APPLE_HOST, APPLE_EXAMPLE)
    match = _APPLE_PATH.match(parts.path)
    if not match:
        raise ValidationError(f"Le lien doit ouvrir la fiche de l'application (…/app/…/id123456789). Exemple : {APPLE_EXAMPLE}")
    segments = [s for s in (match["cc"], "app", match["slug"], f"id{match['id']}") if s]
    return f"https://{APPLE_HOST}/" + "/".join(segments)


NORMALIZERS = {"android": normalize_play_store_url, "ios": normalize_app_store_url}


def safe_store_url(kind: str, url: str) -> str | None:
    """Lien canonique publiable, ou None (vide ou non conforme)."""
    if not (url or "").strip():
        return None
    try:
        return NORMALIZERS[kind](url)
    except ValidationError:
        return None


def validate_play_store_url(value: str) -> None:
    if value:
        normalize_play_store_url(value)


def validate_app_store_url(value: str) -> None:
    if value:
        normalize_app_store_url(value)
