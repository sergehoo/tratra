"""Représentations JSON des engagements, adaptées au rôle de l'appelant. Jamais de coordonnées, de téléphone ni d'e-mail d'une
partie : seul le nom public est exposé. Les pièces justificatives ne sont jamais des URLs publiques."""
from datetime import timedelta
from typing import Optional

from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from engagements import rules as rules_mod
from engagements.services.quality import coherence_warnings
from engagements.models import (
    ContractAmendment, ContractEvent, ContractInstallment, EngagementApplication, EngagementContract, EngagementDispute, EngagementEvaluation,
    EngagementInterview, EngagementPosting, InstallmentLine, InstallmentPayment, ScheduleEvent,
)
from engagements.services import installments as inst_svc
from engagements.services.common import party_of, principal_side, public_name
from engagements.services.postings import posting_side


def money(value) -> Optional[str]:
    return None if value is None else str(value)


def person(user) -> Optional[dict]:
    return None if user is None else {"id": user.id, "name": public_name(user)}


def evidence_ref(kind: str, obj) -> Optional[dict]:
    if not getattr(obj, "evidence", None):
        return None
    name = obj.evidence.name.rsplit("/", 1)[-1]
    return {"name": name[-60:], "url": reverse("engagements-evidence", args=[kind, obj.pk])}


# ── Règles ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def rules(category_id=None) -> dict:
    return rules_mod.rules_payload(rules_mod.rules_for(category_id))


# ── Besoins, candidatures, entretiens ───────────────────────────────────────────────────────────────────────────────

def interview(i: EngagementInterview, user) -> dict:
    return {"id": i.id, "scheduled_at": i.scheduled_at, "duration_minutes": i.duration_minutes, "mode": i.mode, "place_note": i.place_note, "status": i.status,
            "note": i.note, "proposed_by_me": i.proposed_by_id == user.id, "created_at": i.created_at}


def application(a: EngagementApplication, user, *, with_applicant: bool) -> dict:
    from engagements.services.experience import experience_for

    out = {"id": a.id, "posting": a.posting_id, "posting_title": a.posting.title, "message": a.message, "proposed_amount": money(a.proposed_amount), "available_from": a.available_from,
           "status": a.status, "decision_note": a.decision_note, "decided_at": a.decided_at, "created_at": a.created_at, "mine": a.applicant_id == user.id,
           "interviews": [interview(i, user) for i in a.interviews.all().order_by("scheduled_at")],
           "contract_id": getattr(getattr(a, "contract", None), "id", None)}
    if with_applicant:
        out["applicant"] = person(a.applicant)
        out["experience"] = experience_for(a.applicant)
    return out


def posting(p: EngagementPosting, user, *, detail: bool = False) -> dict:
    mine = bool(user and posting_side(p, user))
    out = {"id": p.id, "title": p.title, "category": {"id": p.category_id, "name": p.category.name}, "mission_type": p.mission_type, "work_relationship": p.work_relationship,
           "city": p.city, "start_date": p.start_date, "end_date": p.end_date, "schedule": p.schedule, "hours_per_week": money(p.hours_per_week), "amount": money(p.amount), "period": p.period, "currency": p.currency,
           "status": p.status, "application_deadline": p.application_deadline, "published_at": p.published_at, "created_at": p.created_at, "version": p.version,
           "publisher": person(p.publisher), "organization": ({"id": p.organization_id, "name": p.organization.name} if p.organization_id else None), "mine": mine,
           "applications_count": p.applications.exclude(status__in=("withdrawn",)).count() if mine else None}
    out.update({"benefits": p.benefits, "duration_months": p.duration_months})
    if detail:
        out.update({"description": p.description, "conditions": p.conditions, "employment_notice_ack": p.employment_notice_ack,
                    "location_note": p.location_note if mine else ""})
        if p.work_relationship == "employment":
            out["legal_notice"] = ("Un emploi salarié relève du droit du travail applicable. Tratra n'est pas un conseil juridique et ne calcule ni cotisations ni impôts : "
                                   "les parties restent responsables du respect de leurs obligations légales.")
    return out


# ── Contrat ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def amendment(a: ContractAmendment, user, contract: EngagementContract) -> dict:
    role = party_of(contract, user)
    proposer = party_of(contract, a.proposed_by)
    return {"id": a.id, "kind": a.kind, "changes": a.changes, "reason": a.reason, "effective_date": a.effective_date, "status": a.status, "proposed_by": person(a.proposed_by),
            "proposed_by_role": proposer, "mine": a.proposed_by_id == user.id, "can_respond": a.status == "proposed" and role is not None and role != proposer,
            "can_withdraw": a.status == "proposed" and a.proposed_by_id == user.id, "created_at": a.created_at, "responded_at": a.responded_at, "applied_at": a.applied_at}


