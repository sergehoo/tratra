"""Liens publics des applications mobiles (badges Google Play / App Store du site) — lecture seule, sans authentification."""
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import permissions, serializers
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from handy.models import MobileAppLinks
from handy.store_links import safe_store_url


def public_mobile_app_links() -> dict:
    """Un lien n'est publié que si son badge est activé ET qu'il est une fiche officielle valide (contrôlé à nouveau à la
    lecture : une valeur écrite hors administration n'est jamais exposée). null = badge masqué."""
    links = MobileAppLinks.current()
    return {
        "android_url": safe_store_url("android", links.android_store_url) if links.android_enabled else None,
        "ios_url": safe_store_url("ios", links.ios_store_url) if links.ios_enabled else None,
    }


@extend_schema(
    tags=["Public"],
    summary="Liens des applications mobiles",
    description="Fiches Google Play et App Store à afficher sous forme de badges. null : badge masqué (lien vide, désactivé "
                "ou non conforme). Configuré dans l'administration Django (« Liens des applications mobiles »).",
    request=None,
    responses=inline_serializer(
        name="PublicMobileApps",
        fields={
            "android_url": serializers.URLField(allow_null=True),
            "ios_url": serializers.URLField(allow_null=True),
        },
    ),
)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def public_mobile_apps(request):
    """GET /public/mobile-apps/"""
    response = Response(public_mobile_app_links())
    response["Cache-Control"] = "public, max-age=300"
    return response
