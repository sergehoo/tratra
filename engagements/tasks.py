"""Tâche périodique (toutes les heures, rejouable sans effet double) : fait avancer les engagements avec le calendrier —
activation, suspensions, avenants à échéance, renouvellements, fins de préavis, échéances, planning, réservations des
occurrences — puis envoie les rappels (échéance proche ou en retard, paiement à confirmer, fin de contrat prochaine)."""
import logging
from datetime import date, timedelta
from typing import Optional

from celery import shared_task
from django.utils import timezone

from engagements.models import ContractInstallment, EngagementContract, InstallmentPayment
from engagements.services import contracts as contract_svc
from engagements.services import installments as inst_svc
from engagements.services import postings
from engagements.services.common import notify_role

logger = logging.getLogger(__name__)
BATCH = 500
DUE_SOON_DAYS = 3
ENDING_SOON_DAYS = 30
STALE_PAYMENT_DAYS = 3


def _each(qs):
    for pk in list(qs.values_list("pk", flat=True)[:BATCH]):
        yield pk


def run(today: Optional[date] = None) -> dict:
    today = today or timezone.localdate()
    stats = {"postings_expired": postings.expire_due(today), "contracts": 0, "errors": 0, "installments_refreshed": 0, "reminders": 0}
    live = EngagementContract.objects.filter(status__in=("accepted", "active", "suspended", "notice"))
    for pk in _each(live):
        try:
            contract = EngagementContract.objects.get(pk=pk)
            contract_svc.sync(contract, today)
            stats["contracts"] += 1
        except Exception:  # noqa: BLE001 - un contrat en échec ne bloque pas les autres
            logger.exception("Synchronisation du contrat %s impossible", pk)
            stats["errors"] += 1
    # Échéances : montants variables en fin de période, puis statuts (échue, en retard) — y compris sur contrats terminés non clôturés.
    open_installments = ContractInstallment.objects.filter(status__in=ContractInstallment.OPEN + ("on_hold",)).select_related("contract")
    for pk in _each(open_installments.order_by("due_date")):
        try:
            inst = ContractInstallment.objects.select_related("contract").get(pk=pk)
            inst_svc.compute_variable(inst, today)
            if inst_svc.refresh_installment(inst, today):
                stats["installments_refreshed"] += 1
        except Exception:  # noqa: BLE001
            logger.exception("Mise à jour de l'échéance %s impossible", pk)
            stats["errors"] += 1
    stats["reminders"] = reminders(today)
    return stats


def reminders(today: date) -> int:
    """Rappels dédupliqués (une clé par événement) : jamais deux fois le même."""
    n = 0
    soon = ContractInstallment.objects.filter(status__in=("scheduled", "due"), due_date__gte=today, due_date__lte=today + timedelta(days=DUE_SOON_DAYS), base_amount__gt=0).select_related("contract")
    for inst in soon:
        c = inst.contract
        notify_role(c, "principal", "installment_due", f"Échéance {inst.sequence + 1} de « {c.title} » à régler le {inst.due_date:%d/%m/%Y}.", title="Échéance à venir", key=f"inst-{inst.pk}-soon")
        notify_role(c, "worker", "installment_due", f"Échéance {inst.sequence + 1} de « {c.title} » prévue le {inst.due_date:%d/%m/%Y}.", title="Échéance à venir", key=f"inst-{inst.pk}-soon")
        n += 1
    for inst in ContractInstallment.objects.filter(status="overdue").select_related("contract"):
        c = inst.contract
        notify_role(c, "principal", "installment_overdue", f"L'échéance {inst.sequence + 1} de « {c.title} » est en retard.", title="Échéance en retard", key=f"inst-{inst.pk}-overdue")
        notify_role(c, "worker", "installment_overdue", f"L'échéance {inst.sequence + 1} de « {c.title} » n'est pas réglée.", title="Échéance en retard", key=f"inst-{inst.pk}-overdue")
        n += 1
    cutoff = timezone.now() - timedelta(days=STALE_PAYMENT_DAYS)
    for p in InstallmentPayment.objects.filter(status="declared", declared_at__lte=cutoff).select_related("installment", "installment__contract"):
        c = p.installment.contract
        other = "worker" if p.declared_by_role == "principal" else "principal"
        notify_role(c, other, "payment_declared", f"Un paiement déclaré le {p.declared_at:%d/%m/%Y} attend toujours votre confirmation.", title="Paiement à confirmer", key=f"pay-{p.pk}-stale")
        n += 1
    for c in EngagementContract.objects.filter(status="active", end_date__isnull=False, end_date__gte=today, end_date__lte=today + timedelta(days=ENDING_SOON_DAYS)):
        text = (f"Le contrat « {c.title} » est renouvelé automatiquement le {c.end_date:%d/%m/%Y} sauf non-renouvellement avant le {c.end_date - timedelta(days=c.notice_period_days):%d/%m/%Y}."
                if c.auto_renew and not c.non_renewal_at else f"Le contrat « {c.title} » se termine le {c.end_date:%d/%m/%Y}.")
        for role in ("worker", "principal"):
            notify_role(c, role, "contract_renewal", text, title="Fin de contrat prochaine", key=f"ending-{c.end_date.isoformat()}")
        n += 1
    return n


@shared_task(name="engagements.tasks.tick")
def tick() -> dict:
    return run()
