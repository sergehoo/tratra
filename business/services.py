"""Règles métier de Tratra Business : demandes, validation hiérarchique, affectation intelligente, SLA, budgets,
préventif, facturation consolidée, KPI. Tout est calculé à partir des données réelles ; aucune valeur simulée."""
import hashlib
import secrets
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from django.contrib.gis.db.models.functions import Distance
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from business import rbac
from business.models import (ApprovalRule, ApprovalStep, Budget, ConsolidatedInvoice, Equipment, InterventionRequest,
                             Invitation, InvoiceLine, MaintenanceContract, Membership, Organization, PreventivePlan, Role,
                             Site)
from handy.eligibility import publishable
from handy.models import Booking, HandymanProfile, Notification, Payment, Service, TimeOff
from trust.models import audit

# SLA par défaut (heures : prise en charge, résolution) quand aucun contrat ne s'applique.
DEFAULT_SLA = {"urgent": (4, 24), "high": (24, 72), "normal": (48, 168), "low": (120, 336)}
INVITATION_TTL = timedelta(days=7)


class BusinessError(Exception):
    def __init__(self, code: str, detail: str, status: int = 400):
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status

    def payload(self) -> Dict:
        return {"code": self.code, "detail": self.detail}


# ---- Organisations et membres ---------------------------------------------------------------------------------

def create_organization(user, **fields) -> Organization:
    with transaction.atomic():
        org = Organization.objects.create(owner=user, **fields)
        Membership.objects.create(organization=org, user=user, role=Role.OWNER)
        audit("organization.created", actor=user, target=org, organization_id=org.id)
    return org


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def create_invitation(org: Organization, user, *, role: str, sites=(), label: str = "") -> Dict:
    if role == Role.OWNER:
        raise BusinessError("invalid_role", "Le rôle propriétaire ne s'attribue pas par invitation.")
    code = "-".join("".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(4)) for _ in range(3))
    with transaction.atomic():
        inv = Invitation.objects.create(organization=org, role=role, label=label, created_by=user,
                                        code_hash=_hash(code), expires_at=timezone.now() + INVITATION_TTL)
        inv.sites.set(sites)
        audit("member.invited", actor=user, target=org, organization_id=org.id, role=role, label=label)
    return {"id": inv.id, "code": code, "role": role, "expires_at": inv.expires_at}


def join_with_code(user, code: str) -> Membership:
    """L'invité (compte déjà connecté) saisit son code : adhésion créée, code consommé."""
    with transaction.atomic():
        inv = (Invitation.objects.select_for_update().select_related("organization")
               .filter(code_hash=_hash(code or "")).first())
        now = timezone.now()
        if (inv is None or inv.revoked_at or inv.accepted_at or inv.expires_at <= now
                or not inv.organization.is_active):
            raise BusinessError("invalid_invitation", "Code d'invitation invalide ou expiré.", 404)
        existing = Membership.objects.filter(organization=inv.organization, user=user).first()
        if existing and existing.is_active:
            raise BusinessError("already_member", "Vous faites déjà partie de cette organisation.", 409)
        if existing:
            existing.is_active, existing.role = True, inv.role
            existing.save()
            member = existing
        else:
            member = Membership.objects.create(organization=inv.organization, user=user, role=inv.role,
                                               invited_by=inv.created_by)
        member.sites.set(inv.sites.all())
        inv.accepted_by, inv.accepted_at = user, now
        inv.save(update_fields=["accepted_by", "accepted_at"])
        audit("member.joined", actor=user, target=inv.organization, organization_id=inv.organization_id, role=inv.role)
    return member


# ---- Contrats, SLA, règles de validation -------------------------------------------------------------------------

def applicable_contract(org, site, category, on_date=None) -> Optional[MaintenanceContract]:
    on_date = on_date or timezone.localdate()
    for contract in org.contracts.filter(status="active").prefetch_related("categories").order_by("-starts_on"):
        if not contract.covers(on_date):
            continue
        if contract.site_id and contract.site_id != site.id:
            continue
        cats = {c.id for c in contract.categories.all()}
        if cats and (category is None or category.id not in cats):
            continue
        return contract
    return None


