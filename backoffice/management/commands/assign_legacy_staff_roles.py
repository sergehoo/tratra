"""Attribue un rôle Back-Office aux comptes du personnel historiques qui n'en ont aucun.

Par défaut : SIMULATION (liste les comptes concernés, ne modifie rien). Deux façons d'appliquer (`--apply`) :
  --role <rôle>                  même rôle pour tous les comptes listés ;
  --assign <id>=<rôle> (répétable)   rôle choisi compte par compte (recommandé : moindre privilège) ; les comptes non cités restent sans rôle.
Ensuite, LEGACY_STAFF_BYPASS=False (défaut en production) ferme le passe-droit global de l'ancienne API pour les comptes restés sans rôle.
Chaque attribution est journalisée (trust.AuditEvent « security.legacy_role_assigned »)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from backoffice import mfa, rbac
from trust.models import audit


class Command(BaseCommand):
    help = "Attribue un rôle Back-Office aux comptes du personnel qui n'en ont aucun (simulation par défaut)."

    def add_arguments(self, parser):
        parser.add_argument("--role", choices=sorted(rbac.ROLES), help="Rôle à attribuer à TOUS les comptes listés.")
        parser.add_argument("--assign", action="append", default=[], metavar="ID=RÔLE", help="Rôle d'un compte précis (répétable).")
        parser.add_argument("--apply", action="store_true", help="Applique réellement (sinon simulation).")

    def handle(self, *args, **opts):
        User = get_user_model()
        rbac.ensure_roles()
        candidates = {u.pk: u for u in User.objects.filter(is_staff=True, is_active=True, is_superuser=False).order_by("id") if not rbac.user_roles(u)}
        plan = {}
        for item in opts["assign"]:
            uid, _, role = item.partition("=")
            if not uid.strip().isdigit() or role not in rbac.ROLES:
                raise CommandError(f"--assign « {item} » invalide : attendu ID=RÔLE avec un rôle parmi {', '.join(sorted(rbac.ROLES))}.")
            if int(uid) not in candidates:
                raise CommandError(f"Le compte #{uid} n'est pas un compte du personnel actif sans rôle.")
            plan[int(uid)] = role
        if opts["role"]:
            for uid in candidates:
                plan.setdefault(uid, opts["role"])
        self.stdout.write(f"{len(candidates)} compte(s) du personnel sans rôle Back-Office.")
        for u in candidates.values():
            target = plan.get(u.pk)
            self.stdout.write(f"  - #{u.pk} {u.first_name or 'sans prénom'} (dernière connexion : {u.last_login or 'jamais'}) → {target or 'aucun rôle (accès historique fermé si LEGACY_STAFF_BYPASS=False)'}")
        if not opts["apply"]:
            self.stdout.write("Simulation : rien n'a été modifié. Relancez avec --apply et --role ou --assign ID=RÔLE.")
            return
        if not plan:
            raise CommandError("--role ou --assign est obligatoire avec --apply.")
        for uid, role in plan.items():
            u = candidates[uid]
            u.groups.add(Group.objects.get(name=rbac.role_group_name(role)))
            audit("security.legacy_role_assigned", target=u, role=role)
        self.stdout.write(self.style.SUCCESS(f"{len(plan)} rôle(s) attribué(s)."))
        if mfa.required():
            self.stdout.write("Double authentification exigée : chaque compte l'activera à sa prochaine connexion au Back-Office.")
