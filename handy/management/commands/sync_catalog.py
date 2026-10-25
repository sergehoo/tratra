"""Ré-applique le référentiel des métiers (familles, métiers, prestations, synonymes) — idempotent, n'efface ni ne renomme rien.

  python manage.py sync_catalog --dry-run     ce qui serait ajouté
  python manage.py sync_catalog               ajoute ce qui manque (par exemple après une suppression par erreur dans l'administration)"""
from django.core.management.base import BaseCommand
from django.db import transaction

from handy import catalog, catalog_seed


class Command(BaseCommand):
    help = "Ajoute les familles, métiers, prestations et synonymes manquants du référentiel (sans rien supprimer)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Affiche ce qui serait ajouté, sans rien écrire.")

    def handle(self, *args, **opts):
        with transaction.atomic():
            stats = catalog_seed.apply(dry_run=opts["dry_run"])
        catalog.invalidate()
        prefix = "Simulation — " if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(f"{prefix}Référentiel {catalog_seed.VERSION} : {catalog_seed.summary(stats)}"))