def available_actions(c: EngagementContract, role: str, user) -> list:
    """Actions proposées par l'interface : calculées ici pour que React et Flutter appliquent exactement les mêmes règles."""
    out = []
    if c.status == "draft" and role == "principal":
        out += ["edit", "propose", "cancel"]
    if c.status == "pending_acceptance":
        accepted_roles = set(c.acceptances.filter(terms_version=c.terms_version).values_list("role", flat=True))
        if role not in accepted_roles:
            out += ["accept", "send_back", "decline"]
        elif role == "principal":
            out += ["cancel"]
    if c.signature_required and c.status == "accepted":
        signed = set(c.signatures.filter(document__version=c.terms_version, document__stage="for_signature").values_list("role", flat=True))
        out += ["decline"] + (["sign"] if role and role not in signed else [])
        return sorted(set(out))
    if c.status in ("accepted", "signed", "active", "suspended", "notice"):
        out += ["propose_amendment", "dispute"]
        if c.status in ("active", "suspended"):
            out += ["give_notice"]
        if c.status == "suspended" and not c.suspensions.filter(source="admin", ends_on__isnull=True).exists():
            out += ["resume"]
        if c.auto_renew and c.end_date and not c.non_renewal_at and c.status == "active":
            out += ["declare_non_renewal"]
        if c.status in ("active", "notice", "suspended"):
            out += ["request_event", "evaluate"]
        if role == "worker" and c.status in ("active", "notice"):
            out += ["propose_replacement"]
    if c.status in ("terminated", "completed"):
        out += ["evaluate", "dispute"]
        if not c.closed_at:
            out += ["close"]
    return sorted(set(out))


def contract(c: EngagementContract, user, *, detail: bool = False) -> dict:
    role = party_of(c, user)
    other = c.worker if role == "principal" else c.principal
    open_amendment = c.amendments.filter(status__in=("proposed", "accepted")).first()
    accepted_roles = set(c.acceptances.filter(terms_version=c.terms_version).values_list("role", flat=True))
    out = {"id": c.id, "title": c.title, "status": c.status, "my_role": role, "mission_type": c.mission_type, "work_relationship": c.work_relationship,
           "category": {"id": c.category_id, "name": c.category.name}, "start_date": c.start_date, "end_date": c.end_date, "ends_on": c.ends_on, "is_indefinite": c.is_indefinite,
           "amount": money(c.amount), "period": c.period, "currency": c.currency, "payment_day": c.payment_day, "hours_per_week": money(c.hours_per_week),
           "worker": person(c.worker), "principal": person(c.principal), "counterpart": person(other), "organization": ({"id": c.organization_id, "name": c.organization.name} if c.organization_id else None),
           "version": c.version, "terms_version": c.terms_version, "terms_hash": c.terms_hash, "accepted_by": sorted(accepted_roles), "actions": available_actions(c, role, user),
           "pending_amendment": amendment(open_amendment, user, c) if open_amendment else None, "created_at": c.created_at, "updated_at": c.updated_at,
           "activated_at": c.activated_at, "ended_at": c.ended_at, "closed_at": c.closed_at,
           "reference": c.reference, "signature_required": c.signature_required,
           "template": ({"id": c.template_id, "title": c.template.title, "version": c.template.version, "status": c.template.status,
                         "status_label": c.template.get_status_display()} if c.template_id else None)}
    if c.signature_required:
        signed = {s.role: s.signed_at for s in c.signatures.filter(document__version=c.terms_version, document__stage="for_signature")}
        out["signatures"] = {"principal": signed.get("principal"), "worker": signed.get("worker")}
    if detail:
        suspensions = [{"starts_on": s.starts_on, "ends_on": s.ends_on, "reason": s.reason, "source": s.source} for s in c.suspensions.all()]
        out.update({"description": c.description, "conditions": c.conditions, "benefits": c.benefits, "articles": c.articles,
                    "documents": [document(d) for d in c.documents.order_by("issued_at")],
                    "schedule": c.schedule, "location_city": c.location_city,
                    "location_address": c.location_address if c.status not in ("draft", "pending_acceptance") or role == "principal" else "",
                    "auto_renew": c.auto_renew, "renewal_term_months": c.renewal_term_months, "renewal_count": c.renewal_count, "non_renewal_at": c.non_renewal_at,
                    "non_renewal_deadline": (c.end_date - timedelta(days=c.notice_period_days)) if (c.auto_renew and c.end_date) else None,
                    "proration_mode": c.proration_mode, "overtime_hourly_rate": money(c.overtime_hourly_rate), "notice_period_days": c.notice_period_days,
                    "bookings_mode": c.bookings_mode, "legal_notice_ack": c.legal_notice_ack, "end_reason": c.end_reason, "notice_given_by": person(c.notice_given_by),
                    "notice_given_at": c.notice_given_at, "suspensions": suspensions, "service_id": c.service_id, "posting_id": c.posting_id,
                    "rules": rules(c.category_id),
                    # Avant la proposition : cohérence métier / missions (avertissement pour l'auteur, jamais un blocage).
                    "quality_warnings": coherence_warnings(c) if c.status in ("draft", "pending_acceptance") and role == "principal" else [],
                    "legal_notice": ("Emploi salarié : Tratra met en relation et garde la trace des accords, mais ne calcule ni cotisations, ni impôts, ni congés payés."
                                     if c.work_relationship == "employment" else
                                     "Prestation indépendante : aucune relation de travail salarié n'est créée par Tratra.")})
    return out


