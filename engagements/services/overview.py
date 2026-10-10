"""Tableau de bord des engagements : « à faire » (ce qui attend une réponse de l'utilisateur) et compteurs. Source unique pour le web,
Flutter, la bannière de continuité et les pastilles : même règle partout."""
from django.db.models import Q
from django.utils import timezone

from engagements.models import (
    ContractAmendment, ContractInstallment, EngagementApplication, EngagementContract, EngagementInterview, EngagementPosting, InstallmentLine, InstallmentPayment, ScheduleEvent,
)
from engagements.services.common import contracts_for, managed_org_ids, party_of

CAP = 40
LIVE = EngagementContract.LIVE


def _item(kind, label, contract=None, *, when=None, **extra):
    out = {"kind": kind, "label": label, "contract_id": contract.pk if contract is not None else None, "title": contract.title if contract is not None else extra.pop("title", ""), "at": when}
    out.update(extra)
    return out


def todo_for(user) -> list:
    items = []
    mine = contracts_for(user)
    roles = {}

    def role_of(c):
        if c.pk not in roles:
            roles[c.pk] = party_of(c, user)
        return roles[c.pk]

    for c in mine.filter(status="pending_acceptance").select_related("principal", "worker", "organization")[:CAP]:
        done = set(c.acceptances.filter(terms_version=c.terms_version).values_list("role", flat=True))
        if role_of(c) and role_of(c) not in done:
            items.append(_item("accept_contract", "Contrat à relire et accepter", c, when=c.updated_at))
    live = list(mine.filter(status__in=LIVE).select_related("principal", "worker", "organization"))
    by_id = {c.pk: c for c in live}
    for a in ContractAmendment.objects.filter(contract_id__in=by_id, status="proposed").select_related("proposed_by")[:CAP]:
        c = by_id[a.contract_id]
        if role_of(c) != party_of(c, a.proposed_by):
            items.append(_item("answer_amendment", "Avenant à valider", c, when=a.created_at))
    for p in InstallmentPayment.objects.filter(installment__contract_id__in=by_id, status="declared").select_related("installment")[:CAP]:
        c = by_id[p.installment.contract_id]
        if role_of(c) != p.declared_by_role:
            items.append(_item("confirm_payment", f"Paiement de {p.amount} {c.currency} à confirmer", c, when=p.declared_at, installment_id=p.installment_id))
    for l in InstallmentLine.objects.filter(installment__contract_id__in=by_id, status="proposed").select_related("installment", "proposed_by")[:CAP]:
        c = by_id[l.installment.contract_id]
        if role_of(c) != party_of(c, l.proposed_by):
            items.append(_item("answer_adjustment", "Ajustement de rémunération à valider", c, when=l.created_at, installment_id=l.installment_id))
    for e in ScheduleEvent.objects.filter(contract_id__in=by_id, status="requested").select_related("requested_by")[:CAP]:
        c = by_id[e.contract_id]
        requester = party_of(c, e.requested_by) if e.requested_by_id else None
        if role_of(c) and role_of(c) != requester and (e.kind != "replacement" or e.replacement_status == "accepted"):
            items.append(_item("validate_event", "Demande de planning à valider", c, when=e.created_at, event_id=e.pk))
    for e in ScheduleEvent.objects.filter(contract_id__in=by_id, attendance_status="declared").select_related("contract")[:CAP]:
        c = by_id[e.contract_id]
        if role_of(c) == "principal":
            items.append(_item("confirm_attendance", f"Présence du {e.date:%d/%m/%Y} à confirmer", c, when=e.declared_at, event_id=e.pk))
    for i in ContractInstallment.objects.filter(contract_id__in=by_id, status__in=("due", "overdue")).order_by("due_date")[:CAP]:
        c = by_id[i.contract_id]
        if role_of(c) == "principal":
            items.append(_item("pay_installment", f"Échéance {i.sequence + 1} à régler" + (" (en retard)" if i.status == "overdue" else ""), c, when=i.due_date, installment_id=i.pk, overdue=i.status == "overdue"))
        elif role_of(c) == "worker" and i.status == "overdue":
            items.append(_item("late_installment", f"Échéance {i.sequence + 1} non réglée", c, when=i.due_date, installment_id=i.pk, overdue=True))
    for e in ScheduleEvent.objects.filter(replacement_worker=user, replacement_status="proposed", status="requested").select_related("contract")[:CAP]:
        items.append(_item("answer_replacement", f"Remplacement proposé le {e.date:%d/%m/%Y}", e.contract, when=e.created_at, event_id=e.pk))
    own = Q(posting__publisher=user, posting__organization__isnull=True) | Q(posting__organization_id__in=managed_org_ids(user))
    own_postings = EngagementApplication.objects.filter(own, status__in=("submitted", "shortlisted")).select_related("posting")[:CAP]
    seen = set()
    for a in own_postings:
        if a.posting_id in seen:
            continue
        seen.add(a.posting_id)
        n = EngagementApplication.objects.filter(posting_id=a.posting_id, status="submitted").count()
        if n:
            items.append(_item("review_applications", f"{n} candidature(s) à examiner", None, when=a.created_at, posting_id=a.posting_id, title=a.posting.title))
    for i in EngagementInterview.objects.filter(status="proposed").filter(Q(application__applicant=user) | Q(application__posting__publisher=user, application__posting__organization__isnull=True) | Q(application__posting__organization_id__in=managed_org_ids(user))).exclude(proposed_by=user).select_related("application__posting")[:CAP]:
        items.append(_item("answer_interview", "Entretien proposé à confirmer", None, when=i.created_at, posting_id=i.application.posting_id, title=i.application.posting.title))
    items.sort(key=lambda x: (x["at"] is None, x["at"] or timezone.now()))
    return items[:CAP]


def organizations_for(user) -> list:
    """Organisations au nom desquelles `user` peut publier un besoin ou engager un contrat (adhésion active + capacité)."""
    from business.models import Organization

    return [{"id": o.pk, "name": o.name} for o in Organization.objects.filter(pk__in=managed_org_ids(user), is_active=True).order_by("name")]


def overview(user) -> dict:
    mine = contracts_for(user)
    counts = {s: mine.filter(status=s).count() for s in ("pending_acceptance", "active", "suspended", "notice")}
    todo = todo_for(user)
    return {"counts": counts, "todo_count": len(todo), "todo": todo, "organizations": organizations_for(user),
            "postings_open": EngagementPosting.objects.filter(Q(publisher=user, organization__isnull=True) | Q(organization_id__in=managed_org_ids(user)), status="open").count(), "applications_active": user.engagement_applications.filter(status__in=("submitted", "shortlisted", "interview", "selected")).count()}
