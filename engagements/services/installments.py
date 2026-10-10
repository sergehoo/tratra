"""Échéances de rémunération : génération automatique et idempotente, ajustements acceptés, paiements DÉCLARÉS puis CONFIRMÉS
par la contrepartie, retards. Aucune confirmation fictive : sans confirmation de l'autre partie, un paiement ne compte pas.

Tratra ne calcule AUCUN élément légal (cotisations, impôts, congés payés, salaire minimum) : les montants sont ceux du contrat
(avec, si les parties l'ont convenu, un prorata par jours calendaires sur la dernière période) et des ajustements acceptés."""
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from engagements.dates import add_months, next_payment_date, period_bounds
from engagements.models import ContractInstallment, EngagementContract, InstallmentLine, InstallmentPayment
from engagements.rules import HORIZON_PERIODS, rules_for
from engagements.services.common import EngagementError, conflict, counterpart, notify_role, party_of, record
from engagements.services.evidence import clean_evidence
from engagements.services.validation import Validator

ZERO = Decimal("0.00")
LIVE_FOR_PAYMENT = ("accepted", "active", "suspended", "notice", "terminated", "completed")


def q(value) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def _suspended(contract: EngagementContract, ps: date, pe: date) -> bool:
    """La période est-elle ENTIÈREMENT couverte par une suspension (fenêtres [début, fin[) ?"""
    day = ps
    windows = list(contract.suspensions.all())
    while day <= pe:
        if not any(w.starts_on <= day and (w.ends_on is None or day < w.ends_on) for w in windows):
            return False
        day += timedelta(days=1)
    return True


def _fee(contract: EngagementContract, base: Optional[Decimal]):
    rules = rules_for(contract.category_id)
    percent = rules.commission_percent(contract.work_relationship)
    if not base or percent <= 0:
        return ZERO, "none", rules.commission_payer
    return q((base * percent / Decimal("100")).quantize(Decimal("1."))), "due", rules.commission_payer


def _base_for(contract: EngagementContract, ps: date, pe: date, eff_end: Optional[date]):
    """(base, fin de période effective) d'une période : montant plein, prorata convenu, ou None si calculé en fin de période."""
    if contract.period != "monthly":
        return None, min(pe, eff_end) if eff_end else pe
    if eff_end and pe > eff_end:
        if contract.proration_mode == "calendar_days":
            full, part = (pe - ps).days + 1, (eff_end - ps).days + 1
            return q(contract.amount * Decimal(part) / Decimal(full)), eff_end
        return q(contract.amount), eff_end
    return q(contract.amount), pe


def generate_installments(contract: EngagementContract, today: Optional[date] = None) -> int:
    """Crée les échéances manquantes jusqu'à l'horizon (3 périodes) et jusqu'à la fin effective du contrat. IDEMPOTENT : une
    échéance existe au plus une fois par numéro d'ordre ; une échéance existante n'est jamais réécrite ici."""
    today = today or timezone.localdate()
    if contract.status not in ("accepted", "active", "suspended", "notice"):
        return 0
    anchor = max(today, contract.start_date)
    horizon = add_months(anchor, HORIZON_PERIODS)
    eff_end = contract.effective_end
    last = contract.installments.order_by("-sequence").values_list("sequence", flat=True).first()
    k, created = (last + 1) if last is not None else 0, 0
    while True:
        ps, pe = period_bounds(contract.start_date, k)
        if ps > horizon or (eff_end and ps > eff_end):
            break
        base, pe_eff = _base_for(contract, ps, pe, eff_end)
        on_hold = _suspended(contract, ps, pe_eff)
        if on_hold:
            base = ZERO
        fee, fee_status, payer = _fee(contract, base)
        _, was_created = ContractInstallment.objects.get_or_create(
            contract=contract, sequence=k,
            defaults=dict(period_start=ps, period_end=pe_eff, due_date=next_payment_date(pe_eff, contract.payment_day), base_amount=base, currency=contract.currency,
                          terms_version=contract.terms_version, platform_fee=fee, platform_fee_status=fee_status, platform_fee_payer=payer,
                          status="on_hold" if on_hold else "scheduled", computed_at=timezone.now() if base is not None else None,
                          note="Période suspendue d'un commun accord." if on_hold else ""))
        created += int(was_created)
        k += 1
    return created


