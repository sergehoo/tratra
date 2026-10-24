"""Jetons d'accès (30 min) de comptes SYNTHÉTIQUES de la base de mesure, pour scripts/loadtest/http_load.py.

  DJANGO_ENV=loadtest python manage.py loadtest_tokens --count 500 --out <scratchpad>/tokens.json

Le fichier contient des jetons valables seulement contre la base jetable locale : il reste dans le dossier temporaire, jamais dans Git."""
import json

from django.core.management.base import BaseCommand
from rest_framework_simplejwt.tokens import AccessToken

from loadtest import guard


class Command(BaseCommand):
    help = "Jetons d'accès de comptes synthétiques (base de mesure uniquement)."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=200)
        parser.add_argument("--pros", type=float, default=0.1, help="Part de professionnels parmi les comptes.")
        parser.add_argument("--out", required=True)

    def handle(self, *args, **o):
        guard.assert_safe()
        from handy.models import Conversation, HandymanProfile, User

        n_pros = int(o["count"] * o["pros"])
        pros = list(User.objects.filter(handyman_profile__is_approved=True, username__startswith="lt").order_by("pk")[:n_pros])
        clients = list(User.objects.filter(handyman_profile__isnull=True, username__startswith="lt", client_bookings__isnull=False)
                       .distinct().order_by("pk")[: o["count"] - len(pros)])
        convs = dict(Conversation.participants.through.objects.filter(user__in=clients).values_list("user_id", "conversation_id"))
        profiles = dict(HandymanProfile.objects.filter(user__in=pros).values_list("user_id", "pk"))
        rows = [{"user": u.pk, "role": "pro" if u.pk in profiles else "client", "access": str(AccessToken.for_user(u)),
                 "conversation": convs.get(u.pk), "profile": profiles.get(u.pk)} for u in pros + clients]
        with open(o["out"], "w", encoding="utf-8") as fh:
            json.dump(rows, fh)
        self.stdout.write(f"{len(rows)} jetons écrits ({len(pros)} professionnels) : {o['out']}")
