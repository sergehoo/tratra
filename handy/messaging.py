"""Messagerie interne : conversations privées uniques, messages persistants (texte et médias validés), états d'envoi/lecture,
non-lus, blocage, signalement, synchronisation après coupure. UNIQUE point d'écriture : l'API REST, le Back-Office et le WebSocket
passent par ici (autorisations, idempotence, diffusion) — le frontend n'est jamais cru sur parole.

États d'un message : `sent` (enregistré par le serveur) → `delivered` (reçu par l'appareil du destinataire) → `read` (lu).
Blocage : plus d'écriture dans les deux sens et conversation masquée ; le membre bloqué n'est pas prévenu du motif."""
import logging
import uuid
from typing import Dict, Iterable, List, Optional, Tuple

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Count, DateTimeField, F, Q, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from handy import contacts, inbox
from handy.media.validate import MediaRejected, check_upload
from handy.models import Conversation, Message, Report, UserBlock

logger = logging.getLogger(__name__)
User = get_user_model()

STAFF_LABEL = "Équipe Tratra"
KIND_PREVIEW = {Message.IMAGE: "📷 Photo", Message.VIDEO: "🎥 Vidéo", Message.FILE: "📄 Document"}


class MessagingError(Exception):
    def __init__(self, code: str, detail: str, status: int = 400):
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def _setting(name: str, default):
    return getattr(settings, name, default)


# ------------------------------------------------------------------------------------------------------ présentation

def display_name(user) -> str:
    from handy.api.serializers import public_display_name

    return public_display_name(user) if user is not None else "Membre Tratra"


def preview_of(message: Message) -> str:
    text = (message.content or "").strip().replace("\n", " ")
    if message.kind != Message.TEXT:
        label = KIND_PREVIEW.get(message.kind, "Pièce jointe")
        text = f"{label} {text}".strip()
    return text if len(text) <= 90 else text[:87] + "…"


def media_url(field, request=None) -> Optional[str]:
    from handy.api.serializers import absolute_media_url

    url = absolute_media_url(request, field) if request is not None else None
    if url:
        return url
    try:
        raw = field.url
    except (ValueError, NotImplementedError):
        return None
    base = str(_setting("API_PUBLIC_URL", "")).rstrip("/")
    return raw if raw.startswith(("http://", "https://")) or not base else base + raw


def state_of(message: Message) -> str:
    return "read" if message.read_at else ("delivered" if message.delivered_at else "sent")


def message_payload(message: Message, viewer_id: int, request=None) -> Dict:
    sender_label = STAFF_LABEL if message.via_staff else display_name(message.sender)
    out = {
        "id": message.id, "conversation": message.conversation_id, "mine": message.sender_id == viewer_id, "content": message.content,
        "kind": message.kind, "created_at": message.created_at.isoformat(), "is_read": message.is_read, "state": state_of(message),
        "client_id": str(message.client_id) if message.client_id else None, "sender": sender_label, "via_staff": message.via_staff,
        "attachment": None, "context": message.context or None,
    }
    if message.attachment:
        out["attachment"] = {"url": media_url(message.attachment, request), "kind": message.kind, "mime": message.attachment_mime,
                             "size": message.attachment_size, "name": message.attachment_name, **(message.attachment_meta or {})}
    return out


def _counterpart(conv: Conversation, user_id: int):
    others = [p for p in conv.participants.all() if p.pk != user_id]
    return others[0] if others else None


def conversation_payload(conv: Conversation, viewer_id: int, *, unread: Optional[int] = None, blocked_ids: Optional[set] = None) -> Dict:
    other = _counterpart(conv, viewer_id)
    if unread is None:
        unread = conv.messages.filter(is_read=False).exclude(sender_id=viewer_id).count()
    blocked_ids = contacts.blocked_ids(viewer_id) if blocked_ids is None else blocked_ids
    support = conv.kind == Conversation.SUPPORT
    return {
        "id": conv.id, "kind": conv.kind, "booking_id": conv.booking_id,
        "counterpart": STAFF_LABEL if support else (display_name(other) if other else "Membre Tratra"),
        "counterpart_id": None if support else (other.pk if other else None),
        "last_message": (conv.last_message_preview or None), "last_at": (conv.last_message_at or conv.updated_at).isoformat(),
        "unread": unread, "blocked": bool(other and other.pk in blocked_ids),
        "can_send": not (other and other.pk in blocked_ids),
    }


# ------------------------------------------------------------------------------------------------ conversations