def sla_hours(priority: str, contract: Optional[MaintenanceContract]):
    if contract:
        return contract.sla_response_hours, contract.sla_resolution_hours
    return DEFAULT_SLA.get(priority, DEFAULT_SLA["normal"])


def applicable_rule(org, site, priority: str, amount: Decimal) -> Optional[ApprovalRule]:
    for rule in org.approval_rules.filter(is_active=True):
        if rule.site_id and rule.site_id != site.id:
            continue
        if rule.priorities and priority not in rule.priorities:
            continue
        if amount < rule.min_amount or (rule.max_amount is not None and amount > rule.max_amount):
            continue
        return rule
    return None


def _next_number(org: Organization) -> str:
    year = timezone.now().year
    last = (InterventionRequest.objects.filter(organization=org, number__startswith=f"INT-{year}-")
            .order_by("-number").values_list("number", flat=True).first())
    seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"INT-{year}-{seq:04d}"


# ---- Demandes d'intervention ------------------------------------------------------------------------------------------

@transaction.atomic
def create_request(org: Organization, user, membership: Membership, *, site: Site, title: str, description: str = "",
                   category=None, equipment: Optional[Equipment] = None, priority: str = "normal", desired_date=None,
                   estimated_cost=None, source: str = "manual", preventive_plan=None) -> InterventionRequest:
    if not rbac.site_allowed(membership, site.id):
        raise BusinessError("site_forbidden", "Ce site ne fait pas partie de votre périmètre.", 403)
    Organization.objects.select_for_update().get(pk=org.pk)  # numérotation sans doublon
    now = timezone.now()
    category = category or (equipment.category if equipment else None)
    contract = applicable_contract(org, site, category)
    response_h, resolution_h = sla_hours(priority, contract)
    amount = Decimal(estimated_cost or 0)
    rule = applicable_rule(org, site, priority, amount)
    steps = list(rule.steps) if rule else []
    req = InterventionRequest.objects.create(
        organization=org, number=_next_number(org), site=site, equipment=equipment, requested_by=user, title=title,
        description=description, category=category, priority=priority, source=source, desired_date=desired_date,
        estimated_cost=estimated_cost, contract=contract, preventive_plan=preventive_plan,
        status="pending_approval" if steps else "approved",
        due_response_at=now + timedelta(hours=response_h), due_resolution_at=now + timedelta(hours=resolution_h))
    for i, role in enumerate(steps, 1):
        ApprovalStep.objects.create(request=req, order=i, role=role)
    audit("request.created", actor=user, target=req, target_type="interventionrequest", organization_id=org.id,
          number=req.number, source=source, steps=steps)
    if steps:
        _notify_approvers(req, steps[0])
    return req


def _notify_approvers(req: InterventionRequest, role: str) -> None:
    members = (Membership.objects.filter(organization=req.organization, is_active=True)
               .filter(Q(role=role) | Q(role__in=[Role.OWNER, Role.ADMIN])).exclude(user=req.requested_by)
               .select_related("user"))
    for m in members:
        if rbac.site_allowed(m, req.site_id):
            Notification.objects.create(user=m.user, notification_type="business_request",
                                        message=f"Demande {req.number} à valider : {req.title} ({req.site.name}).")


def pending_step(req: InterventionRequest) -> Optional[ApprovalStep]:
    return req.steps.filter(status="pending").order_by("order").first()


def can_decide(membership: Membership, req: InterventionRequest) -> bool:
    step = pending_step(req)
    if step is None or req.status != "pending_approval":
        return False
    if membership.user_id == req.requested_by_id or not rbac.can(membership, "requests.approve"):
        return False  # séparation des tâches : on ne valide jamais sa propre demande
    if not rbac.site_allowed(membership, req.site_id):
        return False
    return membership.role == step.role or membership.role in (Role.OWNER, Role.ADMIN)


