# routing.py
from django.urls import re_path

from handy.channels.consumers import TrackingConsumer

# from .consumers import TrackingConsumer
websocket_urlpatterns = [ re_path(r"ws/tracking/(?P<booking_id>\d+)/$", TrackingConsumer.as_asgi()), ]