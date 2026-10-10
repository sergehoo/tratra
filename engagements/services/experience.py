"""Expérience professionnelle VÉRIFIABLE d'un artisan, déduite des seuls engagements acceptés par les deux parties dans Tratra :
jamais déclarée librement. Lecture seule, sans nom de donneur d'ordre ni montant ; ne modifie ni les badges ni le score Trust."""
from datetime import date, timedelta
from typing import Optional

from django.utils import timezone

from engagements.models import EngagementContract
from engagements.services.evaluations import summary_for


def _months(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + end.month - start.month - (1 if end.day < start.day else 0))


def experience_for(user, today: Optional[date] = None) -> dict:
    today = today or timezone.localdate()
    contracts = EngagementContract.objects.filter(worker=user, activated_at__isnull=False).exclude(status="cancelled").select_related("category")
    months, completed, active, principals, categories = 0, 0, 0, set(), set()
    for c in contracts:
        ended = c.status in EngagementContract.ENDED
        # Contrat terminé : du premier au dernier jour INCLUS ; contrat en cours : jusqu'à aujourd'hui.
        stop = (min(c.effective_end or today, today) + timedelta(days=1)) if ended else today
        months += _months(c.start_date, stop)
        principals.add(c.organization_id and f"org:{c.organization_id}" or f"user:{c.principal_id}")
        categories.add(c.category.name)
        if c.status in ("completed", "terminated"):
            completed += 1
        elif c.status in EngagementContract.LIVE:
            active += 1
    return {"source": "contrats acceptés par les deux parties", "contracts_completed": completed, "contracts_active": active, "months_total": months,
            "distinct_principals": len(principals), "categories": sorted(categories), "evaluations": summary_for(user)}
