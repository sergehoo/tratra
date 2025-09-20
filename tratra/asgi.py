# tratra/asgi.py
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tratra.settings")

# 1) Always build plain Django HTTP app first
django_asgi_app = get_asgi_application()

# 2) Start with HTTP only; add WS lazily
application = ProtocolTypeRouter({
    "http": django_asgi_app,
})

# 3) Lazily attach websocket router so a bad import doesn't kill ASGI
def _attach_websocket(application):
    try:
        from channels.auth import AuthMiddlewareStack
        from channels.routing import URLRouter
        # Import your patterns lazily to avoid crashing at module import time
        from tratra.routing import websocket_urlpatterns  # adjust path if needed

        application.application_mapping["websocket"] = AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns or [])
        )
    except Exception as e:
        # Optional: log to stderr on boot; HTTP will still run
        import sys
        print(f"[asgi] Websocket stack not attached: {e}", file=sys.stderr)

_attach_websocket(application)

# #/Users/ogahserge/Documents/tratra/tratra/asgi.py
# import os
# from django.core.asgi import get_asgi_application
# from channels.auth import AuthMiddlewareStack
# from channels.routing import ProtocolTypeRouter, URLRouter
#
# os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tratra.settings")
#
# # Initialise l'app Django d'abord (important si des apps touchent les URLs)
# django_asgi_app = get_asgi_application()
#
# # 👉 importe explicitement le sous-module routing de TON projet
# from .routing import websocket_urlpatterns  # <— clé du fix
#
# application = ProtocolTypeRouter({
#     "http": django_asgi_app,
#     "websocket": AuthMiddlewareStack(
#         URLRouter(websocket_urlpatterns)
#     ),
# })