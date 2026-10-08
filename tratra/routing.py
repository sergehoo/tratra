from django.urls import re_path

from handy import consumers
from handy.channels import consumers as tracking_consumers

websocket_urlpatterns = [
    re_path(r'ws/chat/(?P<conversation_id>\d+)/$', consumers.ChatConsumer.as_asgi()),
    # Suivi GPS temps réel d'une mission (autorisation dans le consumer).
    re_path(r'ws/track/(?P<booking_id>\d+)/$', tracking_consumers.TrackingConsumer.as_asgi()),
]