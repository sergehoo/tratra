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


@shared_task(bind=True, max_retries=3)
def send_notification_push(self, notification_id, collapse_key=None):
    """Diffuse UNE notification enregistrée sur tous les appareils du compte (FCM), de façon idempotente :
    seule une notification « queued » est envoyée, donc un rejeu de la tâche ne duplique jamais le push.
    Réessaie (délai exponentiel) uniquement les échecs transitoires ; l'état d'envoi est consigné sur la notification."""
    from django.utils import timezone

    from handy import notifications, push

    n = Notification.objects.filter(pk=notification_id).first()
    if n is None or n.push_status != 'queued':
        return {"skipped": "already_processed"}
    if not notifications.push_enabled(n.user_id, n.category):
        Notification.objects.filter(pk=n.pk).update(push_status='disabled')
        return {"skipped": "disabled"}
    if n.notification_type == "announcement":
        # Annonce annulée/expirée, ou promotion dont le consentement a été retiré entre-temps : jamais de push.
        from announcements.models import Announcement

        a = Announcement.objects.filter(pk=(n.data or {}).get("id")).first()
        if a is None or a.status != "published" or (a.kind == "promotion" and not notifications.has_marketing_consent(n.user_id)):
            Notification.objects.filter(pk=n.pk).update(push_status='disabled')
            return {"skipped": "announcement_not_deliverable"}
    payload = {"t": n.notification_type, "cat": n.category, "nid": n.pk, "deeplink": notifications.deeplink(n.data), **(n.data or {})}
    title, body = notifications.push_text(n)          # texte neutre pour les catégories sensibles (écran verrouillé)
    result = push.send_to_user(
        n.user_id, title, body, payload,
        channel=notifications.CHANNEL_BY_CATEGORY.get(n.category), collapse_key=collapse_key,
        badge=notifications.unread_count(n.user_id), ttl_seconds=notifications.TTL_BY_CATEGORY.get(n.category, 86400),
        private=n.category in notifications.SENSITIVE_PUSH_CATEGORIES)
    if result["skipped"] == "not_configured":
        status = "unconfigured"
    elif result["sent"]:
        status = "sent"
    elif result["failed"]:
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30 * (2 ** self.request.retries))
        status = "failed"
    elif result["skipped"] in ("no_device",) or result["removed"]:
        status = "no_device"
    else:
        status = "failed"
    Notification.objects.filter(pk=n.pk).update(
        push_status=status, push_sent_at=timezone.now() if status == "sent" else None)
    return {**result, "status": status}


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
def notify_booking_status(booking_id, status, actor_id=None):
    """Notifie le changement de statut (historique en base + push asynchrone) : voir handy/notification_events.py.
    L'auteur de l'action (`actor_id`) n'est jamais notifié de sa propre action."""
    from handy.notification_events import booking_status_changed

    booking = (Booking.objects.filter(pk=booking_id).select_related('client', 'handyman', 'service').first())
    if booking:
        booking_status_changed(booking, status, actor_id)


@shared_task
def notify_arrival_imminent(user_id, booking_id):
    _send_sms(_resolve_msisdn(user_id), "Votre artisan arrive. Merci de vous préparer.")


# ---------- Paiements : réconciliation avec les prestataires ----------

RECONCILE_MIN_AGE_S = 60              # laisse au client le temps de payer avant la première vérification
RECONCILE_MAX_AGE_H = 72              # au-delà, une transaction restée « en attente » est laissée à l'examen du Back-Office
RECONCILE_BATCH = 200


@shared_task
def reconcile_provider_payments():
    """Filet de sécurité des webhooks perdus, tardifs ou impossibles à signer (Orange, MTN) : interroge le prestataire pour chaque
    paiement en attente et applique SEULEMENT ce que la vérification serveur-à-serveur établit. Un prestataire non configuré ou
    injoignable ne change rien (rejoué au prochain passage). Rejouable sans effet double."""
    from datetime import timedelta

    from django.utils import timezone

    from handy.models import Payment
    from handy.services import settlement
    from handy.services.gateway import PROVIDER_METHODS, PaymentProviderError, PaymentProviderUnavailable

    now = timezone.now()
    ids = list(Payment.objects.filter(status="pending", method__in=PROVIDER_METHODS, transaction_id__isnull=False,
                                      created_at__lte=now - timedelta(seconds=RECONCILE_MIN_AGE_S),
                                      created_at__gte=now - timedelta(hours=RECONCILE_MAX_AGE_H))
               .order_by("provider_checked_at", "id").values_list("pk", flat=True)[:RECONCILE_BATCH])
    done = {"checked": 0, "settled": 0, "unavailable": 0}
    for pk in ids:
        try:
            result = settlement.settle(pk, source="reconcile")
        except (PaymentProviderUnavailable, PaymentProviderError):
            done["unavailable"] += 1
            continue
        except Exception:    # noqa: BLE001 — un paiement en défaut ne doit pas bloquer les suivants
            logger.warning("Réconciliation du paiement #%s impossible.", pk, exc_info=True)
            continue
        done["checked"] += 1
        done["settled"] += int(result.get("state") in ("completed", "failed", "refunded"))
    return done