def conversations_for(user, q: str = ""):
    """Conversations de l'utilisateur avec leur compteur de non-lus (une seule requête) ; un fil privé sans message n'est pas listé."""
    qs = (Conversation.objects.filter(participants=user).prefetch_related("participants")
          .annotate(unread_count=Count("messages", filter=Q(messages__is_read=False) & ~Q(messages__sender=user), distinct=True)))
    qs = qs.exclude(Q(kind=Conversation.DIRECT, last_message_at__isnull=True))
    q = (q or "").strip()
    if q:
        names = User.objects.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q)).exclude(pk=user.pk)
        by_name = Conversation.objects.filter(participants__in=names).values("pk")
        by_text = Message.objects.filter(conversation__participants=user, content__icontains=q).values("conversation_id")
        qs = qs.filter(Q(pk__in=by_name) | Q(pk__in=by_text))
    return qs.order_by(F("last_message_at").desc(nulls_last=True), "-id")


def unread_total(user) -> int:
    return Message.objects.filter(conversation__participants=user, is_read=False).exclude(sender=user).count()


def _participant_conversation(user, conversation_id: int) -> Conversation:
    conv = Conversation.objects.filter(pk=conversation_id, participants=user).prefetch_related("participants").first()
    if conv is None:
        raise MessagingError("not_found", "Conversation introuvable.", 404)
    return conv


get_conversation = _participant_conversation


def open_direct(user, other_id: int, *, allow_stranger: bool = False) -> Tuple[Conversation, bool]:
    """Fil privé UNIQUE entre deux membres (clé `pair_key`). Refusé : soi-même, compte inactif ou personnel, blocage, membre sans lien
    avec l'utilisateur qui n'est pas un prestataire publié, quota quotidien de nouvelles conversations."""
    other = User.objects.filter(pk=other_id, is_active=True, is_staff=False).first()
    if other is None or other.pk == user.pk:
        raise MessagingError("not_found", "Membre introuvable.", 404)
    if contacts.is_blocked(user.pk, other.pk):
        raise MessagingError("blocked", "Vous ne pouvez pas écrire à ce membre.", 403)
    key = f"{min(user.pk, other.pk)}:{max(user.pk, other.pk)}"
    existing = Conversation.objects.filter(pair_key=key).first()
    if existing is not None:
        return existing, False
    from handy.eligibility import is_user_publishable

    if not allow_stranger and other.pk not in contacts.contact_ids(user.pk) and not is_user_publishable(other):
        raise MessagingError("not_reachable", "Ce membre n'est pas joignable directement : passez par une réservation.", 403)
    day_key = f"msg:newconv:{user.pk}:{timezone.localdate().isoformat()}"
    cache.add(day_key, 0, 90000)
    if cache.incr(day_key) > int(_setting("MESSAGE_NEW_CONVERSATIONS_PER_DAY", 20)):
        raise MessagingError("quota", "Limite quotidienne de nouvelles conversations atteinte. Réessayez demain.", 429)
    try:
        with transaction.atomic():
            conv = Conversation.objects.create(kind=Conversation.DIRECT, pair_key=key)
            conv.participants.set([user, other])
    except IntegrityError:  # course : l'autre membre vient de créer le même fil
        return Conversation.objects.get(pair_key=key), False
    return conv, True


def support_conversation(recipient) -> Conversation:
    """Fil « Équipe Tratra » du membre : unique, jamais partagé avec un autre destinataire."""
    key = f"support:{recipient.pk}"
    try:
        with transaction.atomic():
            conv, created = Conversation.objects.get_or_create(pair_key=key, defaults={"kind": Conversation.SUPPORT})
            if created:
                conv.participants.set([recipient])
    except IntegrityError:
        conv = Conversation.objects.get(pair_key=key)
    return conv


# ---------------------------------------------------------------------------------------------------------- envoi

def _validate_upload(upload):
    try:
        return check_upload(
            upload, allow=("image", "video", "file"),
            max_image_bytes=int(_setting("MESSAGE_MAX_IMAGE_BYTES", 10 * 1024 * 1024)),
            max_video_bytes=int(_setting("MESSAGE_MAX_VIDEO_BYTES", 25 * 1024 * 1024)),
            max_file_bytes=int(_setting("MESSAGE_MAX_FILE_BYTES", 10 * 1024 * 1024)),
            max_video_seconds=float(_setting("MESSAGE_MAX_VIDEO_SECONDS", 60)))
    except MediaRejected as exc:
        raise MessagingError(exc.code, exc.detail, 413 if exc.code == "too_large" else 400)


