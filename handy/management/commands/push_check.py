"""Contrôle de la configuration FCM (push Android/iOS) — sans jamais afficher un secret.

    python manage.py push_check                      # configuration chargée ? projet ? appareils enregistrés par plateforme
    python manage.py push_check --token              # + obtient un jeton OAuth auprès de Google (prouve que le compte de service est valide)
    python manage.py push_check --user 12 --validate # + FCM valide un message vers les appareils du compte 12 SANS le remettre
    python manage.py push_check --user 12 --send     # + envoie un VRAI push de test (qualification : application fermée, en arrière-plan, ouverte)

Sans configuration, la commande l'indique et sort avec le code 1 (le serveur, lui, continue de fonctionner sans push)."""
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from handy import push
from handy.models import Device


class Command(BaseCommand):
    help = "Vérifie la configuration FCM et peut envoyer un push de test."

    def add_arguments(self, parser):
        parser.add_argument("--token", action="store_true", help="Obtient un jeton OAuth (appel réseau vers Google).")
        parser.add_argument("--user", type=int, help="Compte dont les appareils servent au test.")
        parser.add_argument("--validate", action="store_true", help="Validation FCM sans remise (nécessite --user).")
        parser.add_argument("--send", action="store_true", help="Envoie un vrai push de test (nécessite --user).")

    def handle(self, *args, **opts):
        ok = push.is_configured()
        self.stdout.write(f"Configuration FCM : {'chargée' if ok else 'ABSENTE ou illisible'}")
        if ok:
            self.stdout.write(f"  Projet Firebase : {push.project_id()}")
        counts = dict(Device.objects.values_list("device_type").annotate(n=Count("id")))
        self.stdout.write("Appareils enregistrés : " + ", ".join(f"{k}={counts.get(k, 0)}" for k in ("android", "ios", "web")))
        if not ok:
            self.stdout.write("  → déposer le JSON du compte de service et renseigner FCM_CREDENTIALS_FILE (voir docs/push-fcm.md).")
            raise SystemExit(1)
        if opts["token"]:
            push.reset_cache()
            self.stdout.write("Jeton OAuth Google : " + ("obtenu" if push._access_token(force=True) else "REFUSÉ (compte de service invalide, API FCM v1 désactivée ou réseau)"))
        if opts["validate"] or opts["send"]:
            if not opts["user"]:
                raise CommandError("--user est obligatoire avec --validate / --send.")
            result = push.send_to_user(opts["user"], "Test Tratra", "Notification de test : tout fonctionne.", {"kind": "notifications", "deeplink": "tratra://notifications"},
                                       validate_only=not opts["send"])
            self.stdout.write(f"Résultat ({'envoi réel' if opts['send'] else 'validation seule'}) : {result}")
            if result.get("skipped") == "no_device":
                self.stdout.write("  → aucun appareil Android/iOS enregistré pour ce compte : ouvrir l'application connectée, autoriser les notifications.")
