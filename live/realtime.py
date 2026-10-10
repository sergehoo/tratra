"""Diffusion temps réel (Channels) : chaque participant reçoit SON instantané, jamais celui de l'autre.

Le canal temps réel n'est qu'un confort : toute la logique d'autorisation est dans live.services et le client
retombe sur une lecture périodique de GET /live/ si la connexion est perdue (réseau, Redis indisponible)."""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core import signing
from django.core.serializers.json import DjangoJSONEncoder
import json

from live import services

logger = logging.getLogger(__name__)
TICKET_SALT = "live-ws-ticket"
TICKET_MAX_AGE = 60  # secondes


def group_name(booking_id: int, role: str) -> str:
    return f"live_{booking_id}_{role}"


def make_ticket(user_id: int, booking_id: int) -> str:
    """Billet signé à courte durée : évite de placer un jeton d'accès dans l'URL de la WebSocket."""
    return signing.dumps({"u": user_id, "b": booking_id}, salt=TICKET_SALT)


def read_ticket(ticket: str):
    try:
        data = signing.loads(ticket, salt=TICKET_SALT, max_age=TICKET_MAX_AGE)
        return int(data["u"]), int(data["b"])
    except Exception:
        return None


def jsonable(payload):
    return json.loads(json.dumps(payload, cls=DjangoJSONEncoder))


def broadcast(booking) -> None:
    """Envoie l'état courant aux deux participants (silencieusement ignoré si la couche de canaux est absente)."""
    layer = get_channel_layer()
    if layer is None:
        return
    for user_id, role in ((booking.handyman_id, "artisan"), (booking.client_id, "client")):
        try:
            state = jsonable(services.snapshot(booking, _User(user_id)))
            async_to_sync(layer.group_send)(group_name(booking.id, role), {"type": "live.state", "state": state})
        except Exception:  # Redis coupé, etc. : l'action métier ne doit jamais échouer à cause du temps réel
            logger.warning("Diffusion du suivi #%s impossible (%s)", booking.id, role, exc_info=True)


class _User:
    """Utilisateur minimal pour calculer l'instantané d'un participant."""
    is_authenticated = True

    def __init__(self, pk):
        self.id = self.pk = pk
