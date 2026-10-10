"""Modules « argent et relation » du Back-Office : Tratra Business (supervision), Finances, Support.

 - jamais de « marquer payé » : un paiement ne se crée ni ne se valide à la main ; on rembourse via l'escrow existant ;
 - un retrait ne passe à « envoyé » qu'avec la RÉFÉRENCE du virement effectué ; un rejet libère automatiquement les gains ;
 - Business : supervision en lecture, jamais de contournement du circuit de validation des demandes ;
 - aucun identifiant de transaction fournisseur dans les listes ; aucun secret ; contacts masqués."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.response import Response

from backoffice import rbac
from backoffice.common import BOView, apply_range, audit_op, bad_request, mask_phone, money as _money, ordering, paginate, public_name
from backoffice.models import SupportNote
from business import services as business_services
from business.models import (
    Budget, ConsolidatedInvoice, Equipment, InterventionRequest, MaintenanceContract, Membership, Organization, Role, Site,
)
from handy.models import (
    Booking, Dispute, Invoice, Notification, Payment, PaymentLog, Payout, Report, User, artisan_available_earnings,
)
from handy.notifications import notify
from trust.models import AuditEvent

MIN_REASON = 5


def _reason(request, key: str = "reason", minimum: int = MIN_REASON) -> str:
    value = str(request.data.get(key) or "").strip()
    if len(value) < minimum:
        raise ValidationError(f"Un champ « {key} » d'au moins {minimum} caractères est obligatoire.", code=f"{key}_required")
    return value[:500]


def _invalid(exc: ValidationError):
    conflict = exc.code in ("not_pending", "invalid_transition", "already")
    return bad_request(exc.code or "invalid", exc.messages[0], 409 if conflict else 400)


def _history(target_type: str, target_id: int, limit: int = 15):
    rows = AuditEvent.objects.filter(target_type=target_type, target_id=target_id).select_related("actor")[:limit]
    return [{"action": e.action, "at": e.created_at, "by": public_name(e.actor) if e.actor_id else "Système",
             "reason": (e.data or {}).get("reason", "")} for e in rows]


# ═══ Tratra Business (supervision) ══════════════════════════════════════════════════════════════════════════════════

def _org_row(o: Organization) -> dict:
    return {"id": o.pk, "name": o.name, "city": o.city or None, "industry": o.industry or None, "owner": public_name(o.owner), "is_active": o.is_active,
            "members": getattr(o, "n_members", 0), "sites": getattr(o, "n_sites", 0), "open_requests": getattr(o, "n_open", 0), "created_at": o.created_at}


class OrganizationList(BOView):
    bo_permission = "business.manage"

    def get(self, request):
        p = request.query_params
        qs = Organization.objects.select_related("owner").annotate(
            n_members=Count("memberships", filter=Q(memberships__is_active=True), distinct=True), n_sites=Count("sites", distinct=True),
            n_open=Count("requests", filter=Q(requests__status__in=InterventionRequest.OPEN), distinct=True))
        q = (p.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(legal_name__icontains=q) | Q(city__icontains=q) | Q(registration_number__icontains=q))
        if p.get("active") in ("true", "false"):
            qs = qs.filter(is_active=p["active"] == "true")
        qs = qs.order_by(ordering(request, {"created_at": "created_at", "name": "name", "open": "n_open"}, "-created_at"), "-id")
        return paginate(request, qs, _org_row)


class OrganizationDetail(BOView):
    bo_permission = "business.manage"

    def get(self, request, pk):
        o = Organization.objects.select_related("owner").annotate(
            n_members=Count("memberships", filter=Q(memberships__is_active=True), distinct=True), n_sites=Count("sites", distinct=True),
            n_open=Count("requests", filter=Q(requests__status__in=InterventionRequest.OPEN), distinct=True)).filter(pk=pk).first()
        if o is None:
            return bad_request("not_found", "Organisation introuvable.", 404)
        today = timezone.localdate()
        by_status = dict(o.requests.values_list("status").annotate(n=Count("id")))
        late = o.requests.filter(status__in=InterventionRequest.OPEN, due_response_at__lt=timezone.now(), responded_at__isnull=True).count()
        row = _org_row(o)
        row.update({
            "legal_name": o.legal_name, "registration_number": o.registration_number, "currency": o.currency, "address": o.address,
            "members_list": [{"id": m.pk, "name": public_name(m.user), "role": m.role, "role_label": Role.LABELS.get(m.role, m.role), "is_active": m.is_active,
                              "phone": mask_phone(m.user.phone)} for m in o.memberships.select_related("user").order_by("role", "id")],
            # Sites : nom et ville seulement (aucune coordonnée).
            "sites_list": [{"id": s.pk, "name": s.name, "city": s.city or None, "is_active": s.is_active} for s in o.sites.all()],
            "equipment": o.equipment.exclude(status="retired").count(),
            "contracts": {"active": MaintenanceContract.objects.filter(organization=o, status="active").count(), "total": o.contracts.count()},
            "requests": {"by_status": by_status, "late_response": late},
            "budgets": [{"id": b.pk, "name": b.name, "amount": _money(b.amount), "period_start": b.period_start, "period_end": b.period_end,
                         **{k: (_money(v) if isinstance(v, Decimal) else v) for k, v in business_services.budget_status(b).items()}}
                        for b in o.budgets.filter(period_end__gte=today - timedelta(days=60))[:10]],
            "invoices": [{"id": i.pk, "number": i.number, "period_start": i.period_start, "period_end": i.period_end, "total": _money(i.total), "status": i.status}
                         for i in o.invoices.all()[:10]],
            "history": _history("organization", o.pk),
        })
        return Response(row)


class OrganizationActivation(BOView):
    """Suspendre / réactiver une organisation : ses membres perdent l'accès Business (règle existante), rien n'est supprimé."""
    bo_permission = "business.manage"
    suspend = True

    def post(self, request, pk):
        o = Organization.objects.filter(pk=pk).first()
        if o is None:
            return bad_request("not_found", "Organisation introuvable.", 404)
        try:
            reason = _reason(request)
            if o.is_active != self.suspend:
                raise ValidationError("L'organisation est déjà dans cet état.", code="already")
        except ValidationError as exc:
            return _invalid(exc)
        o.is_active = not self.suspend
        o.save(update_fields=["is_active"])
        audit_op(request, "organization.suspended" if self.suspend else "organization.reactivated", o, reason=reason, organization_id=o.pk)
        return Response(_org_row(o))


class OrganizationSuspend(OrganizationActivation):
    suspend = True


class OrganizationReactivate(OrganizationActivation):
    suspend = False


def _request_row(r: InterventionRequest) -> dict:
    now = timezone.now()
    overdue = bool(r.status in InterventionRequest.OPEN and r.due_resolution_at and r.due_resolution_at < now)
    return {"id": r.pk, "number": r.number, "organization": r.organization.name, "organization_id": r.organization_id, "site": r.site.name, "title": r.title,
            "priority": r.priority, "status": r.status, "status_label": dict(InterventionRequest.STATUSES).get(r.status, r.status),
            "requested_by": public_name(r.requested_by), "created_at": r.created_at, "due_response_at": r.due_response_at,
            "due_resolution_at": r.due_resolution_at, "overdue": overdue, "booking_id": r.booking_id}


class BusinessRequestList(BOView):
    """Supervision des demandes d'intervention (lecture) : aucune action ici ne contourne le circuit de validation."""
    bo_permission = "business.manage"

    def get(self, request):
        p = request.query_params
        qs = InterventionRequest.objects.select_related("organization", "site", "requested_by")
        if p.get("status") in dict(InterventionRequest.STATUSES):
            qs = qs.filter(status=p["status"])
        if p.get("priority") in dict(InterventionRequest.PRIORITIES):
            qs = qs.filter(priority=p["priority"])
        if p.get("overdue") == "true":
            qs = qs.filter(status__in=InterventionRequest.OPEN, due_resolution_at__lt=timezone.now())
        if (p.get("organization") or "").isdigit():
            qs = qs.filter(organization_id=int(p["organization"]))
        q = (p.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(number__icontains=q) | Q(organization__name__icontains=q))
        return paginate(request, apply_range(request, qs, "created_at").order_by("-created_at", "-id"), _request_row)