@transaction.atomic
def decide(req: InterventionRequest, user, membership: Membership, *, approve: bool, comment: str = "") -> InterventionRequest:
    req = InterventionRequest.objects.select_for_update().get(pk=req.pk)
    step = pending_step(req)
    if req.status != "pending_approval" or step is None:
        raise BusinessError("not_pending", "Cette demande n'attend plus de validation.", 409)
    if not can_decide(membership, req):
        raise BusinessError("forbidden", "Vous ne pouvez pas valider cette étape.", 403)
    step.status = "approved" if approve else "rejected"
    step.decided_by, step.decided_at, step.comment = user, timezone.now(), comment
    step.save()
    if not approve:
        req.status, req.rejection_reason = "rejected", comment
    elif pending_step(req) is None:
        req.status = "approved"
    req.save()
    audit("request.approved" if approve else "request.rejected", actor=user, target=req,
          target_type="interventionrequest", organization_id=req.organization_id, step=step.order, role=step.role,
          override=membership.role != step.role)
    if not approve or req.status == "approved":
        Notification.objects.create(
            user=req.requested_by, notification_type="business_update",
            message=(f"Votre demande {req.number} a été validée." if approve
                     else f"Votre demande {req.number} a été refusée. {comment}".strip()))
    elif (nxt := pending_step(req)) is not None:
        _notify_approvers(req, nxt.role)
    return req


def cancel_request(req: InterventionRequest, user) -> InterventionRequest:
    if req.status not in ("pending_approval", "approved", "dispatched", "scheduled"):
        raise BusinessError("not_cancellable", "Cette demande ne peut plus être annulée.", 409)
    with transaction.atomic():
        if req.booking_id and req.booking.status in ("pending", "confirmed"):
            req.booking.transition_to("cancelled", actor=user)
        req.status = "cancelled"
        req.save()
        audit("request.cancelled", actor=user, target=req, target_type="interventionrequest",
              organization_id=req.organization_id)
    return req


# ---- Affectation intelligente ---------------------------------------------------------------------------------------

def suggest_artisans(req: InterventionRequest, limit: int = 5) -> List[Dict]:
    """Artisans ÉLIGIBLES (KYC approuvé, profil complet, compte actif — règle unique de la plateforme), classés selon : contrat
    (prestataire attitré), compétence, proximité du site, confiance, note, disponibilité. Chaque suggestion explique son rang."""
    now = timezone.now()
    qs = publishable().select_related("user").prefetch_related("skills")
    qs = qs.exclude(user_id=req.requested_by_id)  # un demandeur ne s'affecte pas sa propre mission
    qs = qs.exclude(Exists(TimeOff.objects.filter(handyman_id=OuterRef("pk"), start__lte=now, end__gte=now)))
    if req.category_id:
        has_service = Service.objects.filter(handyman_id=OuterRef("user_id"), is_active=True, category_id=req.category_id)
        qs = qs.filter(Q(skills__id=req.category_id) | Exists(has_service)).distinct()
    if req.site.location:
        qs = qs.annotate(distance=Distance("location", req.site.location))
    contract_provider = req.contract.provider_id if req.contract_id else None
    rows = []
    for p in qs[:200]:
        score, reasons = 0.0, []
        if contract_provider and p.user_id == contract_provider:
            score += 1000
            reasons.append(f"Prestataire du contrat « {req.contract.name} »")
        if p.trust_score is not None:
            score += p.trust_score * 0.5
            reasons.append(f"Score de confiance {p.trust_score}/100")
        if p.rating:
            score += float(p.rating) * 4
            reasons.append(f"Note {str(round(float(p.rating), 1)).replace('.', ',')}/5")
        for code, label, pts in (("EXPERT", "Badge Expert", 10), ("SUR", "Badge Sûr", 10)):
            if code in (p.trust_badges or []):
                score += pts
                reasons.append(label)
        if p.online:
            score += 15
            reasons.append("En ligne")
        distance_km = None
        dist = getattr(p, "distance", None)
        if dist is not None:
            distance_km = round(dist.m / 1000, 1)
            score += max(0.0, 30 - distance_km)
            reasons.append(f"À {str(distance_km).replace('.', ',')} km du site")
        score += min(p.completed_jobs or 0, 50) / 5
        svc = Service.objects.filter(handyman_id=p.user_id, is_active=True,
                                     **({"category_id": req.category_id} if req.category_id else {})).first()
        rows.append({"user_id": p.user_id, "profile_id": p.id, "display_name": _public_name(p.user), "score": round(score, 1),
                     "distance_km": distance_km, "rating": float(p.rating or 0), "trust_score": p.trust_score,
                     "badges": p.trust_badges or [], "online": p.online, "service_id": svc.id if svc else None,
                     "reasons": reasons})
    rows.sort(key=lambda r: (-r["score"], r["user_id"]))
    return rows[:limit]


