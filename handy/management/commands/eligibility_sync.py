"""Copie calculée de l'éligibilité (`HandymanProfile.published`) : contrôle et recalcul à partir de la règle (handy/eligibility.py).

  python manage.py eligibility_sync            recalcule tous les profils (lancé par l'entrypoint après les migrations)
  python manage.py eligibility_sync --check    compte les écarts sans rien écrire (code de sortie 1 s'il y en a)

Un écart signifie qu'un chemin de modification n'a pas recalculé la copie : le corriger, puis relancer sans --check."""
from django.core.management.base import BaseCommand, CommandError

from handy import eligibility


class Command(BaseCommand):
    help = "Contrôle ou recalcule la copie calculée de l'éligibilité des professionnels."

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true", help="Compte les écarts sans rien écrire.")

    def handle(self, *args, **opts):
        if opts["check"]:
            drift = eligibility.published_drift()
            if drift:
                raise CommandError(f"{drift} profil(s) dont la publication diffère de la règle d'éligibilité.")
            self.stdout.write("Copie de l'éligibilité conforme à la règle.")
            return
        changed = eligibility.refresh_published()
        self.stdout.write(f"Éligibilité recalculée : {changed} profil(s) corrigé(s).")
