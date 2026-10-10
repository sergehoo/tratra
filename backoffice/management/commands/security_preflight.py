"""Pré-vol sécurité AVANT de fermer LEGACY_STAFF_BYPASS et d'exiger la double authentification (lecture seule).

    python manage.py security_preflight            # rapport
    python manage.py security_preflight --strict   # code de sortie 1 s'il reste un bloquant

Bloquants : comptes du personnel actifs SANS rôle (ils perdraient tout accès « personnel » de l'ancienne API),
moins de 2 super administrateurs actifs (verrouillage définitif possible si l'un perd son appareil).
Informations : réglages effectifs, comptes sans double authentification activée (elle sera demandée à la prochaine connexion)."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import ProgrammingError
from django.db.models import Q

from backoffice import mfa, rbac


class Command(BaseCommand):
    help = "Rapport de pré-vol : rôles du personnel, double authentification, passe-droit historique."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Code de sortie 1 s'il reste un bloquant.")

    def handle(self, *args, **opts):
        User = get_user_model()
        rbac.ensure_roles()
        staff = list(User.objects.filter(is_staff=True, is_active=True).order_by("id"))
        no_role = [u for u in staff if not u.is_superuser and not rbac.user_roles(u)]
        supers = User.objects.filter(is_active=True, is_staff=True).filter(Q(is_superuser=True) | Q(groups__name=rbac.role_group_name("super_admin"))).distinct().count()
        try:
            no_mfa = [u for u in staff if mfa.confirmed_device(u) is None]
        except ProgrammingError:
            raise CommandError("La table de la double authentification est absente : appliquer d'abord les migrations (manage.py migrate).")
        blockers = []
        self.stdout.write("Réglages effectifs")
        self.stdout.write(f"  LEGACY_STAFF_BYPASS = {getattr(settings, 'LEGACY_STAFF_BYPASS', True)}   (production : False)")
        self.stdout.write(f"  BACKOFFICE_MFA_REQUIRED = {mfa.required()}   (production : True)")
        self.stdout.write(f"Comptes d'administration actifs : {len(staff)} dont {supers} super administrateur(s)")
        if no_role:
            blockers.append(f"{len(no_role)} compte(s) du personnel sans rôle : " + ", ".join(f"#{u.pk}" for u in no_role) + " → manage.py assign_legacy_staff_roles --assign ID=RÔLE --apply")
        if supers < 2:
            blockers.append(f"{supers} super administrateur actif : en prévoir au moins 2 (récupération en cas d'appareil MFA perdu).")
        if no_mfa:
            self.stdout.write(f"Sans double authentification activée ({len(no_mfa)}) : " + ", ".join(f"#{u.pk}" for u in no_mfa) + " — à activer à la prochaine connexion.")
        if blockers:
            self.stdout.write(self.style.ERROR("Bloquants :"))
            for b in blockers:
                self.stdout.write(self.style.ERROR(f"  ✗ {b}"))
            if opts["strict"]:
                raise CommandError(f"{len(blockers)} bloquant(s) : ne pas fermer LEGACY_STAFF_BYPASS avant résolution.")
        else:
            self.stdout.write(self.style.SUCCESS("Aucun bloquant : LEGACY_STAFF_BYPASS=False peut être appliqué."))