def _public_name(user) -> str:
    first, last = (user.first_name or "").strip(), (user.last_name or "").strip()
    return f"{first} {last[:1]}." if first and last else (first or "Artisan")


@transaction.atomic
def dispatch(req: InterventionRequest, user, *, artisan_id: Optional[int] = None, auto: bool = False,
             when: Optional[datetime] = None) -> InterventionRequest:
    """Crée la RÉSERVATION de l'artisan choisi (statut « en attente » : il l'accepte comme toute mission). Seuls les artisans
    éligibles sont proposables ; rien n'est payé ni activé ici."""
    req = (InterventionRequest.objects.select_for_update(of=("self",))
           .select_related("site", "organization", "contract").get(pk=req.pk))
    if req.status != "approved" or req.booking_id:
        raise BusinessError("not_dispatchable", "Seule une demande validée et non affectée peut être envoyée à un artisan.", 409)
    candidates = suggest_artisans(req, limit=50)
    if not candidates:
        raise BusinessError("no_candidate", "Aucun artisan éligible n'est disponible pour cette demande.", 409)
    if artisan_id is not None:
        chosen = next((c for c in candidates if c["user_id"] == artisan_id), None)
        if chosen is None:
            raise BusinessError("not_eligible", "Cet artisan n'est pas éligible pour cette demande.", 400)
    elif auto:
        chosen = candidates[0]
    else:
        raise BusinessError("artisan_required", "Choisissez un artisan ou demandez l'affectation automatique.")
    site = req.site
    start = when or req.desired_date or (timezone.now() + timedelta(hours=2))
    booking = Booking.objects.create(
        client=req.requested_by, handyman_id=chosen["user_id"], service_id=chosen["service_id"], status="pending",
        booking_date=start, address=site.address or site.name, city=site.city or "—", postal_code=site.postal_code or "",
        description=f"[{req.organization.name} · {req.number}] {req.title}\n{req.description}".strip(),
        job_location=site.location, proposed_price=req.estimated_cost)
    req.booking, req.status = booking, "dispatched"
    req.save()
    Notification.objects.create(user_id=chosen["user_id"], notification_type="booking_request",
                                message=f"Nouvelle demande d'intervention {req.number} : {req.title}.")
    audit("request.dispatched", actor=user, target=req, target_type="interventionrequest",
          organization_id=req.organization_id, artisan_id=chosen["user_id"], booking_id=booking.id, auto=auto)
    return req


# ---- Coûts, réservation → demande ---------------------------------------------------------------------------------------

def booking_cost(booking: Booking) -> Optional[Decimal]:
    """Coût RÉEL d'une intervention : paiement encaissé, sinon montant convenu sur la réservation ; None si inconnu."""
    payment = getattr(booking, "payment", None)
    if payment is not None and payment.status in Payment.PAID_STATUSES and payment.amount:
        return Decimal(payment.amount)
    for value in (booking.total_price, booking.proposed_price):
        if value:
            return Decimal(value)
    return None


def request_cost(req: InterventionRequest) -> Optional[Decimal]:
    if req.final_cost is not None:
        return req.final_cost
    return booking_cost(req.booking) if req.booking_id else None


