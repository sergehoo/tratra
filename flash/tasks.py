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


@shared_task(ignore_result=True)
def close_offers(offer_ids):
    """Notifications marquées lues et alerte retirée des téléphones pour des propositions closes. Rejouable : la notification reste
    lue et le signal de fermeture n'a aucun effet sur un téléphone qui l'a déjà reçu."""
    from flash import notify

    for offer_id in offer_ids:
        notify.offer_closed(offer_id)
