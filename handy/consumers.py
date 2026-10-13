"""WebSockets de la messagerie : UNE connexion par membre (`/ws/inbox/?ticket=`) qui reçoit messages, accusés (distribué/lu), compteurs
et évènements de statuts. Lecture seule pour l'essentiel : les écritures passent par l'API REST (autorisations, idempotence, médias).
Le client peut seulement envoyer `ping` et accuser réception (`ack`). `/ws/chat/<id>/` reste disponible (même billet) pour une
conversation précise : accès refusé à tout membre non participant."""
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from handy import inbox, messaging
from handy.models import Conversation


class InboxConsumer(AsyncJsonWebsocketConsumer):
    conversation_id = None

    async def connect(self):
        self.group = None
        query = parse_qs(self.scope.get("query_string", b"").decode())
        user_id = inbox.read_ticket((query.get("ticket") or [""])[0])
        if user_id is None:
            await self.close(code=4401)
            return
        self.user_id = user_id
        if self.conversation_id is not None and not await self._participates(user_id, self.conversation_id):
            await self.close(code=4403)
            return
        self.group = inbox.group_name(user_id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send_json({"type": "ready", "unread_total": await self._unread(user_id)})

    @database_sync_to_async
    def _participates(self, user_id, conversation_id):
        return Conversation.objects.filter(pk=conversation_id, participants=user_id).exists()

    @database_sync_to_async
    def _unread(self, user_id):
        return messaging.unread_total_for_id(user_id)

    @database_sync_to_async
    def _ack(self, user_id, ids):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(pk=user_id).first()
        return messaging.mark_delivered(user, ids) if user else 0

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            return
        kind = content.get("type")
        if kind == "ping":
            await self.send_json({"type": "pong"})
        elif kind == "ack" and isinstance(content.get("ids"), list):
            try:
                await self._ack(self.user_id, content["ids"])
            except (TypeError, ValueError):
                pass

    async def inbox_event(self, event):
        payload = event["event"]
        if self.conversation_id is not None and payload.get("type") in ("message", "read"):
            conv = payload.get("conversation")
            conv_id = conv.get("id") if isinstance(conv, dict) else conv
            if conv_id != self.conversation_id:
                return
        await self.send_json(payload)

    async def disconnect(self, code):
        if getattr(self, "group", None):
            await self.channel_layer.group_discard(self.group, self.channel_name)


class ChatConsumer(InboxConsumer):
    """Flux d'UNE conversation (même billet que l'inbox) ; refusé si le membre n'en est pas participant."""

    async def connect(self):
        self.conversation_id = int(self.scope["url_route"]["kwargs"]["conversation_id"])
        await super().connect()