def sync_from_booking(booking: Booking) -> None:
    """La réservation liée change de statut : la demande suit (planifiée, en cours, terminée, annulée)."""
    req = InterventionRequest.objects.select_related("organization", "preventive_plan").filter(booking=booking).first()
    if req is None:
        return
    now = timezone.now()
    if booking.status == "confirmed" and req.status == "dispatched":
        req.status, req.responded_at = "scheduled", now
    elif booking.status == "in_progress" and req.status in ("dispatched", "scheduled"):
        req.status, req.responded_at = "in_progress", req.responded_at or now
    elif booking.status == "completed" and req.status != "completed":
        req.status, req.completed_at, req.responded_at = "completed", now, req.responded_at or now
        req.final_cost = booking_cost(booking)
        plan = req.preventive_plan
        if plan:
            today = timezone.localdate()
            plan.last_done_on, plan.next_due_on = today, today + timedelta(days=plan.frequency_days)
            plan.save(update_fields=["last_done_on", "next_due_on"])
    elif booking.status == "cancelled" and req.status in ("dispatched", "scheduled", "in_progress"):
        # l'artisan se désiste ou la mission est annulée : la demande redevient affectable
        req.status, req.booking, req.responded_at = "approved", None, None
        for m in Membership.objects.filter(organization=req.organization, is_active=True, role__in=[Role.OWNER, Role.ADMIN, Role.SITE_MANAGER]):
            if rbac.site_allowed(m, req.site_id):
                Notification.objects.create(user=m.user, notification_type="business_update",
                                            message=f"L'intervention {req.number} est à réaffecter (mission annulée).")
    else:
        return
    req.save()
    audit("request.synced", target=req, target_type="interventionrequest", organization_id=req.organization_id,
          booking_status=booking.status, status=req.status)


# ---- Budgets ---------------------------------------------------------------------------------------------------------------

def scoped_requests(org: Organization, membership: Optional[Membership] = None):
    qs = InterventionRequest.objects.filter(organization=org)
    if membership is not None:
        scope = rbac.scoped_site_ids(membership)
        if scope is not None:
            qs = qs.filter(site_id__in=scope)
        if not rbac.can(membership, "requests.view_all"):
            qs = qs.filter(requested_by=membership.user)
    return qs


def budget_status(budget: Budget) -> Dict:
    qs = InterventionRequest.objects.filter(organization=budget.organization, status="completed",
                                            completed_at__date__gte=budget.period_start, completed_at__date__lte=budget.period_end)
    committed_qs = InterventionRequest.objects.filter(organization=budget.organization, status__in=InterventionRequest.OPEN,
                                                      created_at__date__gte=budget.period_start,
                                                      created_at__date__lte=budget.period_end)
    if budget.site_id:
        qs, committed_qs = qs.filter(site_id=budget.site_id), committed_qs.filter(site_id=budget.site_id)
    if budget.equipment_id:
        qs, committed_qs = qs.filter(equipment_id=budget.equipment_id), committed_qs.filter(equipment_id=budget.equipment_id)
    spent = sum((request_cost(r) or Decimal("0") for r in qs.select_related("booking")), Decimal("0"))
    committed = sum((r.estimated_cost or Decimal("0") for r in committed_qs), Decimal("0"))
    pct = float(spent / budget.amount * 100) if budget.amount else 0.0
    level = "exceeded" if pct >= 100 else ("warning" if pct >= budget.alert_threshold_pct else "ok")
    return {"spent": spent, "committed": committed, "remaining": budget.amount - spent, "percent": round(pct, 1), "level": level}


def budget_warnings(req: InterventionRequest) -> List[Dict]:
    """Budgets dépassés (ou qui le seraient) si cette demande est réalisée à son coût estimé."""
    out = []
    today = timezone.localdate()
    for b in req.organization.budgets.filter(period_start__lte=today, period_end__gte=today):
        if (b.site_id and b.site_id != req.site_id) or (b.equipment_id and b.equipment_id != req.equipment_id):
            continue
        st = budget_status(b)
        projected = st["spent"] + (req.estimated_cost or Decimal("0"))
        if b.amount and projected > b.amount:
            out.append({"budget_id": b.id, "name": b.name, "amount": b.amount, "projected": projected})
    return out