class BusinessInvoiceList(BOView):
    bo_permission = "business.manage"

    def get(self, request):
        qs = ConsolidatedInvoice.objects.select_related("organization")
        if (request.query_params.get("organization") or "").isdigit():
            qs = qs.filter(organization_id=int(request.query_params["organization"]))
        return paginate(request, qs.order_by("-created_at", "-id"), lambda i: {
            "id": i.pk, "number": i.number, "organization": i.organization.name, "organization_id": i.organization_id,
            "period_start": i.period_start, "period_end": i.period_end, "total": _money(i.total), "status": i.status, "lines": i.lines.count(), "created_at": i.created_at})


# ═══ Finances ═══════════════════════════════════════════════════════════════════════════════════════════════════════

def _net(p: Payment) -> str:
    return _money(p.amount - (p.platform_fee or Decimal("0")))


def _payment_row(p: Payment) -> dict:
    b = p.booking
    return {"id": p.pk, "booking_id": p.booking_id, "client": public_name(b.client), "artisan": public_name(b.handyman), "amount": _money(p.amount),
            "platform_fee": _money(p.platform_fee), "net": _net(p), "method": p.method, "status": p.status, "refunded_amount": _money(p.refunded_amount),
            "currency": p.currency, "created_at": p.created_at, "payment_date": p.payment_date}