def reconcile_end(contract: EngagementContract, today: Optional[date] = None) -> int:
    """Fin anticipée (préavis, fin d'un commun accord) : les échéances de périodes qui commencent après la fin et qui n'ont ni
    paiement ni ajustement sont ANNULÉES (jamais supprimées) ; la dernière période est ramenée au prorata convenu si elle est intacte."""
    eff_end = contract.effective_end
    if not eff_end:
        return 0
    changed = 0
    for inst in contract.installments.filter(status__in=("scheduled", "on_hold")).order_by("sequence"):
        untouched = not inst.payments.exists() and not inst.lines.filter(status="accepted").exists()
        if inst.period_start > eff_end and untouched:
            inst.status, inst.closed_reason = "cancelled", "Période postérieure à la fin du contrat."
            inst.save(update_fields=["status", "closed_reason", "updated_at"])
            changed += 1
        elif inst.period_end > eff_end and untouched and contract.period == "monthly":
            base, pe_eff = _base_for(contract, inst.period_start, period_bounds(contract.start_date, inst.sequence)[1], eff_end)
            fee, fee_status, payer = _fee(contract, base)
            inst.period_end, inst.base_amount, inst.platform_fee, inst.platform_fee_status = pe_eff, base, fee, fee_status
            inst.due_date = next_payment_date(pe_eff, contract.payment_day)
            inst.save(update_fields=["period_end", "base_amount", "platform_fee", "platform_fee_status", "due_date", "updated_at"])
            changed += 1
    return changed


def regenerate_future(contract: EngagementContract, from_date: date, today: Optional[date] = None) -> int:
    """Après un avenant : les échéances NON PAYÉES des périodes qui commencent à la date d'effet ou après reprennent les
    nouvelles conditions. Les périodes déjà commencées ne changent jamais (un avenant n'est pas rétroactif)."""
    n = 0
    for inst in contract.installments.filter(status__in=("scheduled", "on_hold"), period_start__gte=from_date).order_by("sequence"):
        if inst.payments.exists() or inst.lines.filter(status="accepted").exists():
            continue
        ps, pe = period_bounds(contract.start_date, inst.sequence)
        base, pe_eff = _base_for(contract, ps, pe, contract.effective_end)
        hold = _suspended(contract, ps, pe_eff)
        if hold:
            base = ZERO
        fee, fee_status, payer = _fee(contract, base)
        inst.period_end, inst.base_amount, inst.platform_fee, inst.platform_fee_status, inst.platform_fee_payer = pe_eff, base, fee, fee_status, payer
        inst.due_date, inst.terms_version = next_payment_date(pe_eff, contract.payment_day), contract.terms_version
        inst.status = "on_hold" if hold else "scheduled"
        inst.computed_at = timezone.now() if base is not None else None
        inst.save()
        n += 1
    generate_installments(contract, today)
    return n


# ── Montants et statuts ─────────────────────────────────────────────────────────────────────────────────────────────

def totals(inst: ContractInstallment) -> dict:
    confirmed = inst.payments.filter(status="confirmed").aggregate(t=Sum("amount"))["t"] or ZERO
    declared = inst.payments.filter(status="declared").aggregate(t=Sum("amount"))["t"] or ZERO
    adjustments = inst.lines.filter(status="accepted").aggregate(t=Sum("amount"))["t"] or ZERO
    base = inst.base_amount or ZERO
    total = q(base + adjustments)
    return {"base": q(base), "adjustments": q(adjustments), "total": total, "confirmed": q(confirmed), "declared": q(declared),
            "balance": q(total - confirmed), "remaining_to_declare": q(max(total - confirmed - declared, ZERO))}


