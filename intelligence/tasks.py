"""Tâche périodique (toutes les 6 h, rejouable) : propose des dossiers de risque. Ne sanctionne rien."""
import logging

from celery import shared_task

from intelligence import risk

logger = logging.getLogger(__name__)


@shared_task(name="intelligence.tasks.scan")
def scan() -> dict:
    try:
        return risk.scan()
    except Exception:  # noqa: BLE001
        logger.exception("Analyse des risques en échec")
        return {}
