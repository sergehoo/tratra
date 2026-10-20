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


@shared_task(name="intelligence.tasks.analyze_document")
def analyze_document(document_id: int) -> str:
    """Analyse assistée d'une pièce transmise par le parcours « Vérifier mon identité » : aide l'examinateur, ne décide rien."""
    from handy.models import HandymanDocument
    from intelligence import documents

    doc = HandymanDocument.objects.filter(pk=document_id).select_related("handyman__user").first()
    if doc is None:
        return "absent"
    try:
        return documents.analyze(doc).risk_level
    except Exception:  # noqa: BLE001 - l'examinateur peut relancer l'analyse depuis le Back-Office
        logger.exception("Analyse de la pièce %s en échec", document_id)
        return "error"
