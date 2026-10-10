"""Litiges d'un engagement : ouverts par l'une des parties, traités par le Back-Office (jamais de modification des montants : la
plateforme suspend, résilie ou médie, elle ne « corrige » pas un paiement)."""
from typing import Optional

from django.db import transaction
from django.utils import timezone

from engagements.models import ContractInstallment, EngagementContract, EngagementDispute
from engagements.services.common import EngagementError, conflict, counterpart, notify_role, party_of, record
from engagements.services.validation import Validator

KINDS = {k for k, _ in EngagementDispute.KINDS}
RESOLUTION_ACTIONS = {"none", "mediated", "suspend", "terminate"}      # « échéance abandonnée » reste la décision du prestataire


@transaction.atomic
def open_dispute(contract: EngagementContract, user, data: dict) -> EngagementDispute:
    contract = EngagementContract.objects.select_for_update().get(pk=contract.pk)
    role = party_of(contract, user)
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    if contract.status in ("draft", "pending_acceptance", "cancelled"):
        raise conflict("contract_not_live", "Un litige concerne un contrat accepté.")
    v = Validator()
    kind = v.choice(data, "kind", label="Nature", allowed=KINDS)
    reason = v.text(data, "reason", label="Motif", max_len=2000, min_len=10, required=True)
    v.raise_if()
    installment: Optional[ContractInstallment] = None
    if data.get("installment"):
        installment = contract.installments.filter(pk=data.get("installment")).first()
        if installment is None:
            raise EngagementError("invalid", "Échéance inconnue pour ce contrat.", 400, fields={"installment": "Échéance introuvable."})
    if EngagementDispute.objects.filter(contract=contract, opened_by=user, kind=kind, installment=installment, status__in=("open", "under_review")).exists():
        raise conflict("dispute_exists", "Un litige de même nature est déjà en cours.")
    dispute = EngagementDispute.objects.create(contract=contract, installment=installment, opened_by=user, kind=kind, reason=reason)
    record(contract, user, "dispute_opened", dispute=dispute.pk, kind=kind)
    notify_role(contract, counterpart(role), "engagement_dispute", f"Un litige a été ouvert sur « {contract.title} » ({dispute.get_kind_display().lower()}).", title="Litige ouvert",
                key=f"dispute-{dispute.pk}-opened")
    return dispute


@transaction.atomic
def take_review(dispute: EngagementDispute, admin) -> EngagementDispute:
    dispute = EngagementDispute.objects.select_for_update(of=("self",)).select_related("contract").get(pk=dispute.pk)
    if dispute.status == "under_review":
        return dispute
    if dispute.status != "open":
        raise conflict("not_open", "Ce litige est déjà clos.")
    dispute.status = "under_review"
    dispute.save(update_fields=["status", "updated_at"])
    record(dispute.contract, admin, "dispute_review", dispute=dispute.pk)
    return dispute


@transaction.atomic
def resolve(dispute: EngagementDispute, admin, *, accepted: bool, resolution: str, action: str = "none") -> EngagementDispute:
    dispute = EngagementDispute.objects.select_for_update(of=("self",)).select_related("contract").get(pk=dispute.pk)
    if dispute.status not in ("open", "under_review"):
        raise conflict("not_open", "Ce litige est déjà clos.")
    resolution = (resolution or "").strip()[:2000]
    if len(resolution) < 10:
        raise EngagementError("invalid", "Expliquez la décision (10 caractères au minimum).", 400, fields={"resolution": "Décision obligatoire."})
    if action not in RESOLUTION_ACTIONS:
        raise EngagementError("invalid", "Action de résolution inconnue.", 400, fields={"resolution_action": "Valeur invalide."})
    dispute.status, dispute.resolution, dispute.resolution_action = ("resolved" if accepted else "rejected"), resolution, action
    dispute.resolved_by, dispute.resolved_at = admin, timezone.now()
    dispute.save(update_fields=["status", "resolution", "resolution_action", "resolved_by", "resolved_at", "updated_at"])
    record(dispute.contract, admin, "dispute_resolved", dispute=dispute.pk, status=dispute.status, resolution_action=action)
    for role in ("principal", "worker"):
        notify_role(dispute.contract, role, "engagement_dispute", f"Le litige sur « {dispute.contract.title} » est {'résolu' if accepted else 'rejeté'} : {resolution[:140]}",
                    title="Litige traité", key=f"dispute-{dispute.pk}-closed")
    return dispute
