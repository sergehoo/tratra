"""Recherche d'adresse (autocomplétion), géocodage et géocodage inverse via un fournisseur configurable.

 - Fournisseur : `GEO_PROVIDER` = `nominatim` (OpenStreetMap, sans clé) | `google` (Geocoding API, clé `GEO_GOOGLE_API_KEY`)
   | `none` (aucun appel externe : saisie manuelle uniquement) ;
 - cache des recherches (`GEO_CACHE_TTL`) et limite globale d'appels sortants par minute (`GEO_MAX_CALLS_PER_MINUTE`) ;
 - panne du fournisseur => `GeoUnavailable` (le client propose la saisie manuelle) ; une panne n'est jamais mise en cache comme réponse ;
 - aucune coordonnée ni requête n'est journalisée ; la clé du fournisseur ne sort jamais dans une réponse.
"""
import hashlib
import logging
import re
import time
from typing import Dict, List, Optional

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

MIN_QUERY = 3
MAX_RESULTS = 5


class GeoUnavailable(Exception):
    """Fournisseur absent, en panne ou quota atteint : le message est destiné à l'utilisateur."""


def _cfg(name: str, default):
    return getattr(settings, name, default)


def provider() -> str:
    p = str(_cfg("GEO_PROVIDER", "nominatim") or "none").strip().lower()
    return p if p in ("nominatim", "google") else "none"


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower())[:160]


def _key(kind: str, payload: str) -> str:
    return "geo:" + hashlib.sha256(f"{provider()}|{kind}|{payload}".encode()).hexdigest()[:32]


