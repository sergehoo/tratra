"""API des statuts : fil d'accueil, découverte, publication (multipart), suppression, vue, lecteurs (auteur seul), réponse, signalement,
réglages et exclusions. Toute règle est dans `statuses.services`."""
from django.views.decorators.cache import never_cache
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status as http
from rest_framework.decorators import api_view, parser_classes, permission_classes, throttle_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from handy import messaging
from statuses import services
from statuses.services import StatusError

_AUTH = [permissions.IsAuthenticated]
_DOC = dict(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT, tags=["Statuts"])


class StatusThrottle(ScopedRateThrottle):
    def allow_request(self, request, view):
        view.throttle_scope = "statuses"
        return super().allow_request(request, view)


def _fail(exc: StatusError) -> Response:
    return Response({"detail": exc.detail, "code": exc.code}, status=exc.status)


def _int(request, name, default):
    try:
        return int(request.query_params.get(name, default))
    except ValueError:
        return default


@never_cache
@extend_schema(summary="Fil d'accueil : mes statuts, ceux de mes contacts (non lus d'abord), nombre de statuts à découvrir", **_DOC)
@api_view(["GET"])
@permission_classes(_AUTH)
def feed(request):
    return Response(services.feed(request.user, request))


@never_cache
@extend_schema(summary="Découvrir les statuts de membres qui ne sont pas mes contacts (audience élargie)", **_DOC)
@api_view(["GET"])
@permission_classes(_AUTH)
def discover(request):
    return Response(services.discover(request.user, request, _int(request, "page", 1), _int(request, "page_size", 20)))


@never_cache
@extend_schema(summary="Publier un statut (GET : mes statuts actifs avec leurs compteurs de vues)", **_DOC)
@api_view(["GET", "POST"])
@permission_classes(_AUTH)
@parser_classes([MultiPartParser, FormParser, JSONParser])
@throttle_classes([StatusThrottle])
def statuses(request):
    if request.method == "GET":
        return Response(services.mine(request.user, request))
    data = request.data
    try:
        allow = data.get("allow_replies")
        status_obj, created = services.publish(
            request.user, text=data.get("text", ""), upload=request.FILES.get("file"), audience=data.get("audience") or None,
            allow_replies=None if allow in (None, "") else str(allow).lower() in ("1", "true", "yes", "on"),
            background=data.get("background", ""), client_id=data.get("client_id") or None)
    except StatusError as exc:
        return _fail(exc)
    return Response({"status": services.payload(status_obj, request.user, request), "created": created},
                    status=http.HTTP_201_CREATED if created else http.HTTP_200_OK)


@never_cache
@extend_schema(summary="Supprimer mon statut", **_DOC)
@api_view(["DELETE"])
@permission_classes(_AUTH)
def status_detail(request, pk):
    try:
        services.delete(request.user, pk)
    except StatusError as exc:
        return _fail(exc)
    return Response(status=http.HTTP_204_NO_CONTENT)


@never_cache
@extend_schema(summary="Enregistrer une vue : à appeler quand le statut est RÉELLEMENT affiché (jamais au préchargement)", **_DOC)
@api_view(["POST"])
@permission_classes(_AUTH)
@throttle_classes([StatusThrottle])
def status_view(request, pk):
    try:
        return Response(services.record_view(request.user, pk))
    except StatusError as exc:
        return _fail(exc)


@never_cache
@extend_schema(summary="Lecteurs de mon statut (liste nominative réservée à l'auteur)", **_DOC)
@api_view(["GET"])
@permission_classes(_AUTH)
def status_viewers(request, pk):
    try:
        return Response(services.viewers(request.user, pk, _int(request, "page", 1), _int(request, "page_size", 50), request))
    except StatusError as exc:
        return _fail(exc)


@never_cache
@extend_schema(summary="Répondre à un statut par message privé (si l'auteur l'autorise)", **_DOC)
@api_view(["POST"])
@permission_classes(_AUTH)
@throttle_classes([StatusThrottle])
def status_reply(request, pk):
    try:
        conv, message = services.reply(request.user, pk, request.data.get("content", ""))
    except StatusError as exc:
        return _fail(exc)
    return Response({"conversation": conv.pk, "message": messaging.message_payload(message, request.user.pk, request)}, status=http.HTTP_201_CREATED)


@never_cache
@extend_schema(summary="Signaler un statut", **_DOC)
@api_view(["POST"])
@permission_classes(_AUTH)
def status_report(request, pk):
    try:
        services.report(request.user, pk, request.data.get("reason", ""))
    except StatusError as exc:
        return _fail(exc)
    return Response({"reported": True}, status=http.HTTP_201_CREATED)


@never_cache
@extend_schema(summary="Mes réglages de statuts (audience par défaut, réponses) — GET / PUT", **_DOC)
@api_view(["GET", "PUT"])
@permission_classes(_AUTH)
def settings_view(request):
    try:
        pref = services.set_preference(request.user, audience=request.data.get("audience"),
                                       allow_replies=request.data.get("allow_replies")) if request.method == "PUT" else services.preference(request.user)
    except StatusError as exc:
        return _fail(exc)
    return Response({"audience": pref.audience, "allow_replies": pref.allow_replies, "limits": services.limits(),
                     "exclusions": services.exclusions(request.user)})


@never_cache
@extend_schema(summary="Mes contacts Tratra (pour choisir ceux à qui je ne montre pas mes statuts)", **_DOC)
@api_view(["GET"])
@permission_classes(_AUTH)
def contacts_view(request):
    return Response({"results": services.contact_candidates(request.user)})


@never_cache
@extend_schema(summary="Exclure un membre de mes statuts (POST) ", **_DOC)
@api_view(["POST"])
@permission_classes(_AUTH)
def exclusions_view(request):
    try:
        services.exclude(request.user, int(request.data.get("user")))
    except (TypeError, ValueError):
        return Response({"detail": "Membre introuvable.", "code": "not_found"}, status=http.HTTP_404_NOT_FOUND)
    except StatusError as exc:
        return _fail(exc)
    return Response({"excluded": True}, status=http.HTTP_201_CREATED)


@never_cache
@extend_schema(summary="Ne plus exclure un membre", **_DOC)
@api_view(["DELETE"])
@permission_classes(_AUTH)
def exclusion_detail(request, user_id):
    services.include(request.user, user_id)
    return Response(status=http.HTTP_204_NO_CONTENT)
