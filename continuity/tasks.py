from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from continuity.models import IdempotencyRecord

RETENTION = timedelta(hours=48)


@shared_task(name="continuity.tasks.purge_idempotency")
def purge_idempotency() -> int:
    """Supprime les clés d'idempotence périmées (une nouvelle tentative légitime survient en quelques minutes ou heures)."""
    deleted, _ = IdempotencyRecord.objects.filter(created_at__lt=timezone.now() - RETENTION).delete()
    return deleted
