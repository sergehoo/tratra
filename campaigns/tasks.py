from celery import shared_task


@shared_task
def tick():
    """Toutes les 10 minutes (Celery beat, file « bulk ») : programmer, envoyer, mesurer les campagnes d'engagement. Rejouable."""
    from campaigns import engine

    return engine.tick()
