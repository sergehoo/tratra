"""Avis : règles de publication et statistiques calculées UNIQUEMENT depuis les données réelles.

Publication : avis d'une mission TERMINÉE, non masqué par la modération. Pour qu'un client ne puisse pas
gonfler (ou écraser) la note d'un artisan en multipliant les missions, les statistiques ne retiennent
qu'UN avis par client et par artisan : le plus récent. Aucun chiffre n'est inventé : sans avis,
moyenne et critères valent `None`.
"""
from collections import Counter
from datetime import timedelta
from typing import Dict, Optional

from django.utils import timezone

from handy.models import Review


def published(handyman_user_id=None):
    """Avis publiables (mission terminée, non masqués), éventuellement d'un artisan."""
    qs = Review.objects.filter(booking__status="completed", is_hidden=False)
    if handyman_user_id is not None:
        qs = qs.filter(booking__handyman_id=handyman_user_id)
    return qs


def counted(handyman_user_id):
    """Avis retenus pour les statistiques : le plus récent de chaque client pour cet artisan."""
    ids = (published(handyman_user_id)
           .order_by("booking__client_id", "-created_at", "-id")
           .distinct("booking__client_id")
           .values_list("id", flat=True))
    return Review.objects.filter(id__in=list(ids))


def _avg(values) -> Optional[float]:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 2) if values else None


def review_stats(handyman_user_id) -> Dict:
    """{count, average, criteria{clé: {average, count}}, distribution{1..5}, replied, response_rate}."""
    rows = list(counted(handyman_user_id).values(
        "rating", "reply_text", *Review.CRITERIA))
    count = len(rows)
    dist = Counter(r["rating"] for r in rows)
    replied = sum(1 for r in rows if (r["reply_text"] or "").strip())
    return {
        "count": count,
        "average": _avg([r["rating"] for r in rows]),
        "criteria": {
            key: {"average": _avg([r[key] for r in rows]), "count": sum(1 for r in rows if r[key] is not None)}
            for key in Review.CRITERIA
        },
        "distribution": {str(i): dist.get(i, 0) for i in range(1, 6)},
        "replied": replied,
        "response_rate": round(replied / count, 2) if count else None,
    }


def can_edit(review: Review, now=None) -> bool:
    """L'auteur corrige son avis pendant `Review.EDIT_WINDOW_DAYS` jours ; ensuite il est figé."""
    now = now or timezone.now()
    return now <= review.created_at + timedelta(days=Review.EDIT_WINDOW_DAYS)


def can_reply(review: Review, now=None) -> bool:
    """L'artisan répond une fois, puis peut corriger sa réponse pendant la même fenêtre ; pas d'avis masqué."""
    if review.is_hidden:
        return False
    now = now or timezone.now()
    start = review.reply_at or now
    return now <= start + timedelta(days=Review.EDIT_WINDOW_DAYS)
