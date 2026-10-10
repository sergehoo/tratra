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
    """Push mobile (FCM HTTP v1, appareils enregistrés via /devices/). Jamais bloquant : sans identifiants FCM ou sans
    appareil, rien n'est envoyé et aucune erreur n'est levée (la notification in-app reste la source fiable)."""
    try:
        send_push.apply_async(args=(user_id, title, body, data or {}), retry=False)
    except Exception:  # broker indisponible : envoi direct (best-effort)
        from handy import push
        push.send_to_user(user_id, title, body, data)


def _send_sms(msisdn, message):
    """Alertes SMS : best-effort (jamais bloquant). Fournisseur : handy/sms.py."""
    if not msisdn:
        return
    from . import sms
    try:
        sms.send_sms(msisdn, message)
    except sms.SMSError as exc:
        logger.warning("SMS non envoyé : %s", exc)


# ---------- Tâches ----------

@shared_task
def send_push(user_id, title, body, data=None):
    from handy import push
    return push.send_to_user(user_id, title, body, data)


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


# Libellés français (accordés avec « réservation ») : le code technique du statut ne doit jamais s'afficher.
BOOKING_STATUS_FR = {"pending": "en attente", "confirmed": "confirmée", "in_progress": "en cours",
                     "completed": "terminée", "cancelled": "annulée"}


@shared_task(max_retries=3, default_retry_delay=10)
def notify_booking_status(booking_id, status):
    """Notifie les DEUX parties d'un changement de statut :
    notification in-app fiable (DB) + push best-effort."""
    booking = (Booking.objects.filter(pk=booking_id)
               .select_related('client', 'handyman').first())
    if not booking:
        return
    label = BOOKING_STATUS_FR.get(status, status)
    msg = f"Statut de la réservation #{booking_id} : {label}"
    for user in (booking.client, booking.handyman):
        if not user:
            continue
        Notification.objects.create(
            user=user, notification_type='booking_status', message=msg,
        )
        _send_fcm(user.id, "Réservation", f"Statut : {label}",
                  {"t": "booking", "id": booking_id, "s": status})


@shared_task
def notify_arrival_imminent(user_id, booking_id):
    _send_sms(_resolve_msisdn(user_id), "Votre artisan arrive. Merci de vous préparer.")
