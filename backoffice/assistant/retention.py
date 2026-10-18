"""Conservation de l'historique de Tratra AI : une conversation inactive depuis plus de `AI_ASSISTANT_RETENTION_DAYS` jours (supprimée ou non)
est effacée avec ses messages. L'audit (qui a demandé quoi, quels outils, combien de jetons) reste dans le journal d'audit, sans texte."""
from datetime import timedelta
from typing import Dict

from django.conf import settings
from django.utils import timezone

from backoffice.models import AssistantConversation


def retention_days() -> int:
    return max(1, int(getattr(settings, "AI_ASSISTANT_RETENTION_DAYS", 90)))


def purge(*, days: int = 0, apply: bool = True) -> Dict:
    cutoff = timezone.now() - timedelta(days=days or retention_days())
    qs = AssistantConversation.objects.filter(updated_at__lt=cutoff)
    n = qs.count()
    if apply and n:
        qs.delete()
    return {"conversations": n, "cutoff": cutoff.isoformat(), "applied": bool(apply)}
