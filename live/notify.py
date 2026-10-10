"""Notifications du suivi : in-app (fiable) + push mobile (best-effort, nécessite la configuration FCM)."""
import logging

from handy.models import Notification
from handy.tasks import _send_fcm

logger = logging.getLogger(__name__)


def _who(user) -> str:
    first = (user.first_name or "").strip()
    return first or "Votre artisan"


def notify_client(booking, kind: str) -> None:
    """kind : en_route | arrived."""
    texts = {
        "en_route": (f"{_who(booking.handyman)} est en route", "Suivez son arrivée en direct."),
        "arrived": (f"{_who(booking.handyman)} est arrivé", "Vérifiez son identité avec le QR de mission."),
    }
    title, body = texts[kind]
    Notification.objects.create(user=booking.client, notification_type=f"live_{kind}",
                                message=f"{title} — réservation #{booking.id}. {body}")
    try:
        _send_fcm(booking.client_id, title, body, {"t": "live", "id": booking.id, "k": kind})
    except Exception:  # push indisponible : la notification in-app est déjà créée
        logger.warning("Push suivi #%s non envoyé", booking.id, exc_info=True)
