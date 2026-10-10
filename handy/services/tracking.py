# handy/services/tracking.py
# Helper d'autorisation du suivi GPS, sans dépendance à `channels`
# (importable depuis les tests sans déclencher l'init de channels).
from django.db.models import Q

from handy.models import Booking


from handy.api.staff_access import staff_may


def can_access_booking_tracking(user, booking_id) -> bool:
    """Seuls le client et l'artisan de la réservation (ou le staff) peuvent
    suivre / émettre la position GPS d'une mission."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    # Positions GPS : jamais un passe-droit du personnel doté d'un rôle (le Back-Office a son accès motivé et audité) ;
    # seul le personnel historique sans rôle garde l'ancien comportement.
    if staff_may(user, None):
        return True
    return Booking.objects.filter(pk=booking_id).filter(
        Q(client=user) | Q(handyman=user)
    ).exists()