def refresh_installment(inst: ContractInstallment, today: Optional[date] = None) -> bool:
    """Recalcule le statut à partir des paiements CONFIRMÉS, des ajustements acceptés et de la date. Renvoie True si modifié."""
    today = today or timezone.localdate()
    if inst.status in ("waived", "cancelled"):
        return False
    t = totals(inst)
    grace = rules_for(inst.contract.category_id).late_grace_days
    if inst.base_amount is None and today <= inst.period_end:
        new = "scheduled"
    elif inst.status == "on_hold" and t["total"] == 0:
        new = "on_hold"
    elif t["total"] > 0 and t["balance"] <= 0:
        new = "paid"
    elif t["confirmed"] > 0:
        new = "overdue" if today > inst.due_date + timedelta(days=grace) else "partial"
    elif today > inst.due_date + timedelta(days=grace) and t["total"] > 0:
        new = "overdue"
    elif today >= inst.due_date and t["total"] > 0:
        new = "due"
    else:
        new = "scheduled"
    if new != inst.status:
        inst.status = new
        inst.save(update_fields=["status", "updated_at"])
        return True
    return False


def compute_variable(inst: ContractInstallment, today: Optional[date] = None) -> bool:
    """Rémunération à l'heure / à l'intervention : montant calculé UNE FOIS la période terminée, à partir des présences
    CONFIRMÉES par le donneur d'ordre (jamais de décompte déclaré par une seule partie)."""
    today = today or timezone.localdate()
    c = inst.contract
    if c.period == "monthly" or inst.base_amount is not None or today <= inst.period_end:
        return False
    events = c.schedule_events.filter(kind="shift", date__gte=inst.period_start, date__lte=inst.period_end, attendance_status="confirmed").exclude(status__in=("cancelled", "replaced"))
    if c.period == "per_visit":
        base = q(c.amount * events.count())
    else:
        base = q(c.amount * (events.aggregate(h=Sum("hours"))["h"] or ZERO))
    fee, fee_status, payer = _fee(c, base)
    inst.base_amount, inst.platform_fee, inst.platform_fee_status, inst.platform_fee_payer, inst.computed_at = base, fee, fee_status, payer, timezone.now()
    inst.save(update_fields=["base_amount", "platform_fee", "platform_fee_status", "platform_fee_payer", "computed_at", "updated_at"])
    refresh_installment(inst, today)
    return True


# ── Ajustements ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _open_for_money(inst: ContractInstallment) -> None:
    if inst.status in ("waived", "cancelled", "paid"):
        raise conflict("installment_closed", "Cette échéance est close.")
    if inst.contract.status not in LIVE_FOR_PAYMENT:
        raise conflict("contract_not_live", "Ce contrat n'est pas en vigueur.")


@transaction.atomic
def propose_line(inst: ContractInstallment, user, data: dict, evidence=None) -> InstallmentLine:
    inst = ContractInstallment.objects.select_for_update(of=("self",)).select_related("contract").get(pk=inst.pk)
    role = party_of(inst.contract, user)
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    _open_for_money(inst)
    v = Validator()
    kind = v.choice(data, "kind", label="Nature", allowed={k for k, _ in InstallmentLine.KINDS if k != "overtime"})
    amount = v.amount(data, "amount", label="Montant", required=True)
    description = v.text(data, "description", label="Description", max_len=300, min_len=3, required=True)
    v.raise_if()
    if kind in ("deduction",):
        amount = -abs(amount)
    elif kind in ("bonus", "expense"):
        amount = abs(amount)
    t = totals(inst)
    if t["total"] + amount < 0 or (kind == "deduction" and abs(amount) > t["base"]):
        raise EngagementError("invalid", "Cet ajustement rendrait la rémunération négative.", 400, fields={"amount": "Montant trop élevé par rapport à l'échéance."})
    cleaned = clean_evidence(evidence)
    line = InstallmentLine.objects.create(installment=inst, kind=kind, amount=amount, description=description, proposed_by=user, evidence=cleaned)
    record(inst.contract, user, "adjustment_proposed", installment=inst.sequence, kind=kind, amount=amount)
    notify_role(inst.contract, counterpart(role), "payment_declared", f"Ajustement proposé sur l'échéance {inst.sequence + 1} : {description}.",
                title="Ajustement à valider", key=f"line-{line.pk}-proposed")
    return line


