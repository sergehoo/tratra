"""Tâche horaire (rejouable) : expiration des sessions abandonnées et suppression des captures arrivées au terme de leur conservation."""
from celery import shared_task

from biometrics import services


@shared_task(name="biometrics.tasks.tick")
def tick() -> dict:
    return services.expire_and_purge()
