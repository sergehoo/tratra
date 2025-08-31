from celery import shared_task
from django.utils import timezone
from .models import HandymanProfile, Notification


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
def notify_booking_status(user_id, booking_id, status):
    _send_fcm(user_id, "Réservation", f"Statut: {status}", {"t":"booking","id":booking_id,"s":status})

@shared_task
def notify_arrival_imminent(user_id, booking_id):
    _send_sms(_resolve_msisdn(user_id), "Votre artisan arrive. Merci de vous préparer.")