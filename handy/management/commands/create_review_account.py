"""Compte de test destiné aux relecteurs de Google Play (et de l'App Store), à créer sur le serveur de production.

    python manage.py create_review_account                 # crée le compte, affiche le mot de passe UNE fois
    python manage.py create_review_account --phone +2250700000199

Les relecteurs ne peuvent pas recevoir de SMS : le téléphone du compte est donc marqué vérifié, par décision de l'exploitant qui
lance la commande. C'est un compte CLIENT ordinaire (aucun droit d'équipe, aucun profil artisan, aucune donnée réelle) ; l'OTP des
autres comptes n'est jamais contourné. Relancer la commande change le mot de passe (rotation). Le mot de passe n'est jamais écrit
dans le dépôt : il est tiré au hasard et affiché une seule fois sur la sortie standard."""
import secrets

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

USERNAME = "play_review"
DEFAULT_PHONE = "+2250700000199"


class Command(BaseCommand):
    help = "Crée (ou fait tourner le mot de passe de) le compte de test des relecteurs de la boutique d'applications."

    def add_arguments(self, parser):
        parser.add_argument("--phone", default=DEFAULT_PHONE, help="Numéro E.164 du compte de test (défaut : %(default)s).")

    @transaction.atomic
    def handle(self, *args, **opts):
        from handy.models import User

        phone = opts["phone"].strip()
        if not phone.startswith("+") or not phone[1:].isdigit() or not 8 <= len(phone) <= 16:
            raise CommandError("Le numéro doit être au format E.164 (ex. +2250700000199).")
        other = User.objects.filter(phone=phone).exclude(username=USERNAME).first()
        if other is not None:
            raise CommandError("Ce numéro appartient déjà à un autre compte : choisissez un autre numéro avec --phone.")

        user = User.objects.filter(username=USERNAME).first()
        created = user is None
        if created:
            user = User(username=USERNAME)
        user.first_name, user.last_name = "Relecteur", "Boutique"
        user.user_type = "client"
        user.phone = phone
        user.is_active = True
        user.is_staff = user.is_superuser = False
        user.is_verified = True
        user.deleted_at = None
        user.terms_accepted_at = user.terms_accepted_at or timezone.now()
        password = secrets.token_urlsafe(12)
        user.set_password(password)
        user.save()

        self.stdout.write(self.style.SUCCESS(f"Compte de relecture {'créé' if created else 'mis à jour (mot de passe changé)'}."))
        self.stdout.write(f"Téléphone : {phone}")
        self.stdout.write(f"Mot de passe (affiché une seule fois) : {password}")