@transaction.atomic
def respond_line(line: InstallmentLine, user, accept: bool) -> InstallmentLine:
    line = InstallmentLine.objects.select_for_update(of=("self",)).select_related("installment", "installment__contract", "proposed_by").get(pk=line.pk)
    inst, contract = line.installment, line.installment.contract
    role = party_of(contract, user)
    proposer_role = party_of(contract, line.proposed_by)
    if role is None or role == proposer_role:
        raise EngagementError("forbidden", "C'est à l'autre partie de répondre à cet ajustement.", 403)
    if line.status != "proposed":
        raise conflict("not_open", "Cet ajustement a déjà reçu une réponse.")
    _open_for_money(inst)
    line.status, line.responded_by, line.responded_at = ("accepted" if accept else "rejected"), user, timezone.now()
    line.save(update_fields=["status", "responded_by", "responded_at"])
    refresh_installment(inst)
    record(contract, user, "adjustment_accepted" if accept else "adjustment_rejected", installment=inst.sequence, kind=line.kind, amount=line.amount)
    notify_role(contract, counterpart(role), "payment_confirmed", f"Ajustement {'accepté' if accept else 'refusé'} sur l'échéance {inst.sequence + 1}.",
                title="Ajustement " + ("accepté" if accept else "refusé"), key=f"line-{line.pk}-{'ok' if accept else 'ko'}")
    return line


# ── Paiements ───────────────────────────────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def declare_payment(inst: ContractInstallment, user, data: dict, evidence=None, today: Optional[date] = None) -> InstallmentPayment:
    """Déclare un paiement (virement, espèces, Mobile Money…) : il ne COMPTE qu'une fois confirmé par l'autre partie."""
    today = today or timezone.localdate()
    inst = ContractInstallment.objects.select_for_update(of=("self",)).select_related("contract").get(pk=inst.pk)
    contract = inst.contract
    role = party_of(contract, user)
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    _open_for_money(inst)
    if inst.base_amount is None:
        raise conflict("not_computed", "Le montant de cette échéance sera connu à la fin de la période.")
    v = Validator()
    amount = v.amount(data, "amount", label="Montant", required=True)
    method = v.choice(data, "method", label="Moyen de paiement", allowed={k for k, _ in InstallmentPayment.METHODS})
    reference = v.text(data, "reference", label="Référence", max_len=100)
    paid_on = v.date(data, "paid_on", label="Date du paiement", required=True)
    v.raise_if()
    if paid_on > today:
        raise EngagementError("invalid", "La date du paiement ne peut pas être dans le futur.", 400, fields={"paid_on": "Date dans le futur."})
    t = totals(inst)
    if amount > t["remaining_to_declare"]:
        raise EngagementError("invalid", "Ce paiement dépasse le solde restant à payer.", 400,
                              fields={"amount": f"Solde restant : {t['remaining_to_declare']}."}, remaining=str(t["remaining_to_declare"]))
    if inst.payments.filter(declared_by=user, amount=amount, method=method, paid_on=paid_on, reference=reference).exclude(status="rejected").exists():
        raise conflict("duplicate_payment", "Ce paiement a déjà été déclaré.")
    is_advance = today <= inst.period_end
    if is_advance:
        cap = q((inst.base_amount or ZERO) * Decimal(rules_for(contract.category_id).max_advance_percent) / Decimal("100"))
        already = inst.payments.exclude(status="rejected").filter(is_advance=True).aggregate(t=Sum("amount"))["t"] or ZERO
        if already + amount > cap:
            raise EngagementError("invalid", f"Avance limitée à {rules_for(contract.category_id).max_advance_percent} % de l'échéance (reste autorisé : {max(cap - already, ZERO)}).", 400,
                                  fields={"amount": "Avance trop élevée."})
    payment = InstallmentPayment.objects.create(installment=inst, amount=amount, method=method, reference=reference, paid_on=paid_on, is_advance=is_advance,
                                                declared_by=user, declared_by_role=role, evidence=clean_evidence(evidence))
    record(contract, user, "payment_declared", installment=inst.sequence, amount=amount, method=method, advance=is_advance)
    notify_role(contract, counterpart(role), "payment_declared",
                f"Un paiement de {amount} {contract.currency} est déclaré pour l'échéance {inst.sequence + 1} : confirmez-le s'il est exact.",
                title="Paiement à confirmer", key=f"pay-{payment.pk}-declared")
    return payment


