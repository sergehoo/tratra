from django.urls import re_path

from handy import consumers
from live import consumers as live_consumers

websocket_urlpatterns = [
    re_path(r'ws/chat/(?P<conversation_id>\d+)/$', consumers.ChatConsumer.as_asgi()),
    # Suivi GPS en direct d'une mission (Tratra Live) : lecture seule, billet signé délivré aux seuls participants.
    # (L'ancien flux ws/track/, qui laissait n'importe quel participant diffuser une position, est retiré.)
    re_path(r'ws/live/(?P<booking_id>\d+)/$', live_consumers.LiveConsumer.as_asgi()),
]