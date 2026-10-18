"""Nettoyage des comptes de DÉMONSTRATION et de leurs données liées (réservations, paiements non vérifiés, pièces, avis…).

Trois temps, jamais en une seule commande :
  1. SIMULATION (défaut, rien n'est modifié) : liste les comptes qui ressemblent à des données fictives, écrit la sélection dans un fichier :
       python manage.py cleanup_demo_data --dry-run --selection-out /tmp/demo_selection.json
  2. RELECTURE par une personne (ouvrir le fichier, retirer toute ligne douteuse, ne jamais se fier à un nom ou à un e-mail).
  3. EXÉCUTION, uniquement avec la sélection relue, une sauvegarde de la base datant de moins de 48 h et le mot de confirmation :
       pg_dump … > /sauvegardes/tratra_avant_nettoyage.sql
       python manage.py cleanup_demo_data --execute --selection /tmp/demo_selection.json --backup /sauvegardes/tratra_avant_nettoyage.sql \\
              --confirm SUPPRIMER-DONNEES-DEMO

Reconnu comme fictif sur des signaux STRUCTURELS (jamais un nom ou un e-mail) : jamais connecté, jamais accepté les conditions, aucune session,
aucun code OTP, aucun appareil, hors administration, ET aucun argent réel (paiement vérifié auprès d'un prestataire, retrait, caution,
abonnement, compte de versement vérifié). Avant d'exécuter, chaque compte de la sélection est REVÉRIFIÉ : un seul qui a changé arrête tout."""
import hashlib
import json
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from handy import safe_delete as sd

CONFIRM = "SUPPRIMER-DONNEES-DEMO"
BACKUP_MAX_AGE_S = 48 * 3600
DEFAULT_LIMIT = 200


def _digest(ids) -> str:
    return hashlib.sha256(",".join(str(i) for i in sorted(ids)).encode()).hexdigest()


class Command(BaseCommand):
    help = "Liste (--dry-run, défaut) puis supprime (--execute) les comptes de démonstration relus et leurs données liées."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Simulation : rien n'est modifié (comportement par défaut).")
        parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Comptes proposés au plus (défaut {DEFAULT_LIMIT}).")
        parser.add_argument("--selection-out", help="Écrit la sélection (identifiants) dans ce fichier JSON pour relecture.")
        parser.add_argument("--execute", action="store_true", help="Supprime réellement la sélection relue.")
        parser.add_argument("--selection", help="Fichier de sélection relu (obligatoire avec --execute).")
        parser.add_argument("--backup", help="Fichier de sauvegarde de la base, de moins de 48 h (obligatoire avec --execute).")
        parser.add_argument("--confirm", help=f"Mot de confirmation exact : {CONFIRM}")

    # ------------------------------------------------------------------ simulation
    def _list(self, opt):
        candidates = list(sd.demo_candidates().order_by("pk")[: max(1, opt["limit"])])
        self.stdout.write(self.style.MIGRATE_HEADING(f"SIMULATION — {len(candidates)} compte(s) ressemblent à des données fictives (rien n'est modifié)"))
        from handy.models import Booking

        for u in candidates:
            bookings = Booking.objects.filter(client=u).count() + Booking.objects.filter(handyman=u).count()
            self.stdout.write(f"  #{u.pk:<7} {u.username:<28} inscrit le {u.date_joined:%Y-%m-%d}  réservations liées : {bookings}")
        outcomes = sd.plan_users(candidates, confirm_fictive=False, actor=None)
        report = sd.execute(outcomes, apply=False)
        self.stdout.write("Objets qui seraient supprimés (comptage exact, puis annulé) :")
        for label, n in sorted(report.counts.items()):
            self.stdout.write(f"  {label:<45} {n}")
        for label, reasons in report.refused:
            self.stdout.write(self.style.WARNING(f"  conservé : {label} — {' ; '.join(reasons)}"))
        if opt.get("selection_out"):
            ids = [o.obj_id for o in outcomes if o.action == "delete"]
            payload = {"created_at": timezone.now().isoformat(), "user_ids": ids, "sha256": _digest(ids),
                       "note": "À RELIRE : retirez toute ligne douteuse avant --execute (le hash est recalculé à partir des identifiants)."}
            Path(opt["selection_out"]).write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Sélection écrite dans {opt['selection_out']} ({len(ids)} compte(s)). Relisez-la, faites une sauvegarde, puis --execute."))
        self.stdout.write("Aucune donnée n'a été modifiée.")

    # ------------------------------------------------------------------ exécution
    def _execute(self, opt):
        if opt.get("confirm") != CONFIRM:
            raise CommandError(f"Confirmation manquante ou inexacte : ajoutez --confirm {CONFIRM}.")
        if not opt.get("selection"):
            raise CommandError("--selection est obligatoire : relisez d'abord la sélection produite par --dry-run --selection-out.")
        if not opt.get("backup"):
            raise CommandError("--backup est obligatoire : faites d'abord une sauvegarde de la base (pg_dump) et indiquez son chemin.")
        backup = Path(opt["backup"])
        if not backup.is_file() or backup.stat().st_size == 0:
            raise CommandError(f"Sauvegarde introuvable ou vide : {backup}")
        if time.time() - backup.stat().st_mtime > BACKUP_MAX_AGE_S:
            raise CommandError("La sauvegarde date de plus de 48 h : faites-en une nouvelle juste avant le nettoyage.")
        try:
            data = json.loads(Path(opt["selection"]).read_text(encoding="utf-8"))
            ids = sorted({int(i) for i in data["user_ids"]})
        except (OSError, ValueError, KeyError, TypeError):
            raise CommandError("Fichier de sélection illisible (attendu : JSON avec « user_ids »).")
        if not ids:
            raise CommandError("La sélection est vide.")

        from handy.models import User

        users = list(User.objects.filter(pk__in=ids))
        missing = sorted(set(ids) - {u.pk for u in users})
        if missing:
            raise CommandError(f"Comptes introuvables (déjà supprimés ?) : {missing[:20]}")
        still_demo = set(sd.demo_candidates().filter(pk__in=ids).values_list("pk", flat=True))
        changed = sorted(set(ids) - still_demo)
        if changed:
            raise CommandError(f"Refus, rien n'est supprimé : {len(changed)} compte(s) ne ressemblent plus à des données fictives ou ont de l'argent réel "
                               f"(ex. {changed[:10]}). Relancez la simulation et relisez.")
        outcomes = sd.plan_users(users, confirm_fictive=False, actor=None)
        not_delete = [o.label for o in outcomes if o.action != "delete"]
        if not_delete:
            raise CommandError(f"Refus, rien n'est supprimé : {len(not_delete)} compte(s) ne seraient pas supprimés tels quels ({not_delete[:5]}).")
        done = 0
        counts = {}
        for o in outcomes:                                    # un compte à la fois : un échec n'efface pas le travail déjà validé
            report = sd.execute([o], apply=True, actor=None)
            if report.deleted:
                done += 1
                for k, v in report.counts.items():
                    counts[k] = counts.get(k, 0) + v
            else:
                self.stdout.write(self.style.WARNING(f"  conservé : {o.label} — {report.refused}"))
        self.stdout.write(self.style.SUCCESS(f"Terminé : {done}/{len(outcomes)} compte(s) supprimé(s) avec leurs données liées."))
        for label, n in sorted(counts.items()):
            self.stdout.write(f"  {label:<45} {n}")

    def handle(self, *args, **opt):
        if opt["execute"] and opt["dry_run"]:
            raise CommandError("--execute et --dry-run s'excluent.")
        if opt["execute"]:
            return self._execute(opt)
        return self._list(opt)
