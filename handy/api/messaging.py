"""API de la messagerie : conversations, messages (texte et médias), lecture, distribution, synchronisation, blocage, signalement,
billet WebSocket. Toute la logique est dans `handy.messaging` ; ici : authentification, forme des requêtes et réponses."""
from django.views.decorators.cache import never_cache
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.decorators import api_view, parser_classes, permission_classes, throttle_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from handy import contacts, inbox, messaging
from handy.models import Booking, Conversation, UserBlock
from handy.messaging import MessagingError

_AUTH = [permissions.IsAuthenticated]


def _fail(exc: MessagingError) -> Response:
    return Response({"detail": exc.detail, "code": exc.code}, status=exc.status)


class MessagingThrottle(ScopedRateThrottle):
    scope = "messaging"

    def __init__(self):
        super().__init__()
        self.scope = "messaging"

    def allow_request(self, request, view):
        view.throttle_scope = "messaging"
        return super().allow_request(request, view)


def _page(qs, request, default=20):
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        size = max(1, min(int(request.query_params.get("page_size", default)), 50))
    except ValueError:
        page, size = 1, default
    rows = list(qs[(page - 1) * size:page * size + 1])
    return rows[:size], len(rows) > size, page


@never_cache
@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT, tags=["Messagerie"],
               summary="Mes conversations (GET, recherche et pagination) / ouvrir une conversation (POST : réservation ou membre)")
