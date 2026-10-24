"""Comptes suspects : rapport, désactivation en lot RÉVERSIBLE, réactivation.

  python manage.py antifraud_accounts report --since 2026-10-22 [--until 2026-10-24] [--out /tmp/rapport.json]
      → résumé (noms répétés, blocs de numéros, IP, rafales, SMS) + fichier JSON des candidats (et CSV à côté) à RELIRE.
  python manage.py antifraud_accounts suspend --report /tmp/rapport.json --confirm DESACTIVER-COMPTES [--label "..."]
      → désactive les candidats du fichier relu (revérifiés un par un : vérifiés ou actifs entre-temps = écartés).
  python manage.py antifraud_accounts revert --batch 3 --confirm REACTIVER-COMPTES
      → rétablit tout le lot à l'identique.  `restore --batch 3 --user 2519` : un seul compte (réclamation légitime).
  python manage.py antifraud_accounts batches
Aucune suppression : les comptes restent en base, leurs données intactes."""
import csv
import json
from datetime import datetime, time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from antifraud import report
from antifraud.models import SuspensionBatch

CONFIRM_SUSPEND = "DESACTIVER-COMPTES"
CONFIRM_REVERT = "REACTIVER-COMPTES"


def _date(value: str, *, end: bool = False):
    try:
        if "T" in value:
            parsed = datetime.fromisoformat(value)
        else:
            parsed = datetime.combine(datetime.fromisoformat(value).date(), time.max if end else time.min)
    except ValueError as exc:
        raise CommandError(f"Date invalide : {value} (AAAA-MM-JJ ou AAAA-MM-JJTHH:MM).") from exc
    return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed


class Command(BaseCommand):
    help = "Comptes suspects : rapport, désactivation en lot réversible, réactivation."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)
        r = sub.add_parser("report")
        r.add_argument("--since", required=True)
        r.add_argument("--until")
        r.add_argument("--out", default="")
        r.add_argument("--min-name", type=int, default=3)
        r.add_argument("--min-block", type=int, default=3)
        r.add_argument("--min-range", type=int, default=5)
        r.add_argument("--min-ip", type=int, default=3)
        r.add_argument("--burst-minutes", type=int, default=10)
        r.add_argument("--burst-size", type=int, default=5)
        s = sub.add_parser("suspend")
        s.add_argument("--report", required=True)
        s.add_argument("--confirm", default="")
        s.add_argument("--label", default="")
        v = sub.add_parser("revert")
        v.add_argument("--batch", type=int, required=True)
        v.add_argument("--confirm", default="")
        o = sub.add_parser("restore")
        o.add_argument("--batch", type=int, required=True)
        o.add_argument("--user", type=int, required=True)
        sub.add_parser("batches")

    def handle(self, *args, **opts):
        getattr(self, f"_{opts['action']}")(opts)

    def _report(self, opts):
        since = _date(opts["since"])
        until = _date(opts["until"], end=True) if opts.get("until") else None
        data = report.build(since, until, min_name=opts["min_name"], min_block=opts["min_block"], min_range=opts["min_range"],
                            min_ip=opts["min_ip"], burst_minutes=opts["burst_minutes"], burst_size=opts["burst_size"])
        s = data["summary"]
        w = self.stdout.write
        w(f"Période : {data['criteria']['since']} → {data['criteria']['until']}")
        w(f"Comptes inscrits : {s['accounts']} (non vérifiés : {s['unverified']})")
        w(f"CANDIDATS à la désactivation : {s['candidates']}  |  écartés car actifs : {s['excluded_active']}, vérifiés : {s['excluded_verified']}")
        w("Noms les plus répétés : " + ", ".join(f"{n} ×{c}" for n, c in s["top_names"]) if s["top_names"] else "Noms répétés : aucun")
        w("Blocs de numéros : " + ", ".join(f"{b} ×{c}" for b, c in s["top_phone_blocks"]) if s["top_phone_blocks"] else "Blocs de numéros : aucun")
        w("Plages de 100 000 numéros : " + ", ".join(f"{b} ×{c}" for b, c in s["top_phone_ranges"]) if s["top_phone_ranges"] else "Plages de numéros : aucune répétée")
        w(f"Inscriptions par client : {s['signups_by_client']}")
        w("IP d'inscription : " + ", ".join(f"{ip} ×{c}" for ip, c in s["top_ips"]) if s["top_ips"] else "IP d'inscription : aucune répétée (journal à partir du correctif)")
        w(f"SMS sur la période : {s['sms']}  bloqués par raison : {s['sms_blocked_by_reason']}")
        w("Inscriptions par heure : " + ", ".join(f"{h} : {c}" for h, c in s["signups_by_hour"][-24:]))
        if opts["out"]:
            out = Path(opts["out"])
            out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            with out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["id", "username", "nom", "téléphone", "inscrit le", "actif", "raisons"])
                for c in data["candidates"]:
                    writer.writerow([c["id"], c["username"], c["name"], c["phone"], c["joined"], c["active"], " ; ".join(c["reasons"])])
            w(self.style.SUCCESS(f"Rapport écrit : {out} et {out.with_suffix('.csv')} — à relire AVANT toute désactivation."))

    def _suspend(self, opts):
        if opts["confirm"] != CONFIRM_SUSPEND:
            raise CommandError(f"Relisez le rapport puis relancez avec --confirm {CONFIRM_SUSPEND}.")
        try:
            data = json.loads(Path(opts["report"]).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CommandError(f"Rapport illisible : {exc}") from exc
        candidates = data.get("candidates") or []
        if not candidates:
            raise CommandError("Aucun candidat dans ce rapport.")
        label = opts["label"] or f"Inscriptions suspectes {data.get('criteria', {}).get('since', '')[:10]}"
        batch, done, skipped = report.suspend(candidates, label=label, criteria=data.get("criteria", {}), actor="commande antifraud_accounts")
        self.stdout.write(self.style.SUCCESS(
            f"Lot #{batch.pk} : {done} compte(s) désactivé(s), {skipped} écarté(s) (vérifiés, actifs ou introuvables). "
            f"Annulation : antifraud_accounts revert --batch {batch.pk} --confirm {CONFIRM_REVERT}"))

    def _revert(self, opts):
        if opts["confirm"] != CONFIRM_REVERT:
            raise CommandError(f"Relancez avec --confirm {CONFIRM_REVERT} pour réactiver tout le lot.")
        if not SuspensionBatch.objects.filter(pk=opts["batch"]).exists():
            raise CommandError("Lot introuvable.")
        n = report.revert(opts["batch"], actor="commande antifraud_accounts")
        self.stdout.write(self.style.SUCCESS(f"Lot #{opts['batch']} : {n} compte(s) rétabli(s)."))

    def _restore(self, opts):
        ok = report.restore_one(opts["batch"], opts["user"])
        self.stdout.write(self.style.SUCCESS("Compte réactivé.") if ok else "Rien à réactiver (compte absent du lot ou déjà rétabli).")

    def _batches(self, opts):
        for b in SuspensionBatch.objects.all()[:50]:
            items = b.items.count()
            restored = b.items.filter(restored=True).count()
            self.stdout.write(f"#{b.pk} {b.created_at:%Y-%m-%d %H:%M} « {b.label} » : {items} compte(s), {restored} rétabli(s)"
                              + (f", annulé le {b.reverted_at:%Y-%m-%d %H:%M}" if b.reverted_at else ""))
