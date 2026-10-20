"""Blocage de connexion (Axes) : état courant et temps restant, pour l'API de connexion.

Pourquoi : lors d'un blocage, `django.contrib.auth.authenticate` avale l'erreur d'Axes et l'API renvoyait le MÊME 400 « identifiants incorrects »
qu'un mauvais mot de passe : l'utilisateur ne pouvait pas savoir qu'il était bloqué, réessayait, et chaque essai prolongeait le blocage
(`AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT`). On vérifie donc le blocage AVANT d'authentifier : réponse claire avec le temps restant, et
l'essai refusé n'enregistre aucun nouvel échec (le compte à rebours ne se remet pas à zéro)."""
from datetime import timedelta
from typing import Optional

from django.utils import timezone


def remaining_lock_seconds(request, identifier: str = "") -> Optional[int]:
    """Secondes avant la fin du blocage de cette source (None = non bloquée). Même règle qu'Axes : adresse client + seuil d'échecs."""
    from axes.handlers.proxy import AxesProxyHandler
    from axes.helpers import get_cool_off, get_failure_limit

    if request is None:
        return None
    credentials = {"username": identifier}
    if not AxesProxyHandler.is_locked(request, credentials):
        return None
    cool_off = get_cool_off(request) or timedelta(hours=1)
    limit = get_failure_limit(request, credentials)
    now = timezone.now()
    latest = None
    for attempts in AxesProxyHandler.get_implementation().get_user_attempts(request, credentials):
        row = attempts.filter(failures_since_start__gte=limit).order_by("-attempt_time").first()
        if row is not None and (latest is None or row.attempt_time > latest):
            latest = row.attempt_time
    if latest is None:                       # bloquée sans trace datée (cas limite) : durée complète annoncée
        return int(cool_off.total_seconds())
    return max(1, int((latest + cool_off - now).total_seconds()) + 1)


def countdown(seconds: int) -> str:
    """« 55:30 » (minutes:secondes ; 1 h = « 60:00 »)."""
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
