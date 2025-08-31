from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from handy.models import ServiceImage, User, HandymanProfile, Review, Booking


@receiver(post_save, sender=User)
def create_handyman_profile(sender, instance, created, **kwargs):
    if created and instance.user_type == 'handyman':
        # Vérifie qu'il n'existe pas déjà un profil
        HandymanProfile.objects.get_or_create(user=instance)


@receiver(post_delete, sender=ServiceImage)
def delete_service_image_file(sender, instance, **kwargs):
    if instance.image:
        instance.image.delete(False)


@receiver(post_save, sender=Review)
def update_rating_on_review(sender, instance: Review, created, **kwargs):
    if not created: return
    handyman = instance.booking.handyman
    qs = Review.objects.filter(booking__handyman=handyman)
    avg = qs.aggregate(avg=models.Avg('rating'))['avg'] or 0
    HandymanProfile.objects.filter(user=handyman).update(rating=avg)

@receiver(post_save, sender=Booking)
def increment_completed_jobs(sender, instance: Booking, **kwargs):
    if instance.status == 'completed':
        HandymanProfile.objects.filter(user=instance.handyman).update(
            completed_jobs=models.F('completed_jobs') + 1
        )

@receiver(post_save, sender=Booking)
def on_booking_status_change(sender, instance: Booking, **kwargs):
    notify_booking_status.delay(instance.client_id, instance.id, instance.status)