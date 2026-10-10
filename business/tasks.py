from celery import shared_task

from business import services


@shared_task
def run_preventive_plans() -> int:
    """Quotidien : crée les demandes de maintenance préventive échues et prévient les gestionnaires."""
    return services.run_preventive()
