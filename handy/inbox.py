"""Temps réel de la messagerie et des statuts : UNE connexion WebSocket par membre (`ws/inbox/`), groupe `inbox_<id>`.

Le WebSocket n'est qu'un confort : toute écriture passe par l'API REST (autorisations, idempotence), les messages sont persistés avant
toute diffusion, et le client retombe sur `GET /me/messages/sync/` si la connexion est perdue (Redis ou réseau indisponibles). La connexion
se fait avec un billet signé de 60 s (`POST /me/realtime/ticket/`) : aucun jeton d'accès dans l'URL."""
import json
import logging
from typing import Iterable

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core import signing
from django.core.serializers.json import DjangoJSONEncoder

logger = logging.getLogger(__name__)
TICKET_SALT = "inbox-ws-ticket"
TICKET_MAX_AGE = 60


def group_name(user_id: int) -> str:
    return f"inbox_{user_id}"


def make_ticket(user_id: int) -> str:
    return signing.dumps({"u": user_id}, salt=TICKET_SALT)


def read_ticket(ticket: str):
    try:
        return int(signing.loads(ticket, salt=TICKET_SALT, max_age=TICKET_MAX_AGE)["u"])
    except Exception:
        return None


def push(user_ids: Iterable[int], event: dict) -> None:
    """Diffuse un évènement à chaque membre (chacun ne reçoit que SA version). Jamais bloquant pour l'action métier."""
    layer = get_channel_layer()
    if layer is None:
        return
    payload = json.loads(json.dumps(event, cls=DjangoJSONEncoder))
    for uid in set(user_ids):
        try:
            async_to_sync(layer.group_send)(group_name(uid), {"type": "inbox.event", "event": payload})
        except Exception:  # Redis coupé, etc.
            logger.warning("Diffusion temps réel impossible pour le membre #%s", uid, exc_info=True)
