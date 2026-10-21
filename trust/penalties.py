"""Pénalités Tratra Trust : uniquement sur des FAITS VÉRIFIABLES, toujours expliquées, contestables, décidées par un humain en cas de recours.

- Automatique : désistement d'un professionnel APRÈS une acceptation ferme Tratra Flash (au-delà du délai de grâce : erreur de
  manipulation). Le fait est daté par le journal de la réservation (qui a annulé, quand) et celui du Smart Dispatch (quand il a accepté).
- Par l'équipe : absence ou manquement constaté sur une mission précise, avec explication et éléments.
- Jamais : refus d'une proposition, absence de réponse, pause de disponibilité.
Une pénalité contestée reste comptée jusqu'à la décision ; retenue → annulée (le score est recalculé aussitôt)."""
from datetime import timedelta
from typing import Dict, Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from trust.models import TrustConfig, TrustPenalty, audit


class PenaltyError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _reevaluate(user_id: int) -> None:
    from trust.engine import evaluate_user

    evaluate_user(user_id, trigger="penalty")


def _notify(penalty: TrustPenalty, text: str, title: str) -> None:
    from handy.notifications import notify

    notify(penalty.user_id, "trust_penalty", text, title=title, data={"kind": "trust_penalty", "id": penalty.pk},
           dedupe_key=f"trust:penalty:{penalty.pk}:{penalty.status}:{(penalty.decided_at or penalty.created_at):%Y%m%d%H%M%S}")


def record_withdrawal(booking, *, accepted_at, cancelled_at, actor_id) -> Optional[TrustPenalty]:
    """Désistement après acceptation ferme : fait constaté automatiquement (idempotent)."""
    with transaction.atomic():
        try:
            penalty = TrustPenalty.objects.create(
                user_id=booking.handyman_id, kind=TrustPenalty.WITHDRAWAL, booking=booking,
                explanation=f"Mission #{booking.pk} acceptée le {timezone.localtime(accepted_at):%d/%m/%Y à %H:%M} puis annulée par vous "
                            f"le {timezone.localtime(cancelled_at):%d/%m/%Y à %H:%M}.",
                evidence={"booking": booking.pk, "accepted_at": accepted_at.isoformat(), "cancelled_at": cancelled_at.isoformat(),
                          "cancelled_by": actor_id, "source": "journal de la réservation et du Smart Dispatch"})
        except IntegrityError:
            return None
        audit("trust.penalty_recorded", target_type="user", target_id=booking.handyman_id, penalty=penalty.pk, kind=penalty.kind,
              booking=booking.pk)
        transaction.on_commit(lambda: (_notify(penalty, f"{penalty.explanation} Cela compte dans « Engagements tenus ». Vous pouvez contester.",
                                               "Désistement enregistré"), _reevaluate(penalty.user_id)))
    return penalty


def record_by_staff(*, user, kind: str, booking, explanation: str, evidence: Dict, staff) -> TrustPenalty:
    if kind not in (TrustPenalty.NO_SHOW, TrustPenalty.OTHER):
        raise PenaltyError("invalid_kind", "Type de pénalité non autorisé ici.")
    if booking is None or booking.handyman_id != user.pk:
        raise PenaltyError("booking_required", "Une pénalité s'appuie sur une mission précise de ce professionnel.")
    if len((explanation or "").strip()) < 20:
        raise PenaltyError("explanation_required", "Expliquez le fait constaté (20 caractères au moins).")
    with transaction.atomic():
        try:
            penalty = TrustPenalty.objects.create(user=user, kind=kind, booking=booking, explanation=explanation.strip()[:500],
                                                  evidence={**(evidence or {}), "booking": booking.pk}, created_by=staff)
        except IntegrityError:
            raise PenaltyError("duplicate", "Cette pénalité existe déjà pour cette mission.", 409)
        audit("trust.penalty_recorded", actor=staff, target_type="user", target_id=user.pk, penalty=penalty.pk, kind=kind, booking=booking.pk)
        transaction.on_commit(lambda: (_notify(penalty, f"{penalty.explanation} Vous pouvez contester cette décision.",
                                               "Manquement enregistré"), _reevaluate(user.pk)))
    return penalty


def contest(penalty_id: int, user, reason: str) -> TrustPenalty:
    reason = (reason or "").strip()
    if len(reason) < 10:
        raise PenaltyError("reason_required", "Expliquez votre contestation (10 caractères au moins).")
    with transaction.atomic():
        penalty = TrustPenalty.objects.select_for_update().filter(pk=penalty_id, user=user).first()
        if penalty is None:
            raise PenaltyError("not_found", "Pénalité introuvable.", 404)
        if penalty.status == TrustPenalty.CONTESTED:
            return penalty
        if penalty.status != TrustPenalty.ACTIVE or penalty.decided_at is not None:
            raise PenaltyError("not_contestable", "Cette pénalité a déjà été examinée.", 409)
        penalty.status, penalty.contest_reason, penalty.contested_at = TrustPenalty.CONTESTED, reason[:1000], timezone.now()
        penalty.save(update_fields=["status", "contest_reason", "contested_at"])
        audit("trust.penalty_contested", actor=user, target_type="user", target_id=user.pk, penalty=penalty.pk)
    return penalty


def decide(penalty_id: int, staff, *, uphold_contest: bool, note: str) -> TrustPenalty:
    """Décision humaine motivée : contestation retenue → pénalité annulée ; rejetée → pénalité maintenue."""
    note = (note or "").strip()
    if len(note) < 10:
        raise PenaltyError("note_required", "Motivez la décision (10 caractères au moins).")
    with transaction.atomic():
        penalty = TrustPenalty.objects.select_for_update().filter(pk=penalty_id).first()
        if penalty is None:
            raise PenaltyError("not_found", "Pénalité introuvable.", 404)
        if penalty.status == TrustPenalty.CANCELLED:
            raise PenaltyError("already_cancelled", "Cette pénalité est déjà annulée.", 409)
        penalty.status = TrustPenalty.CANCELLED if uphold_contest else TrustPenalty.ACTIVE
        penalty.decided_by, penalty.decided_at, penalty.decision_note = staff, timezone.now(), note[:500]
        penalty.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
        audit("trust.penalty_cancelled" if uphold_contest else "trust.penalty_upheld", actor=staff, target_type="user",
              target_id=penalty.user_id, penalty=penalty.pk, note=note[:300])
        text = ("Votre contestation est retenue : la pénalité est annulée. " if uphold_contest
                else "Votre contestation n'est pas retenue : la pénalité est maintenue. ") + note[:300]
        transaction.on_commit(lambda: (_notify(penalty, text, "Décision sur votre contestation"), _reevaluate(penalty.user_id)))
    return penalty


def counted(user_id: int, config: TrustConfig = None, now=None):
    config = config or TrustConfig.get_solo()
    since = (now or timezone.now()) - timedelta(days=config.penalty_validity_days)
    return TrustPenalty.objects.filter(user_id=user_id, status__in=TrustPenalty.COUNTED, created_at__gte=since)


def payload(p: TrustPenalty) -> Dict:
    return {"id": p.pk, "kind": p.kind, "kind_label": p.get_kind_display(), "status": p.status, "status_label": p.get_status_display(),
            "explanation": p.explanation, "evidence": p.evidence, "booking": p.booking_id, "created_at": p.created_at,
            "by_team": p.created_by_id is not None, "contest_reason": p.contest_reason, "contested_at": p.contested_at,
            "decided_at": p.decided_at, "decision_note": p.decision_note,
            "can_contest": p.status == TrustPenalty.ACTIVE and p.decided_at is None}
