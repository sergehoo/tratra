"""Purge de l'historique des conversations de Tratra AI après la durée de conservation.

    python manage.py purge_assistant_history            # simulation : compte seulement
    python manage.py purge_assistant_history --apply    # supprime
    python manage.py purge_assistant_history --days 30 --apply
La tâche planifiée `backoffice.tasks.purge_assistant_history` fait la même chose chaque jour avec `AI_ASSISTANT_RETENTION_DAYS`."""
from django.core.management.base import BaseCommand

from backoffice.assistant.retention import purge


class Command(BaseCommand):
    help = "Supprime les conversations de l'assistant inactives depuis plus longtemps que la durée de conservation."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=0, help="Durée de conservation en jours (défaut : AI_ASSISTANT_RETENTION_DAYS).")
        parser.add_argument("--apply", action="store_true", help="Supprime réellement (sans cette option : simulation).")

    def handle(self, *args, **opts):
        result = purge(days=opts["days"], apply=opts["apply"])
        verb = "supprimée(s)" if result["applied"] else "à supprimer (simulation, rien n'est modifié)"
        self.stdout.write(f"{result['conversations']} conversation(s) {verb} — inactives avant {result['cutoff']}.")