# ---- Facturation consolidée ----------------------------------------------------------------------------------------------

@transaction.atomic
def generate_invoice(org: Organization, user, start: date, end: date) -> ConsolidatedInvoice:
    if end < start:
        raise BusinessError("invalid_period", "La fin de période précède son début.")
    Organization.objects.select_for_update().get(pk=org.pk)
    candidates = (InterventionRequest.objects.filter(organization=org, status="completed", invoice_line__isnull=True,
                                                     completed_at__date__gte=start, completed_at__date__lte=end)
                  .select_related("site", "booking"))
    lines, skipped = [], 0
    for r in candidates:
        cost = request_cost(r)
        if cost is None:
            skipped += 1  # à chiffrer : jamais facturé à zéro ni deviné
            continue
        lines.append((r, cost))
    if not lines:
        raise BusinessError("nothing_to_invoice", "Aucune intervention terminée et chiffrée à facturer sur cette période."
                            + (f" ({skipped} sans montant)" if skipped else ""), 409)
    seq = ConsolidatedInvoice.objects.filter(organization=org, number__startswith=f"FAC-{end:%Y%m}-").count() + 1
    invoice = ConsolidatedInvoice.objects.create(organization=org, number=f"FAC-{end:%Y%m}-{seq:03d}", period_start=start,
                                                 period_end=end, total=sum(c for _, c in lines), created_by=user)
    for r, cost in lines:
        InvoiceLine.objects.create(invoice=invoice, request=r, site_name=r.site.name, amount=cost,
                                   description=f"{r.number} — {r.title}"[:255])
    audit("invoice.issued", actor=user, target=invoice, target_type="consolidatedinvoice", organization_id=org.id,
          number=invoice.number, total=str(invoice.total), lines=len(lines), skipped=skipped)
    invoice.skipped = skipped
    return invoice


# ---- Préventif --------------------------------------------------------------------------------------------------------------

def run_preventive(today: Optional[date] = None) -> int:
    """Transforme les maintenances échues (échéance − délai de rappel) en demandes d'intervention, une fois par échéance, et
    prévient les gestionnaires. Idempotent."""
    today = today or timezone.localdate()
    created = 0
    plans = (PreventivePlan.objects.filter(is_active=True, equipment__organization__is_active=True)
             .exclude(equipment__status="retired").select_related("equipment", "equipment__site", "organization"))
    for plan in plans:
        if plan.next_due_on - timedelta(days=plan.lead_days) > today or plan.last_generated_for == plan.next_due_on:
            continue
        org, eq = plan.organization, plan.equipment
        with transaction.atomic():
            fresh = PreventivePlan.objects.select_for_update().get(pk=plan.pk)
            if fresh.last_generated_for == fresh.next_due_on:
                continue
            owner_m = Membership.objects.filter(organization=org, user=org.owner, is_active=True).first()
            if owner_m is None:
                continue
            due_dt = timezone.make_aware(datetime.combine(fresh.next_due_on, time(9, 0)))
            req = create_request(org, org.owner, owner_m, site=eq.site, equipment=eq, title=f"Maintenance préventive — {fresh.title}",
                                 description=f"Échéance du {fresh.next_due_on:%d/%m/%Y} (tous les {fresh.frequency_days} jours).",
                                 category=fresh.category or eq.category, desired_date=due_dt, source="preventive", preventive_plan=fresh)
            fresh.last_generated_for = fresh.next_due_on
            fresh.save(update_fields=["last_generated_for"])
            for m in Membership.objects.filter(organization=org, is_active=True, role__in=[Role.OWNER, Role.ADMIN, Role.SITE_MANAGER]):
                if rbac.site_allowed(m, eq.site_id):
                    Notification.objects.create(user=m.user, notification_type="business_reminder",
                                                message=f"Maintenance préventive à prévoir : {eq.name} ({eq.site.name}) — {fresh.next_due_on:%d/%m/%Y}. Demande {req.number} créée.")
            created += 1
    return created