def _acquire_slot() -> None:
    """Limite globale des appels sortants (protège le quota et respecte la politique d'usage du fournisseur)."""
    limit = int(_cfg("GEO_MAX_CALLS_PER_MINUTE", 30))
    key = "geo:calls:" + str(int(time.time() // 60))
    cache.add(key, 0, 90)
    try:
        used = cache.incr(key)
    except ValueError:
        used = 1
    if used > limit:
        raise GeoUnavailable("Recherche d’adresse momentanément saturée. Saisissez l’adresse manuellement ou réessayez dans une minute.")


def _get(url: str, params: Dict, headers: Optional[Dict] = None):
    if cache.get("geo:down"):
        raise GeoUnavailable("Recherche d’adresse indisponible pour le moment. Saisissez l’adresse manuellement.")
    _acquire_slot()
    try:
        r = requests.get(url, params=params, headers=headers or {}, timeout=int(_cfg("GEO_TIMEOUT", 4)))
        r.raise_for_status()
        return r.json()
    except Exception as exc:  # panne réseau, quota fournisseur, réponse invalide…
        cache.set("geo:down", 1, 30)  # évite de marteler un fournisseur en panne
        logger.warning("Fournisseur d'adresses indisponible (%s)", type(exc).__name__)
        raise GeoUnavailable("Recherche d’adresse indisponible pour le moment. Saisissez l’adresse manuellement.") from exc


def _coord(v) -> Optional[float]:
    try:
        return round(float(v), 6)
    except (TypeError, ValueError):
        return None


def _from_nominatim(item: Dict) -> Dict:
    a = item.get("address") or {}
    street = " ".join(x for x in (a.get("house_number"), a.get("road") or a.get("pedestrian")) if x)
    return {
        "label": (item.get("display_name") or "")[:255], "street": street[:255],
        "commune": (a.get("suburb") or a.get("neighbourhood") or a.get("quarter") or a.get("city_district") or "")[:100],
        "city": (a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or a.get("county") or "")[:100],
        "country": (a.get("country") or "")[:80], "latitude": _coord(item.get("lat")), "longitude": _coord(item.get("lon")),
    }


def _from_google(item: Dict) -> Dict:
    comps = {}
    for c in item.get("address_components", []):
        for t in c.get("types", []):
            comps.setdefault(t, c.get("long_name", ""))
    loc = (item.get("geometry") or {}).get("location") or {}
    street = " ".join(x for x in (comps.get("street_number"), comps.get("route")) if x)
    return {
        "label": (item.get("formatted_address") or "")[:255], "street": street[:255],
        "commune": (comps.get("sublocality") or comps.get("sublocality_level_1") or comps.get("neighborhood") or "")[:100],
        "city": (comps.get("locality") or comps.get("administrative_area_level_2") or "")[:100],
        "country": comps.get("country", "")[:80], "latitude": _coord(loc.get("lat")), "longitude": _coord(loc.get("lng")),
    }


def _search_remote(q: str) -> List[Dict]:
    country = str(_cfg("GEO_COUNTRY", "ci")).lower()
    if provider() == "google":
        data = _get("https://maps.googleapis.com/maps/api/geocode/json",
                    {"address": q, "components": f"country:{country.upper()}", "language": "fr", "key": _cfg("GEO_GOOGLE_API_KEY", "")})
        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            cache.set("geo:down", 1, 30)
            raise GeoUnavailable("Recherche d’adresse indisponible pour le moment. Saisissez l’adresse manuellement.")
        return [_from_google(i) for i in data.get("results", [])[:MAX_RESULTS]]
    base = str(_cfg("GEO_NOMINATIM_URL", "https://nominatim.openstreetmap.org")).rstrip("/")
    data = _get(f"{base}/search", {"q": q, "format": "jsonv2", "addressdetails": 1, "limit": MAX_RESULTS, "countrycodes": country, "accept-language": "fr"},
                {"User-Agent": _cfg("GEO_USER_AGENT", "Tratra/1.0 (contact: support@tratra.net)")})
    return [_from_nominatim(i) for i in data[:MAX_RESULTS]] if isinstance(data, list) else []


def search(q: str) -> List[Dict]:
    """Suggestions d'adresses pour une saisie (≥ 3 caractères). Résultats mis en cache."""
    q = _norm(q or "")
    if len(q) < MIN_QUERY:
        return []
    if provider() == "none":
        raise GeoUnavailable("La recherche d’adresse n’est pas activée. Saisissez l’adresse manuellement.")
    key = _key("search", q)
    hit = cache.get(key)
    if hit is not None:
        return hit
    results = [r for r in _search_remote(q) if r["latitude"] is not None and r["longitude"] is not None]
    cache.set(key, results, int(_cfg("GEO_CACHE_TTL", 86400)))
    return results


def reverse(lat: float, lng: float) -> Optional[Dict]:
    """Adresse d'un point (géocodage inverse). Coordonnées arrondies à ~11 m pour le cache ; jamais journalisées."""
    if provider() == "none":
        raise GeoUnavailable("La recherche d’adresse n’est pas activée. Saisissez l’adresse manuellement.")
    rlat, rlng = round(lat, 4), round(lng, 4)
    key = _key("reverse", f"{rlat},{rlng}")
    hit = cache.get(key)
    if hit is not None:
        return _at(hit, lat, lng)
    if provider() == "google":
        data = _get("https://maps.googleapis.com/maps/api/geocode/json", {"latlng": f"{rlat},{rlng}", "language": "fr", "key": _cfg("GEO_GOOGLE_API_KEY", "")})
        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            cache.set("geo:down", 1, 30)
            raise GeoUnavailable("Recherche d’adresse indisponible pour le moment. Saisissez l’adresse manuellement.")
        found = _from_google(data["results"][0]) if data.get("results") else None
    else:
        base = str(_cfg("GEO_NOMINATIM_URL", "https://nominatim.openstreetmap.org")).rstrip("/")
        data = _get(f"{base}/reverse", {"lat": rlat, "lon": rlng, "format": "jsonv2", "addressdetails": 1, "zoom": 18, "accept-language": "fr"},
                    {"User-Agent": _cfg("GEO_USER_AGENT", "Tratra/1.0 (contact: support@tratra.net)")})
        found = _from_nominatim(data) if isinstance(data, dict) and data.get("address") else None
    # Le cache (partagé entre comptes) ne garde JAMAIS de coordonnées exactes : elles sont ajoutées à chaque réponse.
    cache.set(key, {k: v for k, v in (found or {}).items() if k not in ("latitude", "longitude")} or {}, int(_cfg("GEO_CACHE_TTL", 86400)))
    return _at(found, lat, lng)


def _at(found: Optional[Dict], lat: float, lng: float) -> Optional[Dict]:
    """Le point reste celui de l'utilisateur (le fournisseur renvoie le bâtiment le plus proche)."""
    if not found:
        return None
    return {**found, "latitude": round(lat, 6), "longitude": round(lng, 6)}
