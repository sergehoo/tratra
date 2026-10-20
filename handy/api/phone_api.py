"""Saisie du téléphone : pays présélectionné par défaut (public, sans donnée personnelle)."""
from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from handy import phone


@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Compte"], summary="Pays proposé pour la saisie du téléphone")
@api_view(["GET"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def phone_defaults(request):
    """`ip_region` n'est renseigné que si le proxy fournit déjà le pays de l'adresse IP ; sinon null (jamais deviné)."""
    response = Response({"default_region": phone.default_region(), "ip_region": phone.ip_region(request)})
    response["Cache-Control"] = "private, max-age=3600"
    header = str(getattr(settings, "PHONE_IP_COUNTRY_HEADER", "") or "").strip()
    if header:
        response["Vary"] = header
    return response
