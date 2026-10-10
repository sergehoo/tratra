from django.core.management.base import BaseCommand

from live import tasks


class Command(BaseCommand):
    help = "Supprime les positions de suivi expirées (missions terminées depuis 24 h, positions de plus de 6 h)."

    def handle(self, *args, **opts):
        self.stdout.write(self.style.SUCCESS(f"{tasks.purge()} position(s) supprimée(s)."))
