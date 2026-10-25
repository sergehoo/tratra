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
    seule une notification « queued » est envoyée, et elle est d'abord RÉSERVÉE atomiquement (« queued » → « sending ») : deux
    exécutions de la même tâche (rejeu, double livraison par le broker, deux workers) ne peuvent pas envoyer deux fois.
    Réessaie (délai exponentiel) uniquement les échecs transitoires ; l'état d'envoi est consigné sur la notification."""
    from django.utils import timezone

    from handy import notifications, push

    n = Notification.objects.filter(pk=notification_id).first()
    if n is None or n.push_status != 'queued':
        return {"skipped": "already_processed"}
    if not Notification.objects.filter(pk=n.pk, push_status='queued').update(push_status='sending'):
        return {"skipped": "already_processed"}      # une autre exécution l'a réservée entre-temps
    if not notifications.push_enabled(n.user_id, n.category):
        Notification.objects.filter(pk=n.pk).update(push_status='disabled')
        return {"skipped": "disabled"}
    if n.notification_type in ("announcement", "campaign"):
        # Annonce annulée/expirée (ou campagne désactivée : son annonce support l'est aussi), ou promotion dont le consentement a été
        # retiré entre-temps : jamais de push.
        from announcements.models import Announcement

        a = Announcement.objects.filter(pk=(n.data or {}).get("id")).first()
        if a is None or a.status != "published" or (a.kind == "promotion" and not notifications.has_marketing_consent(n.user_id)):
            Notification.objects.filter(pk=n.pk).update(push_status='disabled')
            return {"skipped": "announcement_not_deliverable"}
    # Message de campagne = son annonce support pour l'application : « t » reste « announcement », seul type que le récepteur Android
    # affiche en message de données (FlashMessageReceiver) et que l'application compte comme ouvert — builds déjà installés compris.
    kind = "announcement" if n.notification_type == "campaign" else n.notification_type
    payload = {"t": kind, "cat": n.category, "nid": n.pk, "deeplink": notifications.deeplink(n.data), **(n.data or {})}
    title, body = notifications.push_text(n)          # texte neutre pour les catégories sensibles (écran verrouillé)
    ttl, extra = notifications.TTL_BY_CATEGORY.get(n.category, 86400), {}
    if n.notification_type in ("announcement", "campaign"):
        # Annonce (ou message de campagne, porté par son annonce support) : le toucher ouvre l'écran de son action (registre central) ; image 2:1 publique si disponible. Les appareils qui
        # savent construire l'alerte eux-mêmes (« rich1 » : grande image téléchargée, logo, bouton d'action) reçoivent un message de
        # DONNÉES ; les autres une notification classique avec la même image (affichée par Firebase).
        from announcements import push_image as announcement_image
        from announcements import services as announcement_services

        payload["deeplink"] = announcement_services.push_link(a)
        if a.action_kind == "deeplink" and a.action_label:
            payload["cta"] = a.action_label
        image = announcement_image.public_url(a)
        if image:
            payload["image"] = image
        extra = {"image": image, "data_only_capability": push.RICH_CAPABILITY}
    if n.notification_type == "new_mission":
        # Tratra Flash : jamais d'alerte pour une proposition déjà attribuée, retirée ou expirée ; durée de vie = délai de réponse restant.
        from flash.notify import FLASH_CAPABILITY, deliverable_ttl

        ttl = deliverable_ttl(n)
        if ttl is None:
            Notification.objects.filter(pk=n.pk).update(push_status='obsolete')
            return {"skipped": "obsolete"}
        extra = {"sound": notifications.FLASH_SOUND, "apns_category": notifications.FLASH_IOS_CATEGORY,
                 "data_only_capability": FLASH_CAPABILITY}
        payload["expires_in"] = ttl   # délai RELATIF à l'envoi : l'alerte se retire à l'échéance sans dépendre de l'horloge du téléphone
    result = push.send_to_user(
        n.user_id, title, body, payload,
        channel=notifications.CHANNEL_BY_CATEGORY.get(n.category), collapse_key=collapse_key,
        badge=notifications.unread_count(n.user_id), ttl_seconds=ttl,
        private=n.category in notifications.SENSITIVE_PUSH_CATEGORIES or n.category == "flash", **extra)
    if result["skipped"] == "not_configured":
        status = "unconfigured"
    elif result["sent"]:
        status = "sent"
    elif result["failed"]:
        if self.request.retries < self.max_retries:
            Notification.objects.filter(pk=n.pk, push_status='sending').update(push_status='queued')   # rendue au prochain essai
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



# ---------- Éligibilité et notifications : maintenance ----------

@shared_task(ignore_result=True)
def reconcile_published():
    """Filet de sécurité de la copie calculée de l'éligibilité : recalcule les profils dont la publication diffère de la règle.
    Un écart est anormal (un chemin de modification n'a pas recalculé) : il est corrigé ET signalé dans le journal."""
    from handy import eligibility

    changed = eligibility.refresh_published()
    if changed:
        logger.warning("Éligibilité : %s profil(s) corrigé(s) par la réconciliation (chemin de modification sans recalcul).", changed)
    return {"changed": changed}


@shared_task(ignore_result=True)
def purge_notifications():
    """Rétention des notifications (NOTIFICATION_RETENTION_DAYS, désactivée par défaut) : purge par lots, catégories protégées."""
    from handy import notifications

    return notifications.purge()