def document(d) -> dict:
    """Document scellé (sans le jeton de vérification, qui n'existe qu'imprimé dans le PDF)."""
    return {"id": d.id, "reference": d.reference, "kind": d.kind, "stage": d.stage, "version": d.version, "sha256": d.sha256, "size": d.size,
            "issued_at": d.issued_at, "signing_key": d.signing_key_id, "revoked_at": d.revoked_at, "revoked_reason": d.revoked_reason,
            "download": reverse("engagements-document-pdf", args=[d.id])}


def invitation(i, user) -> dict:
    return {"id": i.id, "status": i.status, "message": i.message, "created_at": i.created_at, "responded_at": i.responded_at,
            "posting": {"id": i.posting_id, "title": i.posting.title, "category": i.posting.category.name, "city": i.posting.city,
                        "amount": money(i.posting.amount), "period": i.posting.period, "work_relationship": i.posting.work_relationship},
            "invitee": person(i.invitee), "invited_by": person(i.invited_by), "application_id": i.application_id,
            "can_respond": i.status == "sent" and i.invitee_id == user.id}


def template(t, *, detail: bool = False) -> dict:
    out = {"id": t.id, "code": t.code, "version": t.version, "title": t.title, "relationship": t.relationship, "status": t.status,
           "status_label": t.get_status_display(), "categories": [{"id": c.id, "name": c.name} for c in t.categories.all()],
           "reviewed_at": t.reviewed_at, "reviewed_by": person(t.reviewed_by), "updated_at": t.updated_at, "contracts": t.contracts.count()}
    if detail:
        out.update({"articles": t.articles, "legal_references": t.legal_references, "review_note": t.review_note, "previous_id": t.previous_id})
    return out


def event(e: ContractEvent) -> dict:
    return {"id": e.id, "type": e.type, "actor": person(e.actor), "data": e.data, "at": e.created_at}


# ── Argent ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def line(l: InstallmentLine, user, contract_: EngagementContract) -> dict:
    proposer = party_of(contract_, l.proposed_by)
    role = party_of(contract_, user)
    return {"id": l.id, "kind": l.kind, "amount": money(l.amount), "description": l.description, "status": l.status, "proposed_by_role": proposer, "mine": l.proposed_by_id == user.id,
            "can_respond": l.status == "proposed" and role is not None and role != proposer, "evidence": evidence_ref("line", l), "created_at": l.created_at, "responded_at": l.responded_at}


def payment_trust(p: InstallmentPayment) -> dict:
    """Niveau de preuve d'un paiement entre les parties : « déclaré » (une partie l'affirme), « confirmé » (les deux parties
    concordent) ou « contesté ». JAMAIS « vérifié » ici : aucun encaissement ne transite par Tratra et aucun prestataire de
    paiement n'intervient dans un engagement — l'affirmer serait faux. (Un encaissement « vérifié » n'existe que pour les
    réservations réglées par un prestataire : voir handy/services/settlement.py.)"""
    if p.status == "confirmed":
        return {"level": "confirmed", "verified": False,
                "note": "Confirmé par les deux parties. Tratra ne vérifie pas ce paiement auprès d'un prestataire de paiement : il n'a pas transité par Tratra."}
    if p.status == "rejected":
        return {"level": "contested", "verified": False, "note": "Contesté : ce paiement n'est pas pris en compte."}
    return {"level": "declared", "verified": False, "note": "Déclaré par une partie : il n'est pris en compte qu'une fois confirmé par l'autre."}


def payment(p: InstallmentPayment, user, contract_: EngagementContract) -> dict:
    role = party_of(contract_, user)
    return {"trust": payment_trust(p), "id": p.id, "amount": money(p.amount), "method": p.method, "reference": p.reference, "paid_on": p.paid_on, "is_advance": p.is_advance, "status": p.status,
            "declared_by_role": p.declared_by_role, "mine": p.declared_by_id == user.id, "can_respond": p.status == "declared" and role is not None and role != p.declared_by_role,
            "rejection_reason": p.rejection_reason, "evidence": evidence_ref("payment", p), "declared_at": p.declared_at, "responded_at": p.responded_at}


