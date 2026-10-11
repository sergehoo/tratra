"""Tâche horaire (rejouable) : révélation des notes dont le délai est écoulé, puis détection des évaluations abusives ou répétées."""
import logging

from celery import shared_task

from reputation import reveal

logger = logging.getLogger(__name__)


def run() -> dict:
    from reputation import watch

    stats = {"revealed": reveal.reveal_due(), "watch": {}}
    try:
        stats["watch"] = watch.scan()
    except Exception:  # noqa: BLE001 - la détection ne doit jamais bloquer la révélation des notes
        logger.exception("Détection des évaluations en échec")
    return stats


@shared_task(name="reputation.tasks.tick")
def tick() -> dict:
    return run()
