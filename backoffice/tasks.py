from celery import shared_task


@shared_task(name="backoffice.tasks.deliver_batch", bind=True, autoretry_for=(Exception,), retry_backoff=30, retry_backoff_max=600, max_retries=5)
def deliver_batch(self, batch_id: int) -> dict:
    """Envoie un lot de messages d'équipe (rejouable : jamais de doublon, un destinataire en échec est réessayé)."""
    from backoffice import staff_messaging

    return staff_messaging.deliver(batch_id)