@transaction.atomic
def respond_payment(payment: InstallmentPayment, user, confirm: bool, reason: str = "", today: Optional[date] = None) -> InstallmentPayment:
    payment = InstallmentPayment.objects.select_for_update(of=("self",)).select_related("installment", "installment__contract").get(pk=payment.pk)
    inst, contract = payment.installment, payment.installment.contract
    role = party_of(contract, user)
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    if role == payment.declared_by_role:
        raise EngagementError("forbidden", "Un paiement doit être confirmé par l'AUTRE partie : jamais par son auteur.", 403)
    if payment.status != "declared":
        raise conflict("not_open", "Ce paiement a déjà reçu une réponse.")
    reason = (reason or "").strip()[:500]
    if not confirm and len(reason) < 5:
        raise EngagementError("invalid", "Indiquez le motif de la contestation (5 caractères au minimum).", 400, fields={"reason": "Motif obligatoire."})
    payment.status, payment.responded_by, payment.responded_at = ("confirmed" if confirm else "rejected"), user, timezone.now()
    payment.rejection_reason = "" if confirm else reason
    payment.save(update_fields=["status", "responded_by", "responded_at", "rejection_reason"])
    refresh_installment(inst, today)
    record(contract, user, "payment_confirmed" if confirm else "payment_contested", installment=inst.sequence, amount=payment.amount, reason=reason)
    notify_role(contract, payment.declared_by_role, "payment_confirmed",
                f"Votre paiement de {payment.amount} {contract.currency} (échéance {inst.sequence + 1}) est {'confirmé' if confirm else 'contesté : ' + reason}.",
                title="Paiement " + ("confirmé" if confirm else "contesté"), key=f"pay-{payment.pk}-{'ok' if confirm else 'ko'}")
    return payment


@transaction.atomic
def waive(inst: ContractInstallment, user, reason: str) -> ContractInstallment:
    """Le PRESTATAIRE (créancier) abandonne le solde restant : décision de la partie payée, jamais du payeur."""
    inst = ContractInstallment.objects.select_for_update(of=("self",)).select_related("contract").get(pk=inst.pk)
    if party_of(inst.contract, user) != "worker":
        raise EngagementError("forbidden", "Seul le prestataire peut abandonner un solde qui lui est dû.", 403)
    _open_for_money(inst)
    reason = (reason or "").strip()[:500]
    if len(reason) < 5:
        raise EngagementError("invalid", "Indiquez le motif (5 caractères au minimum).", 400, fields={"reason": "Motif obligatoire."})
    inst.status, inst.closed_reason, inst.closed_by = "waived", reason, user
    inst.save(update_fields=["status", "closed_reason", "closed_by", "updated_at"])
    record(inst.contract, user, "installment_waived", installment=inst.sequence, reason=reason)
    notify_role(inst.contract, "principal", "payment_confirmed", f"Le prestataire a abandonné le solde de l'échéance {inst.sequence + 1}.", title="Solde abandonné", key=f"inst-{inst.pk}-waived")
    return inst
