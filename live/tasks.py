from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from live.models import LivePosition

KEEP_AFTER_END = timedelta(hours=24)   # positions d'une mission terminée/annulée
KEEP_ACTIVE = timedelta(hours=6)       # positions anciennes d'une mission encore ouverte


def purge() -> int:
    now = timezone.now()
    ended = LivePosition.objects.filter(session__booking__status__in=("completed", "cancelled"),
                                        session__booking__updated_at__lt=now - KEEP_AFTER_END)
    stale = LivePosition.objects.filter(received_at__lt=now - KEEP_ACTIVE)
    n = ended.count() + stale.exclude(pk__in=ended.values("pk")).count()
    ended.delete()
    stale.delete()
    return n


@shared_task
def purge_positions() -> int:
    """Historique minimal : supprime les positions expirées (déclenché toutes les heures)."""
    return purge()
