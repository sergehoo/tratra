"""Recherches de proximité servies par l'INDEX SPATIAL (GiST des positions).

Un filtre `distance__lte` sur une annotation `Distance()` calcule la distance de CHAQUE ligne (aucun index possible) : la recherche
parcourt tout le pays et ralentit à chaque nouvel inscrit. `near(champ, point, km)` ajoute un préfiltre ST_DWithin exprimé en degrés,
servi par l'index, qui contient à coup sûr le cercle demandé ; le filtre exact en mètres (ou le calcul de distance de l'appelant) reste
appliqué ensuite : les résultats sont identiques, seul le volume examiné change."""
import math

from django.db.models import Q

KM_PER_DEGREE = 6371.0 * math.pi / 180   # 111,195 km : même rayon terrestre que les distances calculées par l'application
MARGIN = 1.10                             # marge de sécurité (approximation plane locale, sphère de PostGIS)


def radius_degrees(lat: float, km: float) -> float:
    """Rayon en degrés couvrant un cercle de `km` autour d'un point de latitude `lat` : un degré de longitude raccourcit vers les
    pôles, on retient donc la latitude la plus éloignée de l'équateur que le cercle peut atteindre."""
    if km <= 0:
        return 0.0
    edge = min(89.0, abs(lat) + km / KM_PER_DEGREE)
    return min(180.0, MARGIN * km / (KM_PER_DEGREE * math.cos(math.radians(edge))))


def near(field: str, point, km: float) -> Q:
    """Q « à moins de `km` de `point` (au moins) » servi par l'index spatial de `field` ; à combiner avec le filtre exact."""
    return Q(**{f"{field}__dwithin": (point, radius_degrees(point.y, km))})
