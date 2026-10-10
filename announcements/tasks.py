from celery import shared_task


@shared_task
def deliver_announcement(announcement_id):
    """Diffuse une annonce publiée (idempotent : une livraison et une notification par utilisateur)."""
    from announcements import services

    return services.deliver(announcement_id)


@shared_task
def tick():
    """Chaque minute : publication des annonces programmées échues et expiration des annonces dépassées."""
    from announcements import services

    return services.tick()
