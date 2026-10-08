# /Users/ogahserge/Documents/tratra/tratra/urls.py
# Backend DÉCOUPLÉ : API pure (frontend React/Next + Flutter). Plus de pages HTML
# servies par Django ; l'UX vit dans /frontend (React) et l'app mobile (Flutter).
import logging

import redis
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.db import connections
from django.http import JsonResponse
from django.urls import path, include

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

logger = logging.getLogger(__name__)


def api_root(_request):
    return JsonResponse({
        "name": "Tratra API",
        "version": "1.0.0",
        "docs": "/api/docs/",
        "schema": "/api/schema/",
        "api": "/handy/",
    })


def healthz(_request):
    """Liveness probe: the Django process can answer HTTP requests."""
    return JsonResponse({"status": "ok"})


def readyz(_request):
    """Readiness probe: database and Redis are both reachable."""
    unavailable = []
    try:
        connections["default"].ensure_connection()
    except Exception:
        logger.warning("Readiness check: database unavailable", exc_info=True)
        unavailable.append("database")

    try:
        redis.from_url(
            settings.CELERY_BROKER_URL,
            socket_connect_timeout=1,
            socket_timeout=1,
        ).ping()
    except Exception:
        logger.warning("Readiness check: Redis unavailable", exc_info=True)
        unavailable.append("redis")

    if unavailable:
        return JsonResponse({"status": "unavailable", "dependencies": unavailable}, status=503)
    return JsonResponse({"status": "ready"})


urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("", api_root, name="api-root"),
    path("admin/", admin.site.urls),

    # API métier
    path("handy/", include("handy.api.urls")),

    # OpenAPI / documentation interactive
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