class FinanceSummary(BOView):
    bo_permission = "finance.view"

    def get(self, request):
        qs = apply_range(request, Payment.objects.all(), "created_at")
        by_status = {r["status"]: {"count": r["n"], "amount": _money(r["total"])} for r in qs.values("status").annotate(n=Count("id"), total=Sum("amount"))}
        paid = qs.filter(status__in=Payment.PAID_STATUSES).aggregate(gmv=Sum("amount"), fee=Sum("platform_fee"))
        released = qs.filter(status__in=("released", "completed")).aggregate(fee=Sum("platform_fee"))
        payouts = {r["status"]: {"count": r["n"], "amount": _money(r["total"])} for r in Payout.objects.values("status").annotate(n=Count("id"), total=Sum("amount"))}
        return Response({
            "currency": "XOF", "by_status": by_status, "gmv": _money(paid["gmv"]), "commission_earned": _money(released["fee"]),
            "commission_in_escrow": _money((paid["fee"] or Decimal("0")) - (released["fee"] or Decimal("0"))),
            "escrow_held": _money(Payment.objects.filter(status="held").aggregate(t=Sum("amount"))["t"]),
            "refunded": _money(qs.aggregate(t=Sum("refunded_amount"))["t"]), "payouts": payouts,
        })


class PaymentList(BOView):
    bo_permission = "finance.view"

    def get(self, request):
        p = request.query_params
        qs = Payment.objects.select_related("booking", "booking__client", "booking__handyman")
        if p.get("status") in dict(Payment.PAYMENT_STATUS):
            qs = qs.filter(status=p["status"])
        if p.get("method") in dict(Payment.PAYMENT_METHODS):
            qs = qs.filter(method=p["method"])
        q = (p.get("q") or "").strip()
        if q.isdigit():
            qs = qs.filter(Q(pk=int(q)) | Q(booking_id=int(q)))
        qs = apply_range(request, qs, "created_at").order_by(ordering(request, {"created_at": "created_at", "amount": "amount"}, "-created_at"), "-id")
        return paginate(request, qs, _payment_row)


class PaymentDetail(BOView):
    bo_permission = "finance.view"

    def get(self, request, pk):
        p = Payment.objects.select_related("booking", "booking__client", "booking__handyman").filter(pk=pk).first()
        if p is None:
            return bad_request("not_found", "Paiement introuvable.", 404)
        row = _payment_row(p)
        row.update({"booking_status": p.booking.status, "discount": _money(p.discount),
                    "logs": [{"previous_status": l.previous_status, "new_status": l.new_status, "at": l.changed_at, "notes": l.notes or ""} for l in p.logs.order_by("changed_at", "id")],
                    "can_refund": "finance.manage" in rbac.user_permissions(request.user) and "refunded" in Payment.ESCROW_TRANSITIONS.get(p.status, set()),
                    "history": _history("payment", p.pk)})
        return Response(row)


