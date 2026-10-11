"""Purge de comptes ERRONÉS ou de démonstration, avec toutes leurs données liées (réservations, paiements, pièces KYC, avis, litiges…).

Pourquoi une commande : l'administration refuse de supprimer un compte tant que des objets PROTÉGÉS le référencent (pièces KYC, réservations,
paiements : conservation volontaire). Les supprimer à la main oblige à remonter la chaîne objet par objet.

Garde-fous : simulation par défaut (la suppression est réellement exécutée puis ANNULÉE pour compter exactement ce qui partirait) ; `--apply`
pour supprimer ; une seule transaction (tout ou rien) ; jamais un compte d'administration ; refus s'il y a des flux d'argent réels (paiements
encaissés, retraits, dépôts) sauf `--allow-money` ; 50 comptes au plus ; trace d'audit sans donnée personnelle.

    python manage.py purge_accounts --ids 12,13,14            # simulation
    python manage.py purge_accounts --ids 12,13,14 --apply    # suppression définitive
"""
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError, RestrictedError

from handy.models import Booking, DepositTransaction, Payment, Payout, Subscription, User

MAX_ACCOUNTS = 50
MAX_DEPTH = 8
# Paiements dont la suppression effacerait la trace d'argent réellement encaissé, remboursé ou reversé.
MONEY_PAYMENT_STATUSES = ("completed", "held", "released", "refunded", "succeeded", "paid", "partially_refunded")


def delete_with_protected(obj, counts: Counter, depth: int = 0) -> None:
    """Supprime `obj` ; si des objets PROTÉGÉS le référencent, supprime d'abord ceux-ci (récursivement) puis réessaie."""
    if depth > MAX_DEPTH:
        raise CommandError(f"Chaîne de dépendances trop profonde autour de {obj._meta.label} #{obj.pk}.")
    for _ in range(MAX_DEPTH):
        try:
            label = obj._meta.label
            deleted, per_model = obj.delete()
            counts.update(per_model)
            return
        except (ProtectedError, RestrictedError) as exc:
            blockers = list(getattr(exc, "protected_objects", None) or getattr(exc, "restricted_objects", None) or [])
            if not blockers:
                raise
            for blocker in blockers:
                delete_with_protected(blocker, counts, depth + 1)
    raise CommandError(f"Impossible de supprimer {label} #{obj.pk} (dépendances circulaires ?).")


def money_report(users) -> dict:
    ids = [u.pk for u in users]
    booking_ids = Booking.objects.filter(Q(client_id__in=ids) | Q(handyman_id__in=ids)).values("pk")
    return {
        "paiements encaissés ou reversés": Payment.objects.filter(booking_id__in=booking_ids, status__in=MONEY_PAYMENT_STATUSES).count(),
        "retraits": Payout.objects.filter(handyman_id__in=ids).count(),
        "dépôts": DepositTransaction.objects.filter(handyman_id__in=ids, status="completed").count(),
        "abonnements": Subscription.objects.filter(user_id__in=ids).count(),
    }


class Command(BaseCommand):
    help = "Supprime des comptes erronés/de démonstration avec leurs données liées (simulation par défaut)."

    def add_arguments(self, parser):
        parser.add_argument("--ids", required=True, help="Identifiants des comptes, séparés par des virgules (visibles dans l'URL de l'administration).")
        parser.add_argument("--apply", action="store_true", help="Supprime réellement (sans cette option : simulation, rien n'est modifié).")
        parser.add_argument("--allow-money", action="store_true", help="Autorise la suppression même s'il existe des flux d'argent réels (déconseillé).")

    def handle(self, *args, **opt):
        try:
            ids = sorted({int(x) for x in str(opt["ids"]).split(",") if x.strip()})
        except ValueError:
            raise CommandError("--ids attend des nombres séparés par des virgules.")
        if not ids:
            raise CommandError("Aucun identifiant.")
        if len(ids) > MAX_ACCOUNTS:
            raise CommandError(f"{MAX_ACCOUNTS} comptes au plus par exécution.")
        users = list(User.objects.filter(pk__in=ids))
        missing = sorted(set(ids) - {u.pk for u in users})
        if missing:
            raise CommandError(f"Comptes introuvables : {missing}")
        protected = [u.pk for u in users if u.is_staff or u.is_superuser]
        if protected:
            raise CommandError(f"Refus : comptes d'administration {protected} (à gérer depuis « Sécurité et audit »).")

        money = money_report(users)
        if any(money.values()) and not opt["allow_money"]:
            lines = ", ".join(f"{k} : {v}" for k, v in money.items() if v)
            raise CommandError(f"Refus : des flux d'argent existent ({lines}). Ce ne sont pas des données de démonstration. "
                               "Relisez la liste ; `--allow-money` force la suppression (traces comptables perdues).")

        counts: Counter = Counter()
        try:
            with transaction.atomic():
                for user in users:
                    delete_with_protected(User.objects.get(pk=user.pk), counts)
                if not opt["apply"]:
                    transaction.set_rollback(True)             # simulation : tout est annulé après comptage exact
        except CommandError:
            raise
        self.stdout.write(self.style.MIGRATE_HEADING(("SUPPRIMÉ" if opt["apply"] else "SIMULATION (rien n'est modifié)") + f" — {len(users)} compte(s)"))
        for label, n in sorted(counts.items()):
            self.stdout.write(f"  {label:<45} {n}")
        if opt["apply"]:
            from trust.models import audit

            audit("admin.accounts_purged", target_type="user", accounts=len(users), objects=sum(counts.values()), money_forced=bool(any(money.values())))
            self.stdout.write(self.style.SUCCESS("Terminé. Les fichiers des pièces sont nettoyés du stockage au mieux (journalisés en cas d'échec)."))
        else:
            self.stdout.write("Pour supprimer réellement : relancez avec --apply.")