def send(user, conversation: Conversation, content: str = "", *, upload=None, client_id=None, via_staff: bool = False,
         attachment_name: str = "", context: Optional[dict] = None) -> Tuple[Message, bool]:
    """Enregistre un message. Idempotent sur `client_id` : un renvoi (réseau coupé) renvoie le message existant (created=False)."""
    content = (content or "").strip()
    max_chars = int(_setting("MESSAGE_MAX_CHARS", 4000))
    if len(content) > max_chars:
        raise MessagingError("too_long", f"Message trop long : {max_chars} caractères au maximum.")
    if not content and upload is None:
        raise MessagingError("empty", "Le message est vide.")
    if client_id is not None:
        try:
            client_id = uuid.UUID(str(client_id))
        except ValueError:
            raise MessagingError("invalid_client_id", "Identifiant d'envoi invalide.")
        previous = Message.objects.filter(conversation=conversation, sender=user, client_id=client_id).first()
        if previous is not None:
            return previous, False
    if not via_staff:
        if not conversation.participants.filter(pk=user.pk).exists():
            raise MessagingError("not_found", "Conversation introuvable.", 404)
        if conversation.kind != Conversation.SUPPORT:
            for other in conversation.participants.exclude(pk=user.pk):
                if contacts.is_blocked(user.pk, other.pk):
                    raise MessagingError("blocked", "Ce message ne peut pas être envoyé à ce membre.", 403)
    fields = dict(conversation=conversation, sender=user, content=content, client_id=client_id, via_staff=via_staff, context=context or {})
    if upload is not None:
        checked = _validate_upload(upload)
        fields.update(kind=checked.kind, attachment_mime=checked.mime, attachment_size=checked.size, attachment_meta=checked.meta,
                      attachment_name=(attachment_name or getattr(upload, "name", "") or "")[:120])
    message = Message(**fields)
    if upload is not None:
        message.attachment.save(checked.content.name, checked.content, save=False)
    try:
        with transaction.atomic():
            message.save()
    except IntegrityError:                                    # course sur le même `client_id` : l'autre requête a gagné
        if message.attachment:
            message.attachment.delete(save=False)
        existing = Message.objects.filter(conversation=conversation, sender=user, client_id=client_id).first()
        if existing is None:
            raise
        return existing, False
    return message, True


def on_message_created(message: Message) -> None:
    """Après la création (tout chemin : API, Back-Office, admin Django) : aperçu de la conversation puis diffusion temps réel."""
    conv = message.conversation
    Conversation.objects.filter(pk=conv.pk).update(last_message_at=message.created_at, last_message_preview=preview_of(message)[:160],
                                                    updated_at=timezone.now())
    contacts.invalidate(message.sender_id, *conv.participants.values_list("pk", flat=True))
    transaction.on_commit(lambda: broadcast_message(message.pk))


def broadcast_message(message_id: int) -> None:
    message = Message.objects.select_related("conversation", "sender").filter(pk=message_id).first()
    if message is None:
        return
    conv = message.conversation
    blocked_cache: Dict[int, set] = {}
    for uid in conv.participants.values_list("pk", flat=True):
        blocked_cache[uid] = contacts.blocked_ids(uid)
        inbox.push([uid], {"type": "message", "message": message_payload(message, uid),
                           "conversation": conversation_payload(conv, uid, blocked_ids=blocked_cache[uid]),
                           "unread_total": unread_total_for_id(uid)})


def unread_total_for_id(user_id: int) -> int:
    return Message.objects.filter(conversation__participants=user_id, is_read=False).exclude(sender_id=user_id).count()


# ------------------------------------------------------------------------------------------- lecture / distribution

def mark_read(user, conversation: Conversation) -> int:
    """Marque lus les messages REÇUS (jamais les siens ni ceux d'une autre conversation), puis prévient les expéditeurs."""
    now = timezone.now()
    qs = conversation.messages.filter(is_read=False).exclude(sender=user)
    ids = list(qs.values_list("pk", flat=True))
    if not ids:
        return 0
    senders = set(Message.objects.filter(pk__in=ids).values_list("sender_id", flat=True))
    n = Message.objects.filter(pk__in=ids).update(is_read=True, read_at=now, delivered_at=Coalesce(F("delivered_at"), Value(now), output_field=DateTimeField()))
    # Les EXPÉDITEURS voient leurs messages passer à « lu » ; le LECTEUR (et ses autres appareils) reçoit seulement un évènement de
    # synchronisation des non-lus : jamais l'évènement « lu », qui ferait passer ses PROPRES messages à « lu ».
    inbox.push(senders - {user.pk}, {"type": "read", "conversation": conversation.pk, "reader": user.pk, "upto": max(ids), "count": n,
                                      "at": now.isoformat()})
    inbox.push([user.pk], {"type": "read_self", "conversation": conversation.pk, "count": n, "unread_total": unread_total(user)})
    return n


