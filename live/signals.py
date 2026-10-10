from django.db.models.signals import post_save
from django.dispatch import receiver

from handy.models import Booking
from live import realtime, services


@receiver(post_save, sender=Booking, dispatch_uid="live_booking_saved")
def booking_changed(sender, instance, created, **kwargs):
    """Changement de statut de la réservation : fin des partages à la clôture, état poussé aux deux participants."""
    if kwargs.get("raw") or created:
        return
    if instance.status in ("completed", "cancelled"):
        services.end_session(instance)
    if instance.status in ("confirmed", "in_progress", "completed", "cancelled"):
        realtime.broadcast(instance)
