"""Conditions d'utilisation : version en vigueur (public) et acceptation explicite d'une nouvelle version (compte connecté).

Voir `handy/legal.py` pour les garanties (aucune acceptation supposée, comptes existants préservés, audit)."""
from django.views.decorators.cache import never_cache
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from handy import legal

OUTDATED = "Les conditions d'utilisation ont été mises à jour : relisez la version en vigueur avant de l'accepter."


@extend_schema(tags=["Public"], request=None, responses=OpenApiTypes.OBJECT,
               summary="Conditions d'utilisation : version en vigueur, date de mise à jour et adresse de la page publique")
@api_view(["GET"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def public_terms(request):
    response = Response(legal.current())
    response["Cache-Control"] = "public, max-age=300"
    return response


@never_cache
@extend_schema(tags=["Compte"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT,
               summary="Mes conditions d'utilisation : version acceptée (GET) / acceptation de la version en vigueur (POST {version, accept: true})")
@api_view(["GET", "POST"])
@permission_classes([permissions.IsAuthenticated])
def me_terms(request):
    user = request.user
    if request.method == "POST":
        if request.data.get("accept") is not True:
            return Response({"code": "consent_required", "detail": "Cochez « J'accepte les Conditions d'utilisation » pour continuer."},
                            status=status.HTTP_400_BAD_REQUEST)
        source = str(request.data.get("source") or "app")[:20]
        try:
            legal.record_acceptance(user, request.data.get("version"), source=source)
        except legal.TermsOutdated:
            return Response({"code": "terms_outdated", "detail": OUTDATED, "current_version": legal.TERMS_VERSION},
                            status=status.HTTP_400_BAD_REQUEST)
    return Response(legal.status(user))
