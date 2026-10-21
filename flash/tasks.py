"""Échéances Tratra Flash : compte à rebours de chaque vague (précis) et passage périodique (filet de sécurité, 30 s)."""
from celery import shared_task


@shared_task(ignore_result=True)
def wave_timeout(request_id, wave):
    from flash.services import expire_due

    return expire_due()


@shared_task(ignore_result=True)
def tick():
    from flash.hybrid import close_stale_awaiting
    from flash.services import expire_due

    result = expire_due()
    result["awaiting_closed"] = close_stale_awaiting()   # demandes « choix du client attendu » restées sans réponse
    return result
