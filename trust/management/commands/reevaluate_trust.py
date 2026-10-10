from django.core.management.base import BaseCommand

from trust import engine


class Command(BaseCommand):
    help = "Réévalue les badges et scores Tratra Trust (tous les profils artisans, ou ceux non évalués depuis la durée configurée)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Réévalue tous les profils sans tenir compte de la dernière évaluation.")

    def handle(self, *args, **opts):
        n = engine.reevaluate_all(force=opts["force"], trigger="command")
        self.stdout.write(self.style.SUCCESS(f"{n} profil(s) réévalué(s)."))
