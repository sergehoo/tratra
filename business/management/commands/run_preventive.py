from django.core.management.base import BaseCommand

from business import services


class Command(BaseCommand):
    help = "Génère les demandes de maintenance préventive échues (idempotent)."

    def handle(self, *args, **opts):
        self.stdout.write(self.style.SUCCESS(f"{services.run_preventive()} demande(s) créée(s)."))
