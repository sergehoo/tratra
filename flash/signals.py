"""Désistement après une acceptation ferme : le seul fait que Tratra Flash transmet à Tratra Trust (refus et absences de réponse : jamais).

Le fait est vérifiable : la réservation créée par l'attribution est annulée PAR le professionnel (auteur de la transition consigné),
après le délai de grâce qui couvre une erreur de manipulation."""
import logging
from datetime import timedelta

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from handy.models import Booking

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Booking, dispatch_uid="flash_booking_withdrawal")
def booking_withdrawal(sender, instance, created, **kwargs):
    if created or kwargs.get("raw") or instance.status != "cancelled":
        return
    actor_id = getattr(instance, "_transition_actor_id", None)
    if actor_id is None or actor_id != instance.handyman_id:
        return   # annulation par le client ou par l'équipe : aucune conséquence pour le professionnel
    try:
        from flash.models import DispatchConfig, DispatchEvent, MissionRequest
        from trust.penalties import record_withdrawal

        req = MissionRequest.objects.filter(booking=instance).first()
        if req is None or req.assigned_at is None:
            return
        now = timezone.now()
        if now - req.assigned_at <= timedelta(minutes=DispatchConfig.get_solo().withdrawal_grace_minutes):
            DispatchEvent.objects.create(request=req, kind="withdrawal", actor_id=actor_id,
                                         data={"booking": instance.pk, "penalty": False, "reason": "délai de grâce"})
            return
        penalty = record_withdrawal(instance, accepted_at=req.assigned_at, cancelled_at=now, actor_id=actor_id)
        DispatchEvent.objects.create(request=req, kind="withdrawal", actor_id=actor_id,
                                     data={"booking": instance.pk, "penalty": penalty.pk if penalty else None})
    except Exception:  # une pénalité ne doit jamais bloquer l'annulation elle-même
        logger.exception("Désistement Tratra Flash non consigné (réservation %s)", instance.pk)
