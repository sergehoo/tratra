"""API de l'« Inscription accompagnée » (`handy.onboarding`).

GET  /onboarding/config/?trade=<id>  public : prestations du métier, questions, communes (aucune donnée personnelle)
GET  /me/onboarding/                 progression du compte connecté (étapes, prochaine action, annonce proposée)
PUT  /me/onboarding/                 enregistre les réponses (métier, prestations, quartier, réponses, étape)
POST /me/onboarding/apply/           crée/complète le profil professionnel et l'offre proposée (idempotent)
"""
from django.views.decorators.cache import never_cache
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from handy import onboarding


def _run(fn, *args):
    try:
        return Response(fn(*args))
    except onboarding.OnboardingError as exc:
        return Response({"code": exc.code, "detail": exc.detail}, status=exc.status)


@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Inscription accompagnée"], summary="Questions du métier")
@api_view(["GET"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def onboarding_config(request):
    response = _run(onboarding.config, request.query_params.get("trade"))
    if response.status_code == 200:
        response["Cache-Control"] = "public, max-age=300"
    return response


@never_cache
@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT, tags=["Inscription accompagnée"], summary="Progression et réponses")
@api_view(["GET", "PUT"])
@permission_classes([permissions.IsAuthenticated])
def me_onboarding(request):
    if request.method == "GET":
        return _run(onboarding.state, request.user)
    return _run(onboarding.save, request.user, request.data if isinstance(request.data, dict) else {})


@never_cache
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Inscription accompagnée"], summary="Créer le profil et l'annonce")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def me_onboarding_apply(request):
    return _run(onboarding.apply, request.user)
