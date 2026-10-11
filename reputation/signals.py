"""Un avis client créé par l'ancien chemin (POST /reviews/) suit la même règle de réciprocité que le nouveau."""
from django.db.models.signals import post_save
from django.dispatch import receiver

from handy.models import Review
from handy.notifications import notify
from reputation import reveal


@receiver(post_save, sender=Review)
def review_created(sender, instance: Review, created, **kwargs):
    if not created:
        return
    booking = instance.booking
    reveal.reveal_pair(booking)
    if not Review.objects.filter(pk=instance.pk, revealed_at__isnull=False).exists():
        notify(booking.handyman_id, "evaluation_invite", "Votre client vous a évalué. Évaluez-le à votre tour : les deux notes seront alors visibles.",
               title="Évaluation à laisser", data={"kind": "mission", "id": booking.pk}, dedupe_key=f"evaluation:{booking.pk}:client")
