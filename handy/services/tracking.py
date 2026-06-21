# handy/services/tracking.py
# Helper d'autorisation du suivi GPS, sans dépendance à `channels`
# (importable depuis les tests sans déclencher l'init de channels).
from django.db.models import Q

from handy.models import Booking


def can_access_booking_tracking(user, booking_id) -> bool:
    """Seuls le client et l'artisan de la réservation (ou le staff) peuvent
    suivre / émettre la position GPS d'une mission."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False):
        return True
    return Booking.objects.filter(pk=booking_id).filter(
        Q(client=user) | Q(handyman=user)
    ).exists()