# ---- Tableau de bord / KPI ---------------------------------------------------------------------------------------------------

def dashboard(org: Organization, membership: Membership, start: date, end: date) -> Dict:
    now = timezone.now()
    base = scoped_requests(org, membership)
    in_period = base.filter(created_at__date__gte=start, created_at__date__lte=end)
    completed = base.filter(status="completed", completed_at__date__gte=start, completed_at__date__lte=end).select_related("site", "category", "booking")
    by_status = {s: 0 for s, _ in InterventionRequest.STATUSES}
    for row in base.values("status").annotate(n=Count("id")):
        by_status[row["status"]] = row["n"]
    open_qs = base.filter(status__in=InterventionRequest.OPEN)
    overdue = open_qs.filter(due_resolution_at__lt=now).count()

    def rate(items, attr):
        flags = [getattr(r, attr) for r in items]
        flags = [f for f in flags if f is not None]
        return {"met": sum(1 for f in flags if f), "measured": len(flags),
                "rate": round(sum(1 for f in flags if f) / len(flags), 3) if flags else None}

    items = list(completed)
    hours = [(r.completed_at - r.created_at).total_seconds() / 3600 for r in items]
    response_hours = [(r.responded_at - r.created_at).total_seconds() / 3600 for r in items if r.responded_at]
    spend_total, by_site, by_category, by_month = Decimal("0"), defaultdict(Decimal), defaultdict(Decimal), defaultdict(Decimal)
    unpriced = 0
    for r in items:
        cost = request_cost(r)
        if cost is None:
            unpriced += 1
            continue
        spend_total += cost
        by_site[r.site.name] += cost
        by_category[r.category.name if r.category else "Non précisé"] += cost
        by_month[f"{r.completed_at:%Y-%m}"] += cost
    top_equipment = (in_period.exclude(equipment__isnull=True).values("equipment__name", "equipment_id")
                     .annotate(n=Count("id")).order_by("-n")[:5])
    today = timezone.localdate()
    plans = PreventivePlan.objects.filter(organization=org, is_active=True)
    pending_for_me = [r for r in open_qs.filter(status="pending_approval").select_related("site") if can_decide(membership, r)]
    budgets = [{"id": b.id, "name": b.name, "amount": b.amount, **budget_status(b)}
               for b in org.budgets.filter(period_end__gte=today, period_start__lte=today)] if rbac.can(membership, "budgets.manage") or rbac.can(membership, "reports.view") else []
    return {
        "period": {"start": start, "end": end},
        "requests": {"created": in_period.count(), "completed": len(items), "open": open_qs.count(), "overdue": overdue,
                     "by_status": by_status},
        "pending_my_approval": len(pending_for_me),
        "sla": {"response": rate(items, "sla_response_met"), "resolution": rate(items, "sla_resolution_met")},
        "durations": {"avg_resolution_hours": round(sum(hours) / len(hours), 1) if hours else None,
                      "avg_response_hours": round(sum(response_hours) / len(response_hours), 1) if response_hours else None},
        "spend": {"total": spend_total, "currency": org.currency, "unpriced_interventions": unpriced,
                  "by_site": [{"name": k, "amount": v} for k, v in sorted(by_site.items(), key=lambda kv: -kv[1])],
                  "by_category": [{"name": k, "amount": v} for k, v in sorted(by_category.items(), key=lambda kv: -kv[1])],
                  "by_month": [{"month": k, "amount": v} for k, v in sorted(by_month.items())]},
        "top_equipment": [{"id": r["equipment_id"], "name": r["equipment__name"], "interventions": r["n"]} for r in top_equipment],
        "preventive": {"active_plans": plans.count(), "overdue": plans.filter(next_due_on__lt=today).count(),
                       "due_30_days": plans.filter(next_due_on__gte=today, next_due_on__lte=today + timedelta(days=30)).count()},
        "budgets": budgets,
    }
