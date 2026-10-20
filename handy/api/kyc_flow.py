"""API du parcours guidé « Vérifier mon identité » (`handy.kyc_flow`) : uniquement le dossier du compte connecté.

GET   /me/kyc/          état complet (étapes, informations, photos et leur contrôle, revue, activation)
PATCH /me/kyc/          {"personal": {...}} | {"document_kind": "cni|passport"} | {"face_choice": "biometric|human"}
POST  /me/kyc/capture/  multipart : side=front|back, file=<photo>  → contrôle qualité / lecture de la photo
POST  /me/kyc/send/     transmet les photos à l'équipe (pièces « en attente » dans la file KYC)
POST  /me/kyc/restart/  nouvelle pièce après un refus
"""
from django.views.decorators.cache import never_cache
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.decorators import api_view, parser_classes, permission_classes, throttle_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from handy import kyc_flow


class KycFlowThrottle(ScopedRateThrottle):
    def allow_request(self, request, view):
        view.throttle_scope = "kyc_flow"
        return super().allow_request(request, view)


def _fail(exc: kyc_flow.KycFlowError) -> Response:
    body = {"code": exc.code, "detail": exc.detail}
    if getattr(exc, "fields", None):
        body["fields"] = exc.fields
    return Response(body, status=exc.status)


def _run(fn, *args):
    try:
        return Response(fn(*args))
    except kyc_flow.KycFlowError as exc:
        return _fail(exc)


@never_cache
@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT, tags=["KYC"], summary="Parcours « Vérifier mon identité » : état et saisie")
@api_view(["GET", "PATCH"])
@permission_classes([permissions.IsAuthenticated])
@parser_classes([JSONParser])
def me_kyc(request):
    if request.method == "GET":
        return _run(kyc_flow.state, request.user)
    data = request.data if isinstance(request.data, dict) else {}
    return _run(kyc_flow.update, request.user, data)


@never_cache
@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT, tags=["KYC"], summary="Photo d'une face de la pièce + contrôle qualité")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
@throttle_classes([KycFlowThrottle])
def me_kyc_capture(request):
    return _run(kyc_flow.capture, request.user, str(request.data.get("side") or ""), request.FILES.get("file"))


@never_cache
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["KYC"], summary="Transmettre la pièce à l'équipe Tratra")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([KycFlowThrottle])
def me_kyc_send(request):
    return _run(kyc_flow.send, request.user)


@never_cache
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["KYC"], summary="Nouvelle pièce après un refus")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def me_kyc_restart(request):
    return _run(kyc_flow.restart, request.user)
