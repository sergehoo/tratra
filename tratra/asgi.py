import os
from django.core.asgi import get_asgi_application
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tratra.settings")

# Initialise l'app Django d'abord (important si des apps touchent les URLs)
django_asgi_app = get_asgi_application()

# 👉 importe explicitement le sous-module routing de TON projet
from .routing import websocket_urlpatterns  # <— clé du fix

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})