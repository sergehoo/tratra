"""Back-Office — messagerie administrateur : écrire à un membre ou à plusieurs (individuellement), suivre les envois, lire et répondre
aux réponses des membres. Droits : `messages.send` (≤ 20 destinataires choisis, réponses), `messages.bulk` (critères ou plus de 20).
Tout envoi est journalisé ; aucun membre ne voit les autres destinataires."""
from django.core.cache import cache
from django.db.models import Count, F, Q
from rest_framework.response import Response

from backoffice import rbac, staff_messaging
from backoffice.common import BOView, audit_op, bad_request, mask_phone, paginate, public_name
from backoffice.models import StaffMessageBatch, StaffMessageDelivery
from backoffice.staff_messaging import StaffMessagingError
from handy import messaging
from handy.models import Conversation, Message

SEND_PER_HOUR = 30


def _fail(exc: StaffMessagingError) -> Response:
    return bad_request(exc.code, exc.detail, exc.status)


def _selection(request) -> dict:
    data = request.data
    sel = {}
    if data.get("user_ids"):
        sel["user_ids"] = data.get("user_ids")
    if data.get("filters"):
        sel["filters"] = data.get("filters")
    return sel


def _allowed(request, selection) -> bool:
    need = "messages.bulk" if staff_messaging.is_bulk(selection) else "messages.send"
    return rbac.has_permission(request.user, need)


class MessagePreview(BOView):
    bo_permission = "messages.send"

    def post(self, request):
        sel = _selection(request)
        if not _allowed(request, sel):
            return bad_request("forbidden", "Droits insuffisants pour un envoi à de nombreux membres.", 403)
        try:
            return Response(staff_messaging.preview(sel, request.data.get("body", ""), request.data.get("purpose", "service")))
        except StaffMessagingError as exc:
            return _fail(exc)


class MessageSend(BOView):
    bo_permission = "messages.send"

    def post(self, request):
        sel = _selection(request)
        if not _allowed(request, sel):
            return bad_request("forbidden", "Droits insuffisants pour un envoi à de nombreux membres.", 403)
        key = f"bo:msg:{request.user.pk}"
        cache.add(key, 0, 3600)
        if cache.incr(key) > SEND_PER_HOUR:
            return bad_request("rate_limited", "Trop d'envois en une heure. Réessayez plus tard.", 429)
        try:
            batch = staff_messaging.create_batch(request.user, sel, request.data.get("body", ""), request.data.get("purpose", "service"))
        except StaffMessagingError as exc:
            return _fail(exc)
        audit_op(request, "message.batch_created", batch, recipients=batch.recipient_count, purpose=batch.purpose, bulk=staff_messaging.is_bulk(sel),
                 selection_kind="user_ids" if "user_ids" in batch.selection else "filters")
        staff_messaging.enqueue(batch.pk)
        batch.refresh_from_db()
        return Response(_batch_row(batch), status=201)


def _batch_row(b: StaffMessageBatch) -> dict:
    return {"id": b.pk, "created_at": b.created_at, "finished_at": b.finished_at, "status": b.status, "purpose": b.purpose,
            "sender": public_name(b.sender) if b.sender_id else None, "body": b.body, "recipient_count": b.recipient_count,
            "selection": "user_ids" if "user_ids" in b.selection else "filters", "results": staff_messaging.results(b)}


class BatchList(BOView):
    bo_permission = "messages.send"

    def get(self, request):
        qs = StaffMessageBatch.objects.select_related("sender")
        if not rbac.has_permission(request.user, "messages.bulk"):
            qs = qs.filter(sender=request.user)               # sans droit d'envoi en masse : seulement ses propres envois
        return paginate(request, qs, _batch_row)