def installment(i: ContractInstallment, user, *, detail: bool = False) -> dict:
    c = i.contract
    t = inst_svc.totals(i)
    out = {"id": i.id, "contract": c.id, "sequence": i.sequence, "number": i.sequence + 1, "period_start": i.period_start, "period_end": i.period_end, "due_date": i.due_date,
           "status": i.status, "currency": i.currency, "base_amount": money(i.base_amount), "computed": i.base_amount is not None, "adjustments": money(t["adjustments"]),
           "total": money(t["total"]), "confirmed": money(t["confirmed"]), "declared": money(t["declared"]), "balance": money(t["balance"]), "remaining_to_declare": money(t["remaining_to_declare"]),
           "platform_fee": money(i.platform_fee), "platform_fee_payer": i.platform_fee_payer, "platform_fee_status": i.platform_fee_status, "note": i.note, "closed_reason": i.closed_reason,
           "can_waive": party_of(c, user) == "worker" and i.status not in ("waived", "cancelled", "paid") and t["balance"] > 0}
    if detail:
        # Avant la fin de la période, un paiement est une AVANCE plafonnée par la règle de la catégorie : le client l'affiche avant l'envoi.
        advance_left = None
        if i.base_amount is not None and timezone.localdate() <= i.period_end:
            used = i.payments.exclude(status="rejected").filter(is_advance=True).aggregate(t=Sum("amount"))["t"] or 0
            cap = inst_svc.q(i.base_amount * rules_mod.rules_for(c.category_id).max_advance_percent / 100)
            advance_left = money(max(cap - used, 0))
        out["advance_remaining"] = advance_left
        out["lines"] = [line(l, user, c) for l in i.lines.select_related("proposed_by").order_by("created_at", "id")]
        out["payments"] = [payment(p, user, c) for p in i.payments.order_by("declared_at", "id")]
    return out


# ── Planning ────────────────────────────────────────────────────────────────────────────────────────────────────────

def schedule_event(e: ScheduleEvent, user, contract_: EngagementContract) -> dict:
    role = party_of(contract_, user)
    requester = party_of(contract_, e.requested_by) if e.requested_by_id else None
    return {"id": e.id, "kind": e.kind, "date": e.date, "end_date": e.end_date, "start_time": e.start_time, "end_time": e.end_time, "hours": money(e.hours), "status": e.status, "source": e.source,
            "note": e.note, "requested_by_role": requester, "mine": bool(e.requested_by_id and e.requested_by_id == user.id),
            "can_respond": e.status == "requested" and role is not None and role != requester and (e.kind != "replacement" or e.replacement_status == "accepted"),
            "can_cancel": e.status == "requested" and e.requested_by_id == user.id,
            "attendance_status": e.attendance_status, "actual_start": e.actual_start, "actual_end": e.actual_end,
            "can_declare_attendance": ((e.kind == "shift" and contract_.worker_id == user.id) or (e.kind == "replacement" and e.replacement_worker_id == user.id)) and e.status in ("planned", "approved")
            and e.attendance_status in ("none", "disputed") and e.date <= timezone.localdate(),
            "can_confirm_attendance": role == "principal" and e.attendance_status == "declared",
            "replaces": e.replaces_id, "replacement_worker": person(e.replacement_worker) if role else None, "replacement_status": e.replacement_status,
            "can_answer_replacement": e.kind == "replacement" and e.replacement_worker_id == user.id and e.replacement_status == "proposed" and e.status == "requested",
            "booking_id": e.booking_id}


# ── Évaluations et litiges ──────────────────────────────────────────────────────────────────────────────────────────

def evaluation(ev: EngagementEvaluation, user) -> dict:
    mine = ev.author_id == user.id
    return {"id": ev.id, "kind": ev.kind, "period_key": ev.period_key, "rating": ev.rating, "criteria": ev.criteria, "comment": ev.comment, "reply": ev.reply, "reply_at": ev.reply_at,
            "author": person(ev.author), "subject": person(ev.subject), "mine": mine, "about_me": ev.subject_id == user.id, "editable": mine and timezone.now() <= ev.edit_until and not ev.is_hidden,
            "can_reply": ev.subject_id == user.id and not ev.reply and not ev.is_hidden, "is_hidden": ev.is_hidden, "created_at": ev.created_at}


def dispute(d: EngagementDispute, user) -> dict:
    return {"id": d.id, "contract": d.contract_id, "installment": d.installment_id, "kind": d.kind, "reason": d.reason, "status": d.status, "resolution": d.resolution,
            "resolution_action": d.resolution_action, "mine": d.opened_by_id == user.id, "created_at": d.created_at, "resolved_at": d.resolved_at}
