from celery import shared_task

from trust import engine


@shared_task
def reevaluate_all_profiles(force: bool = False) -> int:
    """Réévaluation périodique des badges et scores (période d'observation glissante, justificatifs expirés…)."""
    return engine.reevaluate_all(force=force, trigger="periodic")