@api_view(["GET", "POST"])
@permission_classes(_AUTH)
def me_conversations(request):
    user = request.user
    if request.method == "POST":
        if request.data.get("user") not in (None, ""):
            try:
                conv, created = messaging.open_direct(user, int(request.data["user"]))
            except (TypeError, ValueError):
                return Response({"detail": "Membre introuvable.", "code": "not_found"}, status=status.HTTP_404_NOT_FOUND)
            except MessagingError as exc:
                return _fail(exc)
            return Response({"id": conv.id, "created": created}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
        booking = Booking.objects.filter(pk=request.data.get("booking")).first()
        if booking is None or user.pk not in (booking.client_id, booking.handyman_id):
            return Response({"detail": "Réservation introuvable."}, status=status.HTTP_404_NOT_FOUND)
        if booking.handyman_id is None:
            return Response({"detail": "Aucun artisan n'est encore associé à cette réservation."}, status=status.HTTP_400_BAD_REQUEST)
        conv = Conversation.objects.filter(booking=booking, participants=booking.client).filter(participants=booking.handyman).first()
        created = conv is None
        if created:
            conv = Conversation.objects.create(booking=booking)
            conv.participants.set([booking.client, booking.handyman])
        return Response({"id": conv.id, "created": created}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    rows, more, page = _page(messaging.conversations_for(user, request.query_params.get("q", "")), request)
    blocked = contacts.blocked_ids(user.pk)
    return Response({"results": [messaging.conversation_payload(c, user.pk, unread=c.unread_count, blocked_ids=blocked) for c in rows],
                     "has_more": more, "next_page": page + 1 if more else None, "unread_total": messaging.unread_total(user)})


@never_cache
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Messagerie"],
               summary="Messages d'une de mes conversations, par curseur (GET) / les marquer lus (POST, historique)")
@api_view(["GET", "POST"])
@permission_classes(_AUTH)
def me_conversation_messages(request, pk):
    user = request.user
    try:
        conv = messaging.get_conversation(user, pk)
    except MessagingError as exc:
        return _fail(exc)
    if request.method == "POST":
        return Response({"marked": messaging.mark_read(user, conv)})
    try:
        before = int(request.query_params["before"]) if request.query_params.get("before") else None
        limit = int(request.query_params.get("limit", 50))
    except ValueError:
        before, limit = None, 50
    data = messaging.thread(user, conv, before=before, limit=limit, q=request.query_params.get("q", ""))
    return Response({"conversation": messaging.conversation_payload(conv, user.pk), **data})


@never_cache
@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT, tags=["Messagerie"], summary="Envoyer un message (texte et/ou média)")
@api_view(["POST"])
@permission_classes(_AUTH)
@parser_classes([JSONParser, MultiPartParser, FormParser])
@throttle_classes([MessagingThrottle])
def me_conversation_send(request, pk):
    user = request.user
    try:
        conv = messaging.get_conversation(user, pk)
        message, created = messaging.send(user, conv, request.data.get("content", ""), upload=request.FILES.get("file"),
                                          client_id=request.data.get("client_id") or None)
    except MessagingError as exc:
        return _fail(exc)
    return Response({"message": messaging.message_payload(message, user.pk, request), "created": created},
                    status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@never_cache
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Messagerie"], summary="Marquer la conversation comme lue")
@api_view(["POST"])
@permission_classes(_AUTH)
def me_conversation_read(request, pk):
    try:
        conv = messaging.get_conversation(request.user, pk)
    except MessagingError as exc:
        return _fail(exc)
    return Response({"marked": messaging.mark_read(request.user, conv), "unread_total": messaging.unread_total(request.user)})


@never_cache
@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT, tags=["Messagerie"], summary="Accuser réception de messages")
@api_view(["POST"])
@permission_classes(_AUTH)
def me_messages_delivered(request):
    ids = request.data.get("ids") or []
    if not isinstance(ids, list):
        return Response({"detail": "ids doit être une liste.", "code": "invalid"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        return Response({"delivered": messaging.mark_delivered(request.user, ids)})
    except (TypeError, ValueError):
        return Response({"detail": "Identifiants invalides.", "code": "invalid"}, status=status.HTTP_400_BAD_REQUEST)


@never_cache
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Messagerie"], summary="Rattrapage après coupure : messages plus récents que `after`")
@api_view(["GET"])
@permission_classes(_AUTH)
def me_messages_sync(request):
    try:
        after = int(request.query_params.get("after", 0))
        limit = int(request.query_params.get("limit", 200))
    except ValueError:
        after, limit = 0, 200
    return Response(messaging.sync(request.user, max(after, 0), limit))


@never_cache
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Messagerie"], summary="Compteur de messages non lus")
@api_view(["GET"])
@permission_classes(_AUTH)
def me_messages_unread(request):
    from django.db.models import Count

    from handy.models import Message

    rows = (Message.objects.filter(conversation__participants=request.user, is_read=False).exclude(sender=request.user)
            .values("conversation_id").annotate(n=Count("id")))
    per = {str(r["conversation_id"]): r["n"] for r in rows}
    return Response({"total": sum(per.values()), "conversations": per})


@never_cache
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Messagerie"], summary="Recherche dans mes messages")
@api_view(["GET"])
@permission_classes(_AUTH)
def me_messages_search(request):
    return Response({"results": messaging.search_messages(request.user, request.query_params.get("q", ""))})


@never_cache
@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT, tags=["Messagerie"], summary="Signaler un message d'une conversation")
@api_view(["POST"])
@permission_classes(_AUTH)
def me_conversation_report(request, pk):
    try:
        conv = messaging.get_conversation(request.user, pk)
        report = messaging.report(request.user, conv, message_id=request.data.get("message") or None, reason=request.data.get("reason", ""))
        if request.data.get("block"):
            other = next((p for p in conv.participants.all() if p.pk != request.user.pk), None)
            if other is not None and conv.kind != Conversation.SUPPORT:
                messaging.block(request.user, other.pk)
    except MessagingError as exc:
        return _fail(exc)
    return Response({"id": report.pk, "reported": True}, status=status.HTTP_201_CREATED)


@never_cache
@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT, tags=["Messagerie"], summary="Mes blocages (GET) / bloquer un membre (POST)")
@api_view(["GET", "POST"])
@permission_classes(_AUTH)
def me_blocks(request):
    if request.method == "POST":
        try:
            messaging.block(request.user, int(request.data.get("user")))
        except (TypeError, ValueError):
            return Response({"detail": "Membre introuvable.", "code": "not_found"}, status=status.HTTP_404_NOT_FOUND)
        except MessagingError as exc:
            return _fail(exc)
        return Response({"blocked": True}, status=status.HTTP_201_CREATED)
    rows = UserBlock.objects.filter(blocker=request.user).select_related("blocked").order_by("-id")
    return Response({"results": [{"user": b.blocked_id, "name": messaging.display_name(b.blocked), "since": b.created_at.isoformat()} for b in rows]})


@never_cache
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Messagerie"], summary="Débloquer un membre")
@api_view(["DELETE"])
@permission_classes(_AUTH)
def me_block_detail(request, user_id):
    messaging.unblock(request.user, user_id)
    return Response(status=status.HTTP_204_NO_CONTENT)


@never_cache
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Messagerie"],
               summary="Billet signé (60 s) pour la WebSocket temps réel (`/ws/inbox/?ticket=`)")
@api_view(["POST"])
@permission_classes(_AUTH)
def me_realtime_ticket(request):
    return Response({"ticket": inbox.make_ticket(request.user.pk), "path": "/ws/inbox/", "expires_in": inbox.TICKET_MAX_AGE})
