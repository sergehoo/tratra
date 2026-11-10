"""Recherche d'adresse (autocomplétion), géocodage et géocodage inverse via un fournisseur configurable.

 - Fournisseur : `GEO_PROVIDER` = `nominatim` (OpenStreetMap, sans clé) | `google` (clé `GEO_GOOGLE_API_KEY` : recherche par
   Places API (New) « Text Search » — lieux, quartiers, commerces, avec leurs coordonnées en un seul appel —, position par Geocoding API ;
   `GEO_GOOGLE_PLACES=False` revient à Geocoding pour la recherche) | `none` (aucun appel externe : saisie manuelle uniquement) ;
 - chaque résultat : `name` (lieu nommé), `street`, `quartier`, `commune` (une des 13 communes du district d'Abidjan quand le lieu y est,
   sinon la ville), `city`, `country`, `label`, `latitude`, `longitude` ;
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


def _get(url: str, params: Dict, headers: Optional[Dict] = None, *, body: Optional[Dict] = None):
    """GET (ou POST JSON avec `body`). La clé du fournisseur n'apparaît jamais dans les journaux (seul le type d'erreur y figure)."""
    if cache.get("geo:down"):
        raise GeoUnavailable("Recherche d’adresse indisponible pour le moment. Saisissez l’adresse manuellement.")
    _acquire_slot()
    try:
        timeout = int(_cfg("GEO_TIMEOUT", 4))
        r = (requests.post(url, json=body, headers=headers or {}, timeout=timeout) if body is not None
             else requests.get(url, params=params, headers=headers or {}, timeout=timeout))
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


# Les 13 communes du district autonome d'Abidjan : la « commune » d'une adresse y est l'une d'elles (Cocody, Yopougon…), jamais le
# quartier (Deux-Plateaux, Riviera, Niangon…) — c'est elle qui sert à la zone d'intervention des professionnels.
ABIDJAN_COMMUNES = ("Abobo", "Adjamé", "Attécoubé", "Cocody", "Koumassi", "Marcory", "Plateau", "Port-Bouët", "Treichville", "Yopougon",
                    "Bingerville", "Anyama", "Songon")


def _fold(text: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


_COMMUNES = {_fold(c): c for c in ABIDJAN_COMMUNES}


def abidjan_commune(*texts) -> str:
    """Commune du district d'Abidjan nommée telle quelle dans l'un des éléments (« Cocody », « Port Bouet »…) ; « Deux-Plateaux »
    n'est pas « Plateau » (comparaison d'éléments entiers, jamais de sous-chaîne)."""
    for text in texts:
        for part in re.split(r"[,;/]", str(text or "")):
            hit = _COMMUNES.get(_fold(part).removeprefix("commune de ").removeprefix("commune d "))
            if hit:
                return hit
    return ""


def _place(*, name="", street="", quartiers=(), commune_hints=(), towns=(), country="", label="", lat=None, lng=None) -> Dict:
    commune = abidjan_commune(*commune_hints) or next((t for t in towns if t), "")
    quartier = next((q for q in quartiers if q and _fold(q) != _fold(commune) and _fold(q) != _fold(name)), "")
    city = "Abidjan" if commune in ABIDJAN_COMMUNES else next((t for t in towns if t), "")
    return {"label": (label or "")[:255], "name": (name or "")[:120], "street": (street or "")[:255], "quartier": quartier[:100],
            "commune": commune[:100], "city": city[:100], "country": (country or "")[:80], "latitude": _coord(lat), "longitude": _coord(lng)}


def _from_nominatim(item: Dict) -> Dict:
    a = item.get("address") or {}
    display = item.get("display_name") or ""
    street = " ".join(x for x in (a.get("house_number"), a.get("road") or a.get("pedestrian")) if x)
    named = item.get("name") or ""
    return _place(
        name=named if named and named != street else "", street=street,
        quartiers=(a.get("neighbourhood"), a.get("quarter"), a.get("residential"), a.get("suburb"), a.get("city_district")),
        commune_hints=(a.get("city_district"), a.get("suburb"), a.get("municipality"), a.get("town"), a.get("city"), display),
        towns=(a.get("town"), a.get("city"), a.get("village"), a.get("municipality"), a.get("county")),
        country=a.get("country"), label=display, lat=item.get("lat"), lng=item.get("lon"))


def _components(items, long_key: str) -> Dict[str, str]:
    comps: Dict[str, str] = {}
    for c in items or []:
        for t in c.get("types", []):
            comps.setdefault(t, c.get(long_key, "") or "")
    return comps


def _from_google(item: Dict) -> Dict:
    """Résultat de Geocoding API (position GPS ; recherche si `GEO_GOOGLE_PLACES=False`)."""
    comps = _components(item.get("address_components"), "long_name")
    loc = (item.get("geometry") or {}).get("location") or {}
    street = " ".join(x for x in (comps.get("street_number"), comps.get("route")) if x)
    return _place(
        street=street, quartiers=(comps.get("neighborhood"), comps.get("sublocality_level_2"), comps.get("sublocality_level_1")),
        commune_hints=(comps.get("sublocality_level_1"), comps.get("sublocality"), comps.get("locality"), item.get("formatted_address")),
        towns=(comps.get("locality"), comps.get("administrative_area_level_2")), country=comps.get("country"),
        label=item.get("formatted_address"), lat=loc.get("lat"), lng=loc.get("lng"))


def _from_places(item: Dict) -> Dict:
    """Résultat de Places API (New) « Text Search » : lieu nommé (pharmacie, école, immeuble…) ou adresse, coordonnées incluses."""
    comps = _components(item.get("addressComponents"), "longText")
    loc = item.get("location") or {}
    name = ((item.get("displayName") or {}).get("text") or "").strip()
    street = " ".join(x for x in (comps.get("street_number"), comps.get("route")) if x)
    formatted = item.get("formattedAddress") or ""
    return _place(
        name=name if name and name not in (street, formatted) and _fold(name) != _fold(comps.get("sublocality_level_1", "")) else "",
        street=street, quartiers=(comps.get("neighborhood"), comps.get("sublocality_level_2"), comps.get("sublocality_level_1")),
        commune_hints=(comps.get("sublocality_level_1"), comps.get("sublocality"), comps.get("locality"), formatted, name),
        towns=(comps.get("locality"), comps.get("administrative_area_level_2")), country=comps.get("country"),
        label=", ".join(x for x in (name if name and name not in formatted else "", formatted) if x),
        lat=loc.get("latitude"), lng=loc.get("longitude"))


PLACES_FIELDS = "places.displayName,places.formattedAddress,places.location,places.addressComponents"


def _google_places(q: str, country: str) -> List[Dict]:
    lat, lng = (float(x) for x in str(_cfg("GEO_BIAS_CENTER", "5.345,-4.024")).split(","))
    body = {"textQuery": q, "languageCode": "fr", "regionCode": country.upper(), "pageSize": MAX_RESULTS,
            "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": float(_cfg("GEO_BIAS_RADIUS_M", 50000))}}}
    data = _get("https://places.googleapis.com/v1/places:searchText", {}, {
        "X-Goog-Api-Key": _cfg("GEO_GOOGLE_API_KEY", ""), "X-Goog-FieldMask": PLACES_FIELDS, "Content-Type": "application/json"}, body=body)
    out = []
    for item in (data or {}).get("places", [])[:MAX_RESULTS]:
        comps = _components(item.get("addressComponents"), "shortText")
        if comps.get("country", country.upper()).upper() == country.upper():   # jamais un lieu hors du pays
            out.append(_from_places(item))
    return out


def _search_remote(q: str) -> List[Dict]:
    country = str(_cfg("GEO_COUNTRY", "ci")).lower()
    if provider() == "google" and _cfg("GEO_GOOGLE_PLACES", True):
        return _google_places(q, country)
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
    if found:
        found["name"] = ""   # un commerce voisin (le plus proche du point) n'est pas le lieu de l'utilisateur
    # Le cache (partagé entre comptes) ne garde JAMAIS de coordonnées exactes : elles sont ajoutées à chaque réponse.
    cache.set(key, {k: v for k, v in (found or {}).items() if k not in ("latitude", "longitude")} or {}, int(_cfg("GEO_CACHE_TTL", 86400)))
    return _at(found, lat, lng)


def _at(found: Optional[Dict], lat: float, lng: float) -> Optional[Dict]:
    """Le point reste celui de l'utilisateur (le fournisseur renvoie le bâtiment le plus proche)."""
    if not found:
        return None
    return {**found, "latitude": round(lat, 6), "longitude": round(lng, 6)}
