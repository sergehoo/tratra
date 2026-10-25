"""Catalogue public des métiers : `GET /handy/catalog/` — la même réponse pour le web, l'application mobile et tout futur client.

Aucune authentification, aucune donnée personnelle (catégories et nombres d'offres uniquement). Réponse mise en cache côté serveur quelques secondes,
avec `ETag` : un client qui renvoie `If-None-Match` reçoit `304` sans corps tant que le catalogue n'a pas changé."""
from django.http import HttpResponse
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from handy import catalog

CACHE_CONTROL = "public, max-age=60, stale-while-revalidate=300"


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def public_catalog(request):
    payload = catalog.get_payload()
    etag = f'W/"{payload["version"]}"'
    if etag in [t.strip() for t in request.META.get("HTTP_IF_NONE_MATCH", "").split(",")]:
        response = HttpResponse(status=304)
    else:
        response = Response(payload)
    response["ETag"] = etag
    response["Cache-Control"] = CACHE_CONTROL
    return response


public_catalog.cls.throttle_scope = "catalog"


MATCH_MAX_CHARS = 300


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def catalog_match(request):
    """« J'ai une panne » : `GET /handy/catalog/match/?q=mon frigo ne refroidit plus` → prestations et métiers pertinents (classés).

    Le texte du client n'est ni enregistré ni journalisé ; la réponse ne contient que des catégories du catalogue public. Pour trouver les
    artisans, le client enchaîne avec la recherche habituelle (`/services/?categories=…&commune=…` ou `/services/nearby/`)."""
    text = (request.query_params.get("q") or "").strip()[:MATCH_MAX_CHARS]
    response = Response(catalog.match(text))
    response["Cache-Control"] = "no-store"
    return response


catalog_match.cls.throttle_scope = "catalog"
