"""Bilan des numéros enregistrés au regard de libphonenumber — LECTURE SEULE, rien n'est modifié.

    python manage.py phone_audit            # synthèse
    python manage.py phone_audit --details  # comptes concernés (numéros masqués)

- « canoniques » : déjà au format E.164 que produit libphonenumber (cas normal) ;
- « à forme différente » : numéro valide mais enregistré autrement (ex. 0 national conservé après l'indicatif) — la connexion et la
  récupération les retrouvent quand même (forme historique) ;
- « historiques » : invalides pour libphonenumber (ex. anciens numéros ivoiriens à 8 chiffres) — conservés, retrouvés par l'ancienne règle ;
- « doublons potentiels » : comptes distincts dont les numéros désignent la même ligne une fois normalisés (à arbitrer par un humain).
"""
from collections import defaultdict

from django.core.management.base import BaseCommand

from handy import phone
from handy.models import User
from handy.sms import mask


class Command(BaseCommand):
    help = "Bilan (lecture seule) des numéros de téléphone enregistrés : format, numéros historiques, doublons potentiels."

    def add_arguments(self, parser):
        parser.add_argument("--details", action="store_true", help="Lister les comptes concernés (numéros masqués).")

    def handle(self, *args, details=False, **options):
        canonical, different, legacy = [], [], []
        groups = defaultdict(list)
        for pk, stored in User.objects.exclude(phone__isnull=True).exclude(phone="").values_list("pk", "phone").iterator():
            try:
                norm = phone.to_e164(stored)
            except phone.PhoneError:
                legacy.append((pk, stored))
                groups[stored].append(pk)
                continue
            (canonical if norm == stored else different).append((pk, stored))
            groups[norm].append(pk)
        duplicates = {k: v for k, v in groups.items() if len(v) > 1}
        self.stdout.write(f"Numéros enregistrés : {len(canonical) + len(different) + len(legacy)}")
        self.stdout.write(f"  canoniques (E.164 libphonenumber) : {len(canonical)}")
        self.stdout.write(f"  valides, enregistrés sous une autre forme : {len(different)}")
        self.stdout.write(f"  historiques (invalides pour libphonenumber, conservés) : {len(legacy)}")
        self.stdout.write(f"  doublons potentiels (même ligne, comptes distincts) : {len(duplicates)}")
        if details:
            for title, rows in (("Autre forme", different), ("Historiques", legacy)):
                for pk, stored in rows:
                    self.stdout.write(f"  [{title}] compte #{pk} : {mask(stored)}")
            for norm, pks in duplicates.items():
                self.stdout.write(f"  [Doublon] {mask(norm)} : comptes {', '.join(f'#{p}' for p in pks)}")
        self.stdout.write("Aucune donnée n'a été modifiée.")
