"""API membre de la vérification faciale (Flutter). Toutes les réponses sont en no-store ; le jeton de session ne circule que dans l'en-tête
`X-Biometric-Token` (jamais dans l'URL) ; aucun score ni seuil n'est renvoyé à l'utilisateur."""
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.decorators import api_view, parser_classes, permission_classes, throttle_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from biometrics import services
from biometrics.crypto import BiometricUnavailable

TOKEN_HEADER = "HTTP_X_BIOMETRIC_TOKEN"


def _error(exc):
    if isinstance(exc, BiometricUnavailable):
        return Response({"code": exc.code, "detail": exc.detail}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({"code": exc.code, "detail": exc.detail, **exc.extra}, status=exc.status)


def _guard(view):
    def wrapped(request, *a, **kw):
        try:
            return view(request, *a, **kw)
        except (services.BiometricError, BiometricUnavailable) as exc:
            return _error(exc)
    wrapped.__name__ = view.__name__
    wrapped.__doc__ = view.__doc__
    return wrapped


def _ip(request) -> str:
    return (request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0] or request.META.get("REMOTE_ADDR", "")).strip()


@extend_schema(tags=["KYC biométrique"], summary="État de ma vérification faciale (consentement, pièce, session en cours, résultat)")
@never_cache
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@_guard
def biometric_state(request):
    return Response(services.state(request.user))


@extend_schema(tags=["KYC biométrique"], summary="Donner (POST) ou retirer (DELETE) mon consentement biométrique ; le retrait supprime mes captures")
@never_cache
@api_view(["POST", "DELETE"])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_guard
def biometric_consent(request):
    if request.method == "DELETE":
        return Response({"captures_deleted": services.withdraw_consent(request.user)})
    c = services.grant_consent(request.user, version=str(request.data.get("version") or ""), ip=_ip(request))
    return Response({"granted": True, "version": c.version}, status=status.HTTP_201_CREATED)


@extend_schema(tags=["KYC biométrique"], summary="Créer ou reprendre une session de vérification faciale (jeton court renvoyé une seule fois)")
@never_cache
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_guard
def biometric_session(request):
    return Response(services.start_session(request.user), status=status.HTTP_201_CREATED)


@extend_schema(tags=["KYC biométrique"], summary="Envoyer la capture d'une étape (multipart : index, kind, file ; en-tête X-Biometric-Token)")
@never_cache
@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_guard
def biometric_capture(request, pk):
    upload = request.FILES.get("file")
    try:
        index = int(request.data.get("index"))
    except (TypeError, ValueError):
        raise services.BiometricError("invalid", "Étape invalide.", 400)
    if upload is None:
        raise services.BiometricError("invalid", "Capture manquante.", 400)
    return Response(services.add_capture(request.user, pk, request.META.get(TOKEN_HEADER, ""), index=index, kind=str(request.data.get("kind") or ""), data=upload.read()),
                    status=status.HTTP_201_CREATED)


@extend_schema(tags=["KYC biométrique"], summary="Soumettre la session (vérification faite côté serveur ; en l'absence de fournisseur : revue humaine)")
@never_cache
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_guard
def biometric_submit(request, pk):
    return Response(services.submit(request.user, pk, request.META.get(TOKEN_HEADER, "")))


@extend_schema(tags=["KYC biométrique"], summary="Demander une vérification par l'équipe Tratra (alternative accessible)")
@never_cache
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_guard
def biometric_human_review(request):
    ver = services.request_human_review(request.user, str(request.data.get("reason") or "other"))
    return Response({"status": ver.status, "status_label": ver.get_status_display()})


for _v in (biometric_consent, biometric_session, biometric_capture, biometric_submit, biometric_human_review):
    _v.cls.throttle_scope = "biometric"