class PaymentRefund(BOView):
    """Remboursement via l'escrow existant (jamais de création ni de validation manuelle d'un paiement)."""
    bo_permission = "finance.manage"

    @transaction.atomic
    def post(self, request, pk):
        p = Payment.objects.select_for_update().filter(pk=pk).first()
        if p is None:
            return bad_request("not_found", "Paiement introuvable.", 404)
        try:
            reason = _reason(request)
            amount = None
            if request.data.get("amount") not in (None, ""):
                try:
                    amount = Decimal(str(request.data["amount"]))
                except InvalidOperation:
                    raise ValidationError("Montant invalide.", code="invalid_amount")
                if amount <= 0 or amount > p.amount:
                    raise ValidationError("Le montant doit être compris entre 0 et le montant payé.", code="invalid_amount")
            try:
                p.refund(amount=amount, note=f"Back-Office : {reason}")
            except ValidationError as exc:
                raise ValidationError(exc.messages[0], code="invalid_transition")
        except ValidationError as exc:
            return _invalid(exc)
        audit_op(request, "payment.refunded", p, reason=reason, amount=_money(p.refunded_amount), booking_id=p.booking_id)
        return Response(_payment_row(p))


def _payout_row(p: Payout, with_balance: bool = False) -> dict:
    row = {"id": p.pk, "artisan_id": p.handyman_id, "artisan": public_name(p.handyman), "amount": _money(p.amount), "status": p.status,
           "requested_at": p.requested_at, "processed_at": p.processed_at, "notes": p.notes or ""}
    if with_balance:
        row["available_after"] = _money(artisan_available_earnings(p.handyman))
    return row


class PayoutList(BOView):
    bo_permission = "finance.view"

    def get(self, request):
        qs = Payout.objects.select_related("handyman")
        if request.query_params.get("status") in ("pending", "sent", "failed"):
            qs = qs.filter(status=request.query_params["status"])
        return paginate(request, qs.order_by("-requested_at", "-id"), _payout_row)


class PayoutDecision(BOView):
    """Valider (virement effectué, RÉFÉRENCE obligatoire) ou rejeter (motif) un retrait. Un rejet libère les gains."""
    bo_permission = "finance.manage"

    @transaction.atomic
    def post(self, request, pk, op):
        payout = Payout.objects.select_for_update().select_related("handyman").filter(pk=pk).first()
        if payout is None:
            return bad_request("not_found", "Retrait introuvable.", 404)
        if payout.status != "pending":
            return bad_request("not_pending", "Ce retrait a déjà été traité.", 409)
        try:
            if op == "approve":
                reference = _reason(request, "reference", 4)         # preuve du virement réellement effectué
                payout.status, payout.notes = "sent", f"Réf. {reference}"
                title, text = "Retrait envoyé", f"Votre retrait de {payout.amount:.0f} FCFA a été envoyé."
            elif op == "reject":
                reason = _reason(request)
                payout.status, payout.notes = "failed", f"Rejeté : {reason}"
                title, text = "Retrait refusé", f"Votre retrait de {payout.amount:.0f} FCFA n'a pas pu être effectué : {reason}"
            else:
                return bad_request("invalid_action", "Opération inconnue.", 404)
        except ValidationError as exc:
            return _invalid(exc)
        payout.processed_at = timezone.now()
        payout.save(update_fields=["status", "notes", "processed_at"])
        notify(payout.handyman_id, "system", text, title=title, data={"kind": "notifications"}, dedupe_key=f"payout:{payout.pk}:{payout.status}")
        audit_op(request, f"payout.{'sent' if op == 'approve' else 'rejected'}", payout, amount=_money(payout.amount), note=payout.notes)
        return Response(_payout_row(payout, with_balance=True))


class InvoiceList(BOView):
    bo_permission = "finance.view"

    def get(self, request):
        qs = Invoice.objects.select_related("booking", "booking__client", "booking__handyman")
        return paginate(request, qs.order_by("-id"), lambda i: {
            "id": i.pk, "number": i.number, "booking_id": i.booking_id, "client": public_name(i.booking.client), "artisan": public_name(i.booking.handyman),
            "amount": _money(i.amount), "fee": _money(i.fee), "total": _money(i.total)})


# ═══ Support ════════════════════════════════════════════════════════════════════════════════════════════════════════

DISPUTE_SLA = timedelta(hours=48)
REPORT_SLA = timedelta(hours=72)


