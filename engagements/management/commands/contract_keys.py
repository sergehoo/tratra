"""Clés de scellement des contrats (Ed25519), côté serveur uniquement — jamais de clé privée affichée.

  python manage.py contract_keys list                         clés publiques et statuts
  python manage.py contract_keys rotate                       nouvelle clé active (l'ancienne vérifie encore ses documents)
  python manage.py contract_keys revoke <kid> --reason "…"    compromission : signatures de cette clé signalées, nouvelle clé active"""
from django.core.management.base import BaseCommand, CommandError

from engagements import signing


class Command(BaseCommand):
    help = "Liste, rotation et révocation des clés de scellement des contrats."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)
        sub.add_parser("list")
        sub.add_parser("rotate")
        r = sub.add_parser("revoke")
        r.add_argument("kid")
        r.add_argument("--reason", required=True)

    def handle(self, *args, **opts):
        from trust.models import audit

        if opts["action"] == "rotate":
            key = signing.generate_key()
            audit("contract_key.rotated", actor=None, target_type="signing_key", target_id=key.pk, kid=key.kid, source="command")
            self.stdout.write(self.style.SUCCESS(f"Nouvelle clé active : {key.kid}"))
        elif opts["action"] == "revoke":
            if len(opts["reason"].strip()) < 10:
                raise CommandError("Motif d'au moins 10 caractères obligatoire.")
            try:
                key = signing.revoke_key(opts["kid"], reason=opts["reason"])
            except signing.SigningError as exc:
                raise CommandError(str(exc)) from exc
            audit("contract_key.revoked", actor=None, target_type="signing_key", target_id=key.pk, kid=key.kid, source="command")
            self.stdout.write(self.style.SUCCESS(f"Clé {key.kid} révoquée."))
        for k in signing.public_keys():
            self.stdout.write(f"{k['kid']:28} {k['status']:8} créée {k['created_at']:%Y-%m-%d}  publique {k['public_key']}")
