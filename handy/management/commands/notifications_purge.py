"""Rétention des notifications : aperçu puis purge par lots (handy.notifications.purge).

  python manage.py notifications_purge --dry-run                 ce qui serait supprimé, par catégorie (rien n'est écrit)
  python manage.py notifications_purge --dry-run --days 180      même aperçu pour une autre durée
  python manage.py notifications_purge --days 180                purge (sans --days : NOTIFICATION_RETENTION_DAYS, 0 = désactivée)

Jamais supprimées : catégories protégées (NOTIFICATION_RETENTION_PROTECTED_CATEGORIES), push pas encore envoyé, notifications non
lues tant que NOTIFICATION_UNREAD_RETENTION_DAYS vaut 0. Les réservations, paiements, messages et annonces ne sont jamais touchés."""
from django.core.management.base import BaseCommand

from handy import notifications


class Command(BaseCommand):
    help = "Aperçu ou purge par lots des notifications au-delà de la durée de conservation."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None, help="Durée de conservation (jours) ; défaut : NOTIFICATION_RETENTION_DAYS.")
        parser.add_argument("--dry-run", action="store_true", help="Aperçu sans suppression.")

    def handle(self, *args, **opts):
        result = notifications.purge(days=opts["days"], dry_run=opts["dry_run"])
        if not result["enabled"]:
            self.stdout.write("Rétention désactivée (NOTIFICATION_RETENTION_DAYS=0) : rien n'est supprimé.")
        elif result.get("dry_run"):
            self.stdout.write(f"Aperçu : {result['would_delete']} notification(s) seraient supprimées — {result['by_category']}")
        else:
            self.stdout.write(f"{result['deleted']} notification(s) supprimée(s) en {result['batches']} lot(s)"
                              + ("" if result["complete"] else " — limite du passage atteinte, la suite au prochain passage"))
