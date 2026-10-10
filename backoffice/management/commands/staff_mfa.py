"""Exploitation de la double authentification du personnel (hors ligne, avec accès serveur).

    python manage.py staff_mfa                       # état de tous les comptes d'administration
    python manage.py staff_mfa --reset <id> --reason "Téléphone perdu"   # supprime l'appareil (à ré-enrôler à la prochaine connexion)

L'activation se fait par l'utilisateur lui-même (Back-Office ou /admin/mfa/) : ce script n'affiche JAMAIS de secret."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from backoffice import mfa, rbac


class Command(BaseCommand):
    help = "État et réinitialisation de la double authentification des comptes d'administration."

    def add_arguments(self, parser):
        parser.add_argument("--reset", type=int, metavar="USER_ID", help="Supprime l'appareil de ce compte.")
        parser.add_argument("--reason", default="", help="Motif (obligatoire avec --reset, journalisé).")

    def handle(self, *args, **opts):
        User = get_user_model()
        if opts["reset"] is not None:
            reason = (opts["reason"] or "").strip()
            if len(reason) < 5:
                raise CommandError("--reason (5 caractères minimum) est obligatoire avec --reset.")
            u = User.objects.filter(pk=opts["reset"], is_staff=True).first()
            if u is None:
                raise CommandError("Compte d'administration introuvable.")
            had = mfa.reset(u, by=None, reason=f"[console] {reason}")
            self.stdout.write(self.style.SUCCESS(f"Compte #{u.pk} : appareil {'supprimé' if had else 'inexistant'}."))
            return
        self.stdout.write(f"Double authentification exigée : {'OUI' if mfa.required() else 'non'}")
        for u in User.objects.filter(is_staff=True, is_active=True).order_by("id"):
            dev = mfa.confirmed_device(u)
            roles = ",".join(sorted(rbac.user_roles(u))) or "aucun rôle"
            self.stdout.write(f"  #{u.pk} {u.first_name or 'sans prénom'} · {roles} · MFA : {'activée' if dev else 'NON ACTIVÉE'}")