class BatchDetail(BOView):
    bo_permission = "messages.send"

    def get(self, request, pk):
        b = StaffMessageBatch.objects.filter(pk=pk).select_related("sender").first()
        if b is None or (b.sender_id != request.user.pk and not rbac.has_permission(request.user, "messages.bulk")):
            return bad_request("not_found", "Envoi introuvable.", 404)
        status = request.query_params.get("status")
        qs = StaffMessageDelivery.objects.filter(batch=b).select_related("user", "message").order_by("pk")
        if status in dict(StaffMessageDelivery.STATUSES):
            qs = qs.filter(status=status)
        deliveries = paginate(request, qs, lambda d: {
            "user": d.user_id, "name": public_name(d.user), "phone": mask_phone(d.user.phone), "status": d.status, "error": d.error,
            "state": messaging.state_of(d.message) if d.message_id else None, "updated_at": d.updated_at})
        return Response({"batch": _batch_row(b), "deliveries": deliveries.data})


def _thread_row(c: Conversation, member) -> dict:
    return {"id": c.pk, "member": {"id": member.pk, "name": public_name(member), "phone": mask_phone(member.phone)} if member else None,
            "last_message": c.last_message_preview, "last_at": c.last_message_at or c.updated_at, "unread": getattr(c, "unread_from_member", 0)}


class ThreadList(BOView):
    """Fils « Équipe Tratra » : un par membre. `unread` = réponses du membre pas encore lues par l'équipe."""
    bo_permission = "messages.send"

    def get(self, request):
        qs = (Conversation.objects.filter(kind=Conversation.SUPPORT, last_message_at__isnull=False).prefetch_related("participants")
              .annotate(unread_from_member=Count("messages", filter=Q(messages__is_read=False, messages__via_staff=False), distinct=True)))
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(participants__first_name__icontains=q) | Q(participants__last_name__icontains=q) | Q(participants__username__icontains=q))
        if request.query_params.get("unread") == "true":
            qs = qs.filter(unread_from_member__gt=0)
        qs = qs.order_by(F("last_message_at").desc(nulls_last=True), "-id")
        return paginate(request, qs, lambda c: _thread_row(c, next(iter(c.participants.all()), None)))


def _thread(pk):
    return Conversation.objects.filter(pk=pk, kind=Conversation.SUPPORT).prefetch_related("participants").first()


class ThreadDetail(BOView):
    bo_permission = "messages.send"

    def get(self, request, pk):
        c = _thread(pk)
        if c is None:
            return bad_request("not_found", "Conversation introuvable.", 404)
        member = next(iter(c.participants.all()), None)
        try:
            before = int(request.query_params["before"]) if request.query_params.get("before") else None
        except ValueError:
            before = None
        qs = c.messages.select_related("sender").order_by("-id")
        if before:
            qs = qs.filter(pk__lt=before)
        rows = list(qs[:51])
        more = len(rows) > 50
        rows = list(reversed(rows[:50]))
        return Response({"thread": _thread_row(c, member), "has_more": more, "next_before": rows[0].pk if (rows and more) else None,
                         "results": [{"id": m.pk, "from_member": not m.via_staff, "staff": public_name(m.sender) if m.via_staff else None,
                                      "content": m.content, "created_at": m.created_at, "state": messaging.state_of(m)} for m in rows]})


class ThreadReply(BOView):
    bo_permission = "messages.send"

    def post(self, request, pk):
        c = _thread(pk)
        member = next(iter(c.participants.all()), None) if c else None
        if c is None or member is None:
            return bad_request("not_found", "Conversation introuvable.", 404)
        try:
            message, _ = messaging.send(request.user, c, request.data.get("content", ""), via_staff=True, client_id=request.data.get("client_id") or None)
        except messaging.MessagingError as exc:
            return bad_request(exc.code, exc.detail, exc.status)
        audit_op(request, "message.reply", c, message=message.pk)
        return Response({"id": message.pk}, status=201)


class ThreadRead(BOView):
    bo_permission = "messages.send"

    def post(self, request, pk):
        c = _thread(pk)
        if c is None:
            return bad_request("not_found", "Conversation introuvable.", 404)
        return Response({"marked": c.messages.filter(is_read=False, via_staff=False).update(is_read=True)})
