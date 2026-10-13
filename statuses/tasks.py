"""Expiration et conservation des statuts : tâche périodique rejouable, réessayée en cas d'indisponibilité du stockage."""
from celery import shared_task


@shared_task(name="statuses.tasks.purge", bind=True, autoretry_for=(Exception,), retry_backoff=60, retry_backoff_max=900, max_retries=5)
def purge(self) -> dict:
    from statuses import services

    return services.purge()
