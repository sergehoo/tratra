# /Users/ogahserge/Documents/tratra/tratra/urls.py
# Backend DÉCOUPLÉ : API pure (frontend React/Next + Flutter). Plus de pages HTML
# servies par Django ; l'UX vit dans /frontend (React) et l'app mobile (Flutter).
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, include

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView


def api_root(_request):
    return JsonResponse({
        "name": "Tratra API",
        "version": "1.0.0",
        "docs": "/api/docs/",
        "schema": "/api/schema/",
        "api": "/handy/",
    })


urlpatterns = [
    path("healthz", lambda r: JsonResponse({"status": "ok"})),
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