class SupportQueue(BOView):
    """Ce qui attend une réponse humaine, du plus ancien au plus récent, avec dépassement de délai de traitement."""
    bo_permission = "support.manage"

    def get(self, request):
        now = timezone.now()
        items = []
        for d in Dispute.objects.filter(status__in=("open", "under_review")).select_related("booking", "reporter"):
            age = now - d.created_at
            items.append({"kind": "dispute", "id": d.pk, "title": f"Litige sur la réservation #{d.booking_id}", "excerpt": d.reason[:160], "status": d.status,
                          "who": public_name(d.reporter), "created_at": d.created_at, "age_hours": int(age.total_seconds() // 3600), "overdue": age > DISPUTE_SLA,
                          "href": f"/backoffice/bookings?tab=disputes&id={d.pk}"})
        for r in Report.objects.filter(is_resolved=False).select_related("reporter", "review", "message"):
            age = now - r.created_at
            items.append({"kind": "report", "id": r.pk, "title": f"Signalement ({'avis' if r.report_type == 'review' else 'message'})", "excerpt": r.reason[:160],
                          "status": "open", "who": public_name(r.reporter), "created_at": r.created_at, "age_hours": int(age.total_seconds() // 3600),
                          "overdue": age > REPORT_SLA, "href": "/backoffice/reviews?tab=reports"})
        items.sort(key=lambda i: i["created_at"])
        return Response({"count": len(items), "overdue": sum(1 for i in items if i["overdue"]), "results": items[:200],
                         "sla_hours": {"dispute": int(DISPUTE_SLA.total_seconds() // 3600), "report": int(REPORT_SLA.total_seconds() // 3600)}})


class SupportOverview(BOView):
    """Dossier d'un compte pour répondre à un utilisateur : activité récente, litiges, signalements, notes internes."""
    bo_permission = "support.manage"

    def get(self, request, pk):
        u = User.objects.filter(pk=pk, is_staff=False).first()
        if u is None:
            return bad_request("not_found", "Compte introuvable.", 404)
        bookings = Booking.objects.filter(Q(client=u) | Q(handyman=u)).select_related("service").order_by("-created_at")[:10]
        return Response({
            "user": {"id": u.pk, "name": public_name(u), "phone": mask_phone(u.phone), "city": u.city, "is_active": u.is_active, "is_verified": u.is_verified,
                     "date_joined": u.date_joined, "last_login": u.last_login},
            "bookings": [{"id": b.pk, "status": b.status, "role": "client" if b.client_id == u.pk else "artisan", "service": b.service.title if b.service_id else None,
                          "booking_date": b.booking_date} for b in bookings],
            "disputes": [{"id": d.pk, "booking_id": d.booking_id, "status": d.status, "created_at": d.created_at}
                         for d in Dispute.objects.filter(Q(reporter=u) | Q(booking__client=u) | Q(booking__handyman=u)).order_by("-created_at")[:10]],
            "reports_filed": Report.objects.filter(reporter=u).count(),
            "notifications": [{"title": n.title or n.get_notification_type_display(), "category": n.category, "at": n.created_at, "push_status": n.push_status or None}
                              for n in Notification.objects.filter(user=u).order_by("-created_at")[:10]],        # titres seulement
            "notes": [{"id": n.pk, "body": n.body, "author": public_name(n.author) if n.author_id else "—", "created_at": n.created_at} for n in u.support_notes.select_related("author")[:30]],
        })


class SupportNotes(BOView):
    bo_permission = "support.manage"

    def post(self, request, pk):
        u = User.objects.filter(pk=pk, is_staff=False).first()
        if u is None:
            return bad_request("not_found", "Compte introuvable.", 404)
        body = str(request.data.get("body") or "").strip()
        if len(body) < 3:
            return Response({"code": "invalid", "detail": "Formulaire invalide.", "fields": {"body": "La note est vide ou trop courte."}}, status=400)
        if len(body) > 2000:
            return Response({"code": "invalid", "detail": "Formulaire invalide.", "fields": {"body": "La note dépasse 2000 caractères."}}, status=400)
        note = SupportNote.objects.create(user=u, author=request.user, body=body)
        audit_op(request, "support.note_added", u, note_id=note.pk)         # le contenu reste dans la note, pas dans le journal
        return Response({"id": note.pk, "body": note.body, "author": public_name(request.user), "created_at": note.created_at}, status=201)
