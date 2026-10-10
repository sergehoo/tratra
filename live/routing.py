"""Distance, itinéraire et ETA. Données honnêtes : sans service d'itinéraire configuré, l'ETA est une ESTIMATION à
vol d'oiseau, clairement étiquetée comme telle (`source: "estimate"`)."""
import logging
import math
from typing import Dict, Optional, Tuple

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ESTIMATE_SPEED_KMH = 25  # vitesse moyenne urbaine retenue pour l'estimation
EARTH_RADIUS_M = 6371000.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def estimate(origin: Tuple[float, float], dest: Tuple[float, float]) -> Dict:
    d = haversine_m(*origin, *dest)
    seconds = int(d / (ESTIMATE_SPEED_KMH * 1000 / 3600))
    return {"eta_seconds": seconds, "distance_m": int(d), "polyline": [list(origin), list(dest)], "source": "estimate"}


def osrm_route(origin: Tuple[float, float], dest: Tuple[float, float]) -> Optional[Dict]:
    """Itinéraire routier réel via un serveur OSRM configuré (`ROUTING_OSRM_URL`). None si indisponible."""
    base = (getattr(settings, "ROUTING_OSRM_URL", "") or "").rstrip("/")
    if not base:
        return None
    url = f"{base}/route/v1/driving/{origin[1]:.6f},{origin[0]:.6f};{dest[1]:.6f},{dest[0]:.6f}"
    try:
        r = requests.get(url, params={"overview": "simplified", "geometries": "geojson"},
                         timeout=getattr(settings, "ROUTING_TIMEOUT", 3))
        r.raise_for_status()
        route = r.json()["routes"][0]
        coords = route["geometry"]["coordinates"]
        return {"eta_seconds": int(route["duration"]), "distance_m": int(route["distance"]),
                "polyline": [[lat, lng] for lng, lat in coords][:500], "source": "osrm"}
    except Exception as exc:  # service d'itinéraire en panne : repli honnête sur l'estimation
        logger.warning("Itinéraire OSRM indisponible : %s", exc)
        return None


def compute_route(origin: Tuple[float, float], dest: Tuple[float, float]) -> Dict:
    return osrm_route(origin, dest) or estimate(origin, dest)