def mark_delivered(user, message_ids: Iterable[int]) -> int:
    """L'appareil du destinataire confirme la réception. Seuls ses messages reçus sont concernés."""
    ids = [int(i) for i in message_ids][:500]
    if not ids:
        return 0
    now = timezone.now()
    qs = (Message.objects.filter(pk__in=ids, conversation__participants=user, delivered_at__isnull=True).exclude(sender=user))
    rows = list(qs.values_list("pk", "sender_id", "conversation_id"))
    if not rows:
        return 0
    Message.objects.filter(pk__in=[r[0] for r in rows]).update(delivered_at=now)
    by_sender: Dict[int, List[int]] = {}
    for pk, sender_id, _ in rows:
        by_sender.setdefault(sender_id, []).append(pk)
    for sender_id, mids in by_sender.items():
        inbox.push([sender_id], {"type": "delivered", "ids": mids, "at": now.isoformat()})
    return len(rows)


def sync(user, after_id: int, limit: int = 200) -> Dict:
    """Rattrapage après coupure : messages (de TOUTES mes conversations) plus récents que `after_id`, marqués distribués."""
    limit = max(1, min(int(limit), 500))
    qs = (Message.objects.filter(conversation__participants=user, id__gt=after_id).select_related("sender", "conversation")
          .order_by("id")[:limit + 1])
    rows = list(qs)
    more = len(rows) > limit
    rows = rows[:limit]
    mark_delivered(user, [m.pk for m in rows if m.sender_id != user.pk])
    conv_ids = {m.conversation_id for m in rows}
    convs = {c.pk: c for c in Conversation.objects.filter(pk__in=conv_ids, participants=user).prefetch_related("participants")}
    blocked = contacts.blocked_ids(user.pk)
    return {"messages": [message_payload(m, user.pk) for m in rows], "has_more": more,
            "last_id": rows[-1].pk if rows else after_id, "unread_total": unread_total(user),
            "conversations": [conversation_payload(c, user.pk, blocked_ids=blocked) for c in convs.values()]}


def thread(user, conversation: Conversation, *, before: Optional[int] = None, limit: int = 50, q: str = "") -> Dict:
    """Page de messages (curseur `before` = id du plus ancien déjà affiché), du plus ancien au plus récent."""
    limit = max(1, min(int(limit or 50), 100))
    qs = conversation.messages.select_related("sender")
    if q.strip():
        qs = qs.filter(content__icontains=q.strip())
    if before:
        qs = qs.filter(pk__lt=before)
    rows = list(qs.order_by("-id")[:limit + 1])
    more = len(rows) > limit
    rows = list(reversed(rows[:limit]))
    return {"results": [message_payload(m, user.pk) for m in rows], "has_more": more, "next_before": rows[0].pk if (rows and more) else None}


def search_messages(user, q: str, limit: int = 30) -> List[Dict]:
    q = (q or "").strip()
    if len(q) < 2:
        return []
    qs = (Message.objects.filter(conversation__participants=user, content__icontains=q).select_related("conversation", "sender")
          .order_by("-id")[:min(limit, 50)])
    return [{"conversation": m.conversation_id, "message": m.pk, "snippet": m.content[:140], "created_at": m.created_at.isoformat(),
             "mine": m.sender_id == user.pk} for m in qs]


# ------------------------------------------------------------------------------------------- blocage / signalement

def block(user, other_id: int) -> UserBlock:
    other = User.objects.filter(pk=other_id).first()
    if other is None or other.pk == user.pk:
        raise MessagingError("not_found", "Membre introuvable.", 404)
    obj, _ = UserBlock.objects.get_or_create(blocker=user, blocked=other)
    contacts.invalidate(user.pk, other.pk)
    return obj


def unblock(user, other_id: int) -> int:
    n, _ = UserBlock.objects.filter(blocker=user, blocked_id=other_id).delete()
    contacts.invalidate(user.pk, other_id)
    return n


def report(user, conversation: Conversation, *, message_id: Optional[int], reason: str) -> Report:
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise MessagingError("reason_required", "Indiquez le motif du signalement.")
    msgs = conversation.messages.exclude(sender=user)
    msg = msgs.filter(pk=message_id).first() if message_id else msgs.order_by("-id").first()
    if msg is None:
        raise MessagingError("nothing_to_report", "Aucun message de l'autre membre à signaler.", 404)
    obj, _ = Report.objects.get_or_create(reporter=user, report_type="message", message=msg, defaults={"reason": reason[:2000]})
    return obj
