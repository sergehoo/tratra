# channels/consumers.py
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from django.contrib.gis.geos import Point
from handy.models import JobTracking

class TrackingConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.booking_id = self.scope["url_route"]["kwargs"]["booking_id"]
        await self.channel_layer.group_add(f"bk_{self.booking_id}", self.channel_name)
        await self.accept()

    @sync_to_async
    def _save_point(self, data):
        JobTracking.objects.create(
            booking_id=int(self.booking_id),
            handyman_id=data["handyman_id"],
            loc=Point(data["lng"], data["lat"]),
            speed=data.get("speed"), heading=data.get("heading")
        )

    async def receive_json(self, content, **kwargs):
        await self._save_point(content)
        await self.channel_layer.group_send(
            f"bk_{self.booking_id}", {"type":"loc.update","data":content}
        )

    async def loc_update(self, event): await self.send_json(event["data"])
    async def disconnect(self, code): await self.channel_layer.group_discard(f"bk_{self.booking_id}", self.channel_name)