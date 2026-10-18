"""Suppression SÉCURISÉE de comptes et de réservations (administration Django et commande `cleanup_demo_data`).

Pourquoi : l'administration refuse de supprimer un compte ou une réservation tant que des objets PROTÉGÉS les référencent (paiements,
réservations, pièces KYC…). `on_delete=PROTECT` reste en place : c'est ce service qui remonte la chaîne, sous contrôle.

Règles (aucune n'est contournable, sauf mention) :
- ARGENT RÉEL JAMAIS EFFACÉ : paiement vérifié auprès d'un prestataire (`provider_verified_at`) ou ayant une session prestataire, retrait demandé
  ou envoyé, caution encaissée, abonnement, compte de versement vérifié. Un compte concerné est ANONYMISÉ (écritures conservées, plus aucun
  nom, téléphone ni e-mail), jamais supprimé ; une réservation concernée est refusée.
- DONNÉE FICTIVE reconnue sur des signaux STRUCTURELS (jamais sur un nom ou un e-mail) : aucune connexion, aucune acceptation des conditions,
  aucun jeton de session, aucun code OTP, aucun appareil de notification, compte hors administration.
- Un compte d'administration, ou son propre compte, n'est jamais supprimé.
- Un compte qui ne ressemble pas à une donnée fictive n'est ANONYMISÉ par défaut ; le supprimer vraiment exige la case « ce sont des données
  fictives » cochée explicitement (et reste impossible s'il y a de l'argent réel).
- Aperçu exact avant tout : la suppression est réellement exécutée puis ANNULÉE pour compter ce qui partirait ; confirmation par mot saisi ;
  une trace d'audit sans donnée personnelle ; superutilisateur uniquement (contrôle côté administration)."""
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError, RestrictedError

User = get_user_model()
MAX_DEPTH = 8
MAX_BATCH = 50                       # éléments au plus par opération depuis l'administration
CONFIRM_WORD = "SUPPRIMER"


class RealMoneyError(Exception):
    """La chaîne de suppression atteindrait de l'argent réel : rien n'est supprimé."""


# ------------------------------------------------------------------ argent réel
def is_real_payment(payment) -> bool:
    return payment.provider_verified_at is not None or bool(payment.provider_session)


def real_payments(booking_ids):
    from handy.models import Payment

    return Payment.objects.filter(booking_id__in=booking_ids).filter(Q(provider_verified_at__isnull=False) | ~Q(provider_session={}))


def money_reasons_for_users(user_ids: Iterable[int]) -> List[str]:
    from handy.models import Booking, DepositTransaction, Payout, PayoutAccount, Subscription

    ids = list(user_ids)
    booking_ids = Booking.objects.filter(Q(client_id__in=ids) | Q(handyman_id__in=ids)).values("pk")
    out = []
    n = real_payments(booking_ids).count()
    if n:
        out.append(f"{n} paiement(s) vérifié(s) auprès d'un prestataire")
    n = Payout.objects.filter(handyman_id__in=ids, status__in=("pending", "sent")).count()
    if n:
        out.append(f"{n} retrait(s) demandé(s) ou envoyé(s)")
    n = DepositTransaction.objects.filter(handyman_id__in=ids, status="completed").count()
    if n:
        out.append(f"{n} mouvement(s) de caution")
    n = Subscription.objects.filter(user_id__in=ids).count()
    if n:
        out.append(f"{n} abonnement(s)")
    n = PayoutAccount.objects.filter(handyman_id__in=ids, verified=True).count()
    if n:
        out.append(f"{n} compte(s) de versement vérifié(s)")
    return out


def money_reasons_for_bookings(booking_ids: Iterable[int]) -> List[str]:
    n = real_payments(list(booking_ids)).count()
    return [f"{n} paiement(s) vérifié(s) auprès d'un prestataire : écriture financière conservée"] if n else []


def _guard(obj) -> None:
    """Appelé sur CHAQUE objet protégé avant sa suppression (tout flux d'argent est protégé : il passe forcément ici)."""
    from handy.models import DepositTransaction, Payment, Payout, PayoutAccount, Subscription

    if isinstance(obj, Payment) and is_real_payment(obj):
        raise RealMoneyError(f"paiement #{obj.pk} vérifié auprès d'un prestataire")
    if isinstance(obj, Payout) and obj.status in ("pending", "sent"):
        raise RealMoneyError(f"retrait #{obj.pk}")
    if isinstance(obj, DepositTransaction) and obj.status == "completed":
        raise RealMoneyError(f"mouvement de caution #{obj.pk}")
    if isinstance(obj, Subscription):
        raise RealMoneyError(f"abonnement #{obj.pk}")
    if isinstance(obj, PayoutAccount) and obj.verified:
        raise RealMoneyError(f"compte de versement #{obj.pk} vérifié")


def cascade_delete(obj, counts: Counter, depth: int = 0) -> None:
    """Supprime `obj` ; les objets PROTÉGÉS qui le référencent sont supprimés d'abord (récursivement), SAUF argent réel (RealMoneyError)."""
    if depth > MAX_DEPTH:
        raise RuntimeError(f"Chaîne de dépendances trop profonde autour de {obj._meta.label} #{obj.pk}.")
    for _ in range(MAX_DEPTH):
        try:
            with transaction.atomic():
                _, per_model = obj.delete()
            counts.update(per_model)
            return
        except (ProtectedError, RestrictedError) as exc:
            blockers = list(getattr(exc, "protected_objects", None) or getattr(exc, "restricted_objects", None) or [])
            if not blockers:
                raise
            for blocker in blockers:
                _guard(blocker)
                cascade_delete(blocker, counts, depth + 1)
    raise RuntimeError(f"Impossible de supprimer {obj._meta.label} #{obj.pk} (dépendances circulaires ?).")


# ------------------------------------------------------------------ données fictives
def demo_failures(user) -> List[str]:
    """Signaux qui montrent qu'un compte est RÉEL (liste vide = ressemble à une donnée fictive). Jamais le nom ni l'e-mail."""
    from handy.models import Device, OTPCode

    out = []
    if user.is_staff or user.is_superuser:
        out.append("compte d'administration")
    if user.last_login is not None:
        out.append("s'est déjà connecté")
    if user.terms_accepted_at is not None:
        out.append("a accepté les conditions d'utilisation")
    if OTPCode.objects.filter(user=user).exists():
        out.append("a demandé un code de vérification")
    if Device.objects.filter(user=user).exists():
        out.append("a enregistré un appareil de notification")
    try:
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

        if OutstandingToken.objects.filter(user=user).exists():
            out.append("a eu une session ouverte")
    except Exception:  # application de jetons absente
        pass
    return out


def looks_demo(user) -> bool:
    return not demo_failures(user)


def demo_candidates():
    """Comptes qui ressemblent à des données fictives ET sans argent réel (le moins de requêtes possible, résultat à valider par une personne)."""
    from handy.models import Booking, DepositTransaction, Device, OTPCode, Payout, PayoutAccount, Subscription

    qs = User.objects.filter(is_staff=False, is_superuser=False, last_login__isnull=True, terms_accepted_at__isnull=True, deleted_at__isnull=True)
    qs = qs.exclude(pk__in=OTPCode.objects.values("user_id")).exclude(pk__in=Device.objects.values("user_id"))
    try:
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

        qs = qs.exclude(pk__in=OutstandingToken.objects.exclude(user__isnull=True).values("user_id"))
    except Exception:
        pass
    money_bookings = real_payments(Booking.objects.values("pk")).values("booking_id")
    qs = qs.exclude(pk__in=Booking.objects.filter(pk__in=money_bookings).values("client_id"))
    qs = qs.exclude(pk__in=Booking.objects.filter(pk__in=money_bookings).values("handyman_id"))
    qs = qs.exclude(pk__in=Payout.objects.filter(status__in=("pending", "sent")).values("handyman_id"))
    qs = qs.exclude(pk__in=DepositTransaction.objects.filter(status="completed").values("handyman_id"))
    qs = qs.exclude(pk__in=Subscription.objects.values("user_id"))
    qs = qs.exclude(pk__in=PayoutAccount.objects.filter(verified=True).values("handyman_id"))
    return qs


# ------------------------------------------------------------------ plan
@dataclass
class Outcome:
    kind: str                       # "user" | "booking"
    obj_id: int
    label: str
    action: str                     # "delete" | "anonymize" | "refuse"
    reasons: List[str] = field(default_factory=list)
    demo: bool = False


def _user_label(u) -> str:
    return f"Compte #{u.pk} ({u.username})"


def plan_users(users, *, confirm_fictive: bool = False, actor=None) -> List[Outcome]:
    from handy.account_deletion import blockers
    from handy.models import Booking

    out: List[Outcome] = []
    selected_ids = {u.pk for u in users}
    for u in users:
        demo_reasons = demo_failures(u)
        demo = not demo_reasons
        base = dict(kind="user", obj_id=u.pk, label=_user_label(u), demo=demo)
        if u.is_staff or u.is_superuser:
            out.append(Outcome(action="refuse", reasons=["compte d'administration : à gérer depuis « Sécurité et audit »"], **base))
            continue
        if actor is not None and u.pk == actor.pk:
            out.append(Outcome(action="refuse", reasons=["votre propre compte"], **base))
            continue
        if u.deleted_at is not None:
            out.append(Outcome(action="refuse", reasons=["compte déjà anonymisé"], **base))
            continue
        money = money_reasons_for_users([u.pk])
        if money:
            reasons = ["argent réel conservé : " + ", ".join(money)]
            pending = blockers(u)
            if pending:
                out.append(Outcome(action="refuse", reasons=reasons + [b["detail"] for b in pending], **base))
            else:
                out.append(Outcome(action="anonymize", reasons=reasons + ["le compte est anonymisé, les écritures financières restent"], **base))
            continue
        # Réservations avec des comptes RÉELS hors sélection : les supprimer effacerait leurs données.
        others = set(Booking.objects.filter(client=u).values_list("handyman_id", flat=True)) | set(Booking.objects.filter(handyman=u).values_list("client_id", flat=True))
        real_others = [o for o in others - selected_ids if o is not None and not looks_demo(User.objects.get(pk=o))]
        if demo or confirm_fictive:
            if real_others and not confirm_fictive:
                out.append(Outcome(action="anonymize", reasons=[f"{len(real_others)} réservation(s) avec des comptes réels : anonymisation plutôt que suppression"], **base))
            else:
                reasons = [] if demo else ["ne ressemble pas à une donnée fictive : suppression confirmée par la case « données fictives »"] + demo_reasons
                out.append(Outcome(action="delete", reasons=reasons, **base))
            continue
        pending = blockers(u)
        why = ["ne ressemble pas à une donnée fictive (" + ", ".join(demo_reasons) + ")"]
        if pending:
            out.append(Outcome(action="refuse", reasons=why + [b["detail"] for b in pending], **base))
        else:
            out.append(Outcome(action="anonymize", reasons=why + ["anonymisé ; cochez « données fictives » pour le supprimer vraiment"], **base))
    return out


def plan_bookings(bookings, *, confirm_fictive: bool = False, actor=None) -> List[Outcome]:
    out: List[Outcome] = []
    for b in bookings:
        client_failures, pro_failures = demo_failures(b.client), demo_failures(b.handyman)
        demo = not client_failures and not pro_failures
        base = dict(kind="booking", obj_id=b.pk, label=f"Réservation #{b.pk}", demo=demo)
        money = money_reasons_for_bookings([b.pk])
        if money:
            out.append(Outcome(action="refuse", reasons=money + ["annulez la réservation plutôt que de la supprimer"], **base))
        elif demo or confirm_fictive:
            reasons = [] if demo else ["parties qui ne ressemblent pas à des données fictives : suppression confirmée par la case « données fictives »"]
            out.append(Outcome(action="delete", reasons=reasons, **base))
        else:
            out.append(Outcome(action="refuse", reasons=["réservation de comptes réels : annulez-la, ou cochez « données fictives » si ce sont des essais"], **base))
    return out


# ------------------------------------------------------------------ exécution
@dataclass
class Report:
    counts: Counter = field(default_factory=Counter)
    deleted: List[str] = field(default_factory=list)
    anonymized: List[str] = field(default_factory=list)
    refused: List[tuple] = field(default_factory=list)
    applied: bool = False


def execute(outcomes: List[Outcome], *, apply: bool, actor=None) -> Report:
    """`apply=False` : tout est exécuté puis ANNULÉ (comptage exact). Chaque suppression a son point de retour : un échec n'emporte pas les autres."""
    from handy.account_deletion import DeletionRefused, delete_account
    from handy.models import Booking

    report = Report(applied=apply)
    with transaction.atomic():
        for o in outcomes:
            if o.action == "refuse":
                report.refused.append((o.label, o.reasons))
                continue
            if o.action == "anonymize":
                if apply:
                    try:
                        delete_account(User.objects.get(pk=o.obj_id), actor=actor)
                        report.anonymized.append(o.label)
                    except DeletionRefused as exc:
                        report.refused.append((o.label, [b["detail"] for b in exc.blockers]))
                else:
                    report.anonymized.append(o.label)               # prévu : non exécuté pendant l'aperçu (fichiers, révocations de session)
                continue
            model = User if o.kind == "user" else Booking
            try:
                with transaction.atomic():
                    cascade_delete(model.objects.get(pk=o.obj_id), report.counts)
                report.deleted.append(o.label)
            except RealMoneyError as exc:
                report.refused.append((o.label, [f"argent réel atteint ({exc}) : conservé"]))
            except model.DoesNotExist:
                report.refused.append((o.label, ["introuvable (déjà supprimé ?)"]))
            except Exception as exc:  # noqa: BLE001 — l'opération continue pour les autres éléments
                report.refused.append((o.label, [f"suppression impossible : {exc.__class__.__name__}"]))
        if not apply:
            transaction.set_rollback(True)
    if apply:
        from trust.models import audit

        audit("admin.safe_delete", actor=actor, target_type=outcomes[0].kind if outcomes else "", ids=[o.obj_id for o in outcomes][:200],
              deleted=len(report.deleted), anonymized=len(report.anonymized), refused=len(report.refused), objects=sum(report.counts.values()))
    return report
