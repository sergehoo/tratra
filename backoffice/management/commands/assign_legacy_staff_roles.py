"""Attribue un rôle Back-Office aux comptes du personnel historiques qui n'en ont aucun.

Par défaut : SIMULATION (liste les comptes concernés, ne modifie rien). `--apply --role <rôle>` applique le rôle choisi.
Ensuite, mettre LEGACY_STAFF_BYPASS=False ferme le passe-droit global de l'ancienne API pour ces comptes."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from backoffice import rbac


class Command(BaseCommand):
    help = "Attribue un rôle Back-Office aux comptes du personnel qui n'en ont aucun (simulation par défaut)."

    def add_arguments(self, parser):
        parser.add_argument("--role", choices=sorted(rbac.ROLES), help="Rôle à attribuer.")
        parser.add_argument("--apply", action="store_true", help="Applique réellement (sinon simulation).")

    def handle(self, *args, **opts):
        User = get_user_model()
        rbac.ensure_roles()
        candidates = [u for u in User.objects.filter(is_staff=True, is_active=True, is_superuser=False) if not rbac.user_roles(u)]
        self.stdout.write(f"{len(candidates)} compte(s) du personnel sans rôle Back-Office.")
        for u in candidates:
            self.stdout.write(f"  - #{u.pk} {u.first_name or 'sans prénom'} (dernière connexion : {u.last_login or 'jamais'})")
        if not opts["apply"]:
            self.stdout.write("Simulation : rien n'a été modifié. Relancez avec --apply --role <rôle>.")
            return
        if not opts["role"]:
            raise CommandError("--role est obligatoire avec --apply.")
        from django.contrib.auth.models import Group

        group = Group.objects.get(name=rbac.role_group_name(opts["role"]))
        for u in candidates:
            u.groups.add(group)
        self.stdout.write(self.style.SUCCESS(f"Rôle « {opts['role']} » attribué à {len(candidates)} compte(s)."))
