import logging

from celery import shared_task
from django.contrib.auth import get_user_model

from .models import HandymanProfile, Notification, Booking

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------- Canaux d'envoi (best-effort, jamais bloquants) ----------

def _resolve_msisdn(user_id):
    """Numéro E.164 de l'utilisateur (None si absent)."""
    user = User.objects.filter(pk=user_id).first()
    return getattr(user, 'phone', None) if user else None


def _send_fcm(user_id, title, body, data=None):
    """Push via django-push-notifications. No-op gracieux si non configuré
    (pas de credentials FCM) ou si l'utilisateur n'a aucun device actif."""
    try:
        from push_notifications.models import GCMDevice
        devices = GCMDevice.objects.filter(user_id=user_id, active=True)
        if devices.exists():
            devices.send_message(body, title=title, extra=data or {})
    except Exception:
        logger.warning("Push FCM non envoyé (non configuré ou erreur).", exc_info=True)


def _send_sms(msisdn, message):
    """Envoi SMS — stub journalisé. TODO(prod): brancher un provider (Orange/Twilio)."""
    if not msisdn:
        return
    logger.info("SMS (stub) -> %s : %s", msisdn, message)


# ---------- Tâches ----------

@shared_task
def send_profile_completion_reminders():
    profiles = HandymanProfile.objects.filter(is_approved=True)
    for profile in profiles:
        if profile.profile_completion() < 100:
            Notification.objects.create(
                user=profile.user,
                notification_type='profile_incomplete',
                message=f"Votre profil n'est complété qu'à {profile.profile_completion()}%. "
                        f"Complétez-le pour apparaître dans les recommandations."
            )


@shared_task(max_retries=3, default_retry_delay=10)
def notify_booking_status(booking_id, status):
    """Notifie les DEUX parties d'un changement de statut :
    notification in-app fiable (DB) + push best-effort."""
    booking = (Booking.objects.filter(pk=booking_id)
               .select_related('client', 'handyman').first())
    if not booking:
        return
    msg = f"Statut de la réservation #{booking_id} : {status}"
    for user in (booking.client, booking.handyman):
        if not user:
            continue
        Notification.objects.create(
            user=user, notification_type='booking_status', message=msg,
        )
        _send_fcm(user.id, "Réservation", f"Statut: {status}",
                  {"t": "booking", "id": booking_id, "s": status})


@shared_task
def notify_arrival_imminent(user_id, booking_id):
    _send_sms(_resolve_msisdn(user_id), "Votre artisan arrive. Merci de vous préparer.")
