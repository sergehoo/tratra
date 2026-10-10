from urllib.parse import parse_qs

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async

from handy.models import Booking
from live import realtime, services


class LiveConsumer(AsyncJsonWebsocketConsumer):
    """Flux temps réel d'une mission, en LECTURE SEULE pour le navigateur/l'appareil.

    Connexion : /ws/live/<booking_id>/?ticket=<billet> — le billet (60 s) est délivré par POST /live/ticket/ aux
    seuls participants. Les messages entrants sont ignorés (les positions passent par l'API REST validée)."""

    async def connect(self):
        self.group = None
        booking_id = int(self.scope["url_route"]["kwargs"]["booking_id"])
        query = parse_qs(self.scope.get("query_string", b"").decode())  # décode %3A etc. (billet encodé par le navigateur)
        ticket = (query.get("ticket") or [""])[0]
        parsed = realtime.read_ticket(ticket)
        if parsed is None or parsed[1] != booking_id:
            await self.close(code=4401)
            return
        user_id, _ = parsed
        role = await self._role(user_id, booking_id)
        if role is None:
            await self.close(code=4403)
            return
        self.group = realtime.group_name(booking_id, role)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        state = await self._state(user_id, booking_id)
        if state is not None:
            await self.send_json({"type": "state", "state": state})

    @database_sync_to_async
    def _role(self, user_id, booking_id):
        booking = Booking.objects.filter(pk=booking_id).first()
        return services.role_of(booking, realtime._User(user_id)) if booking else None

    @database_sync_to_async
    def _state(self, user_id, booking_id):
        booking = Booking.objects.filter(pk=booking_id).first()
        return realtime.jsonable(services.snapshot(booking, realtime._User(user_id))) if booking else None

    async def receive_json(self, content, **kwargs):
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def live_state(self, event):
        await self.send_json({"type": "state", "state": event["state"]})

    async def disconnect(self, code):
        if self.group:
            await self.channel_layer.group_discard(self.group, self.channel_name)
