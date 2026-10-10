import logging

from django.db import models
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from handy.media.sanitize import sanitize_new_upload
from handy.models import (
    ServiceImage, User, HandymanProfile, Review, Booking, CompanyProfile, Service, ReviewMedia,
)
from handy.tasks import notify_booking_status
logger = logging.getLogger(__name__)


# Images servies publiquement : tout NOUVEL envoi est réencodé sans métadonnées
# (EXIF/GPS), quel que soit le chemin (API, admin Django, commande). L'API valide
# et réencode déjà en amont (PublicImageField) : le fichier marqué n'est pas
# retraité ; un fichier déjà en base n'est jamais relu.
PUBLIC_IMAGE_FIELDS = {
    ServiceImage: ("image",),
    Service: ("banner",),
    ReviewMedia: ("image",),
    HandymanProfile: ("photo",),
    User: ("profile_picture",),
}


def sanitize_public_images(sender, instance, **kwargs):
    if kwargs.get("raw"):  # chargement de fixtures : données telles quelles
        return
    update_fields = kwargs.get("update_fields")
    for field_name in PUBLIC_IMAGE_FIELDS.get(sender, ()):
        if update_fields is not None and field_name not in update_fields:
            continue
        sanitize_new_upload(instance, field_name)


for _model in PUBLIC_IMAGE_FIELDS:
    pre_save.connect(sanitize_public_images, sender=_model,
                     dispatch_uid=f"handy_sanitize_public_images_{_model.__name__}")

@receiver(post_save, sender=User)
def create_handyman_profile(sender, instance, created, **kwargs):
    if created and instance.user_type == 'handyman':
        # Vérifie qu'il n'existe pas déjà un profil
        HandymanProfile.objects.get_or_create(user=instance)


@receiver(post_save, sender=User)
def create_company_profile(sender, instance, created, **kwargs):
    if created and instance.user_type == 'entreprise':
        CompanyProfile.objects.get_or_create(
            user=instance,
            defaults={'company_name': instance.get_full_name() or instance.username},
        )


@receiver(post_delete, sender=ServiceImage)
def delete_service_image_file(sender, instance, **kwargs):
    if instance.image:
        instance.image.delete(False)


def refresh_handyman_rating(handyman_id):
    """Note = moyenne des avis RETENUS de l'artisan : missions terminées, non masqués, un avis par client
    (le plus récent) — handy/reviews.py ; même règle que les statistiques publiques."""
    if not handyman_id:
        return
    from handy.reviews import review_stats

    average = review_stats(handyman_id)["average"] or 0
    HandymanProfile.objects.filter(user_id=handyman_id).update(rating=average)
    profile = HandymanProfile.objects.filter(user_id=handyman_id).first()
    if profile:
        profile.refresh_quality_score()


@receiver(post_save, sender=Review)
def update_rating_on_review(sender, instance: Review, created, **kwargs):
    # Création ET modification : l'auteur peut corriger sa note.
    refresh_handyman_rating(instance.booking.handyman_id)


@receiver(post_delete, sender=Review)
def update_rating_on_review_delete(sender, instance: Review, **kwargs):
    # La réservation peut être en cours de suppression (cascade) : lecture défensive.
    handyman_id = (Booking.objects.filter(pk=instance.booking_id)
                   .values_list('handyman_id', flat=True).first())
    refresh_handyman_rating(handyman_id)

# NB: l'incrément de completed_jobs est désormais géré de façon IDEMPOTENTE
# dans Booking.transition_to() (uniquement à l'entrée dans 'completed').
# L'ancien signal post_save incrémentait à CHAQUE sauvegarde -> double comptage. Supprimé.


@receiver(post_save, sender=Booking)
def on_booking_status_change(sender, instance: Booking, created: bool, **kwargs):
    # Ne pas notifier à la création si ce n'est pas utile
    if created:
        return

    if notify_booking_status:
        try:
            # retry=False : sans broker joignable (dev, panne), échec immédiat et journalisé au lieu de
            # ~10 s d'attente par changement de statut ; la notification reste « best-effort ».
            notify_booking_status.apply_async(args=(instance.id, instance.status), retry=False)
        except Exception:
            logger.exception("Échec d'envoi de la tâche Celery notify_booking_status")
    else:
        logger.debug("notify_booking_status indisponible — notification ignorée.")
