"""Limites de requêtes, de coût et de délai de l'assistant. Les compteurs viennent de la BASE (messages et journal d'audit), donc exacts
même avec plusieurs processus ; seul le verrou « une réponse à la fois » utilise le cache (au mieux, il expire seul)."""
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone

INPUT_MAX = 2000
HISTORY_MESSAGES = 12
HISTORY_CHARS = 4000
ANSWER_MAX_CHARS = 8000


class LimitError(Exception):
    def __init__(self, code: str, detail: str, status: int = 429):
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def _cfg(name: str, default):
    return type(default)(getattr(settings, name, default))


def per_hour() -> int:
    return _cfg("AI_ASSISTANT_PER_HOUR", 30)


def per_day() -> int:
    return _cfg("AI_ASSISTANT_PER_DAY", 150)


def daily_tokens() -> int:
    return _cfg("AI_ASSISTANT_DAILY_TOKENS", 150000)


def draft_per_hour() -> int:
    return _cfg("AI_DRAFT_PER_HOUR", 30)


def deadline_seconds() -> int:
    return _cfg("AI_ASSISTANT_DEADLINE", 90)


def max_tokens() -> int:
    return _cfg("AI_ASSISTANT_MAX_TOKENS", 1024)


def enabled() -> bool:
    return bool(getattr(settings, "AI_ASSISTANT_ENABLED", True))


def _mine(user):
    from backoffice.models import AssistantMessage

    return AssistantMessage.objects.filter(conversation__owner=user)


def _tokens(qs, since) -> int:
    used = qs.filter(role="assistant", created_at__gte=since).aggregate(i=Sum("tokens_in"), o=Sum("tokens_out"))
    return (used["i"] or 0) + (used["o"] or 0)


def check_chat(user) -> None:
    """Refuse AVANT d'appeler un fournisseur : trop de questions (heure, jour) ou budget de jetons du jour épuisé."""
    now = timezone.now()
    mine = _mine(user)
    if mine.filter(role="user", created_at__gte=now - timedelta(hours=1)).count() >= per_hour():
        raise LimitError("rate_limited", "Trop de questions en une heure. Réessayez un peu plus tard.")
    if mine.filter(role="user", created_at__gte=now - timedelta(days=1)).count() >= per_day():
        raise LimitError("rate_limited", "Limite quotidienne de questions atteinte. Réessayez demain.")
    if _tokens(mine, now - timedelta(days=1)) >= daily_tokens():
        raise LimitError("budget_exceeded", "Budget quotidien de l'assistant atteint. Réessayez demain.")


def check_draft(user) -> None:
    from trust.models import AuditEvent

    n = AuditEvent.objects.filter(actor=user, action="backoffice.assistant.draft", created_at__gte=timezone.now() - timedelta(hours=1)).count()
    if n >= draft_per_hour():
        raise LimitError("rate_limited", "Trop de rédactions assistées en une heure. Réessayez un peu plus tard.")


def acquire(user) -> bool:
    """Une seule réponse en cours par administrateur (évite les rafales parallèles et les doubles envois)."""
    return cache.add(f"bo:ai:running:{user.pk}", 1, deadline_seconds() + 30)


def release(user) -> None:
    cache.delete(f"bo:ai:running:{user.pk}")


def usage_today(user) -> dict:
    now = timezone.now()
    mine = _mine(user)
    return {"questions_last_hour": mine.filter(role="user", created_at__gte=now - timedelta(hours=1)).count(), "questions_per_hour_limit": per_hour(),
            "tokens_last_24h": _tokens(mine, now - timedelta(days=1)), "tokens_daily_limit": daily_tokens()}
