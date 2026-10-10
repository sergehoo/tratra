"""Notifications du suivi : historique en base + push asynchrone (voir handy/notifications.py)."""
import logging

from handy.notifications import notify

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
    try:
        notify(booking.client_id, f"live_{kind}", f"{title} — réservation #{booking.id}. {body}", title=title,
               data={"kind": "booking", "id": booking.id, "audience": "client"}, dedupe_key=f"live:{booking.id}:{kind}",
               content_object=booking)
    except Exception:  # la mission continue même si la notification échoue
        logger.warning("Notification de suivi #%s non créée", booking.id, exc_info=True)
