"""Module Back-Office « Engagements » : contrats récurrents et de longue durée, échéances, litiges, modération, règles.

 - la plateforme ne confirme JAMAIS un paiement à la place d'une partie et ne modifie jamais un montant de contrat : elle
   suspend, reprend ou résilie (motif obligatoire, journalisé), traite les litiges et modère besoins et évaluations ;
 - aucune pièce justificative, adresse précise ni contact complet dans les réponses (noms publics, téléphone masqué) ;
 - règles par catégorie : lecture `engagements.view`, écriture `settings.manage` (valeurs bornées, avant/après journalisés)."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.response import Response

from backoffice import rbac
from backoffice.common import BOView, apply_range, audit_op, bad_request, money, ordering, paginate, phone_for, public_name
from engagements import rules as rules_mod
from engagements import serializers as S
from engagements.models import (
    ContractInstallment, EngagementApplication, EngagementContract, EngagementDispute, EngagementEvaluation, EngagementPosting, EngagementRule, EvaluationReport,
    InstallmentPayment,
)
from engagements.services import contracts as contract_svc
from engagements.services import disputes as dispute_svc
from engagements.services import installments as inst_svc
from engagements.services.common import EngagementError
from handy.models import ServiceCategory
from handy.notifications import notify
from trust.models import AuditEvent

MIN_REASON = 5


def _reason(request, *, minimum: int = MIN_REASON) -> str:
    reason = str(request.data.get("reason") or "").strip()
    if len(reason) < minimum:
        raise EngagementError("reason_required", f"Un motif d'au moins {minimum} caractères est obligatoire.", 400)
    return reason[:500]


def _error(exc: EngagementError) -> Response:
    return Response({"code": exc.code, "detail": exc.message, **exc.extra}, status=exc.status)


def _party(u, request) -> dict:
    return {"id": u.pk, "name": public_name(u), "phone": phone_for(request, u.phone), "is_active": u.is_active}


def _contract_row(c: EngagementContract) -> dict:
    return {"id": c.pk, "title": c.title, "status": c.status, "mission_type": c.mission_type, "work_relationship": c.work_relationship, "category": c.category.name,
            "principal": {"id": c.principal_id, "name": public_name(c.principal)}, "organization": c.organization.name if c.organization_id else None,
            "worker": {"id": c.worker_id, "name": public_name(c.worker)}, "start_date": c.start_date, "end_date": c.end_date, "ends_on": c.ends_on,
            "amount": money(c.amount), "period": c.period, "currency": c.currency, "created_at": c.created_at, "updated_at": c.updated_at,
            "open_disputes": getattr(c, "n_disputes", 0), "overdue_installments": getattr(c, "n_overdue", 0)}


# ═══ Tableau de bord ════════════════════════════════════════════════════════════════════════════════════════════════

class EngagementOverview(BOView):
    """Indicateurs RÉELS : volumes par état, encours contractuel mensuel, retards, litiges, renouvellements, durée moyenne."""
    bo_permission = "engagements.view"

    def get(self, request):
        now = timezone.now()
        today = timezone.localdate()
        by_status = dict(EngagementContract.objects.values_list("status").annotate(n=Count("id")))
        live = EngagementContract.objects.filter(status__in=EngagementContract.LIVE)
        monthly = live.filter(period="monthly").aggregate(t=Sum("amount"))["t"]
        ended = EngagementContract.objects.filter(status__in=("terminated", "completed"), activated_at__isnull=False, ended_at__isnull=False)
        durations = [(c.ended_at - c.activated_at).days for c in ended.only("activated_at", "ended_at")[:2000]]
        overdue = ContractInstallment.objects.filter(status="overdue")
        series = (EngagementContract.objects.filter(created_at__gte=now - timedelta(days=365)).annotate(m=TruncMonth("created_at")).values("m").annotate(n=Count("id")).order_by("m"))
        paid_series = (InstallmentPayment.objects.filter(status="confirmed", responded_at__gte=now - timedelta(days=365)).annotate(m=TruncMonth("responded_at"))
                       .values("m").annotate(t=Sum("amount"), n=Count("id")).order_by("m"))
        renewals = EngagementContract.objects.filter(renewal_count__gt=0).count()
        out = {
            "generated_at": now,
            "contracts": {"total": sum(by_status.values()), "by_status": by_status, "live": live.count(),
                          "by_mission_type": dict(live.values_list("mission_type").annotate(n=Count("id"))),
                          "by_relationship": dict(live.values_list("work_relationship").annotate(n=Count("id"))),
                          "monthly_commitment": money(monthly), "currency": "XOF", "renewed": renewals,
                          "average_duration_days": round(sum(durations) / len(durations)) if durations else None, "terminations": by_status.get("terminated", 0),
                          "created_30d": EngagementContract.objects.filter(created_at__gte=now - timedelta(days=30)).count()},
            "installments": {"overdue": overdue.count(), "overdue_amount": money(sum((inst_svc.totals(i)["balance"] for i in overdue.select_related("contract")[:500]), Decimal("0"))),
                             "due_7d": ContractInstallment.objects.filter(status__in=("scheduled", "due"), due_date__gte=today, due_date__lte=today + timedelta(days=7)).count(),
                             "payments_awaiting_confirmation": InstallmentPayment.objects.filter(status="declared").count(),
                             "payments_contested": InstallmentPayment.objects.filter(status="rejected").count()},
            "postings": {"open": EngagementPosting.objects.filter(status="open").count(), "applications_30d": EngagementApplication.objects.filter(created_at__gte=now - timedelta(days=30)).count()},
            "disputes": {"open": EngagementDispute.objects.filter(status__in=("open", "under_review")).count(), "total": EngagementDispute.objects.count()},
            "evaluations": {"total": EngagementEvaluation.objects.count(), "hidden": EngagementEvaluation.objects.filter(is_hidden=True).count(),
                            "reports_open": EvaluationReport.objects.filter(is_resolved=False).count()},
            "series": {"contracts_created": [{"month": r["m"].date().isoformat()[:7], "count": r["n"]} for r in series],
                       "confirmed_payments": [{"month": r["m"].date().isoformat()[:7], "count": r["n"], "amount": money(r["t"])} for r in paid_series]},
        }
        return Response(out)


# ═══ Contrats ═══════════════════════════════════════════════════════════════════════════════════════════════════════

class ContractList(BOView):
    bo_permission = "engagements.view"

    def get(self, request):
        p = request.query_params
        qs = (EngagementContract.objects.select_related("category", "principal", "worker", "organization")
              .annotate(n_disputes=Count("disputes", filter=Q(disputes__status__in=("open", "under_review")), distinct=True),
                        n_overdue=Count("installments", filter=Q(installments__status="overdue"), distinct=True)))
        if p.get("status"):
            qs = qs.filter(status__in=[s for s in p["status"].split(",") if s])
        for field in ("mission_type", "work_relationship"):
            if p.get(field):
                qs = qs.filter(**{field: p[field]})
        if (p.get("category") or "").isdigit():
            qs = qs.filter(category_id=int(p["category"]))
        if (p.get("user") or "").isdigit():  # contrats d'un compte (fiche utilisateur) : donneur d'ordre OU prestataire
            qs = qs.filter(Q(principal_id=int(p["user"])) | Q(worker_id=int(p["user"])))
        if p.get("flag") == "overdue":
            qs = qs.filter(n_overdue__gt=0)
        elif p.get("flag") == "disputed":
            qs = qs.filter(n_disputes__gt=0)
        q = (p.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(principal__first_name__icontains=q) | Q(principal__last_name__icontains=q) | Q(worker__first_name__icontains=q)
                           | Q(worker__last_name__icontains=q) | Q(organization__name__icontains=q))
        qs = apply_range(request, qs, "created_at").order_by(ordering(request, {"created_at": "created_at", "start_date": "start_date", "amount": "amount", "status": "status"}, "-created_at"), "-id")
        return paginate(request, qs, _contract_row)


class ContractDetail(BOView):
    bo_permission = "engagements.view"

    def get(self, request, pk):
        c = EngagementContract.objects.select_related("category", "principal", "worker", "organization", "notice_given_by").filter(pk=pk).first()
        if c is None:
            return bad_request("not_found", "Contrat introuvable.", 404)
        installments = []
        for i in c.installments.prefetch_related("payments", "lines").order_by("sequence"):
            t = inst_svc.totals(i)
            installments.append({"id": i.pk, "number": i.sequence + 1, "period_start": i.period_start, "period_end": i.period_end, "due_date": i.due_date, "status": i.status,
                                 "base_amount": money(i.base_amount) if i.base_amount is not None else None, "total": money(t["total"]), "confirmed": money(t["confirmed"]),
                                 "declared": money(t["declared"]), "balance": money(t["balance"]), "platform_fee": money(i.platform_fee), "platform_fee_status": i.platform_fee_status,
                                 "payments": [{"id": p.pk, "amount": money(p.amount), "method": p.method, "status": p.status, "declared_by_role": p.declared_by_role, "paid_on": p.paid_on,
                                               "is_advance": p.is_advance, "has_evidence": bool(p.evidence)} for p in i.payments.all()]})
        terms = contract_svc.snapshot(c)
        terms.pop("location_address", None)                       # l'adresse précise reste entre les parties
        events = [{"id": e.pk, "type": e.type, "actor": public_name(e.actor) if e.actor_id else "Système", "data": e.data, "at": e.created_at} for e in c.events.select_related("actor").order_by("-created_at", "-id")[:150]]
        return Response({
            **_contract_row(c), "terms": terms, "terms_version": c.terms_version, "terms_hash": c.terms_hash, "renewal_count": c.renewal_count, "end_reason": c.end_reason, "closed_at": c.closed_at,
            "principal_detail": _party(c.principal, request), "worker_detail": _party(c.worker, request),
            "acceptances": [{"role": a.role, "terms_version": a.terms_version, "terms_hash": a.terms_hash, "accepted_at": a.accepted_at} for a in c.acceptances.order_by("terms_version", "accepted_at")],
            "amendments": [{"id": a.pk, "kind": a.kind, "status": a.status, "changes": a.changes, "reason": a.reason, "effective_date": a.effective_date, "created_at": a.created_at} for a in c.amendments.order_by("-created_at")],
            "suspensions": [{"starts_on": s.starts_on, "ends_on": s.ends_on, "source": s.source, "reason": s.reason} for s in c.suspensions.all()],
            "installments": installments, "events": events,
            "disputes": [{"id": d.pk, "kind": d.kind, "status": d.status, "created_at": d.created_at} for d in c.disputes.order_by("-created_at")],
            "evaluations": [{"id": e.pk, "kind": e.kind, "rating": e.rating, "is_hidden": e.is_hidden, "created_at": e.created_at} for e in c.evaluations.order_by("-created_at")],
            "admin_actions": [{"action": a.action, "at": a.created_at, "by": public_name(a.actor) if a.actor_id else "Système", "reason": (a.data or {}).get("reason", "")}
                              for a in AuditEvent.objects.filter(target_type="engagementcontract", target_id=c.pk).select_related("actor")[:30]],
        })


class ContractDecision(BOView):
    """Suspension, reprise ou résiliation par la plateforme (litige, fraude) : motif obligatoire, journal d'audit, parties notifiées."""
    bo_permission = "engagements.manage"

    def post(self, request, pk):
        c = EngagementContract.objects.filter(pk=pk).first()
        if c is None:
            return bad_request("not_found", "Contrat introuvable.", 404)
        action = str(request.data.get("action") or "")
        try:
            reason = _reason(request)
            if action not in ("suspend", "resume", "terminate"):
                raise EngagementError("invalid", "Action inconnue (suspend, resume, terminate).", 400)
            c = contract_svc.admin_decision(c, request.user, action, reason)
        except EngagementError as exc:
            return _error(exc)
        audit_op(request, f"engagement.contract_{action}", c, reason=reason, status=c.status)
        return Response(_contract_row(c))


# ═══ Besoins ════════════════════════════════════════════════════════════════════════════════════════════════════════

def _posting_row(p: EngagementPosting) -> dict:
    return {"id": p.pk, "title": p.title, "status": p.status, "mission_type": p.mission_type, "work_relationship": p.work_relationship, "city": p.city, "category": p.category.name,
            "publisher": {"id": p.publisher_id, "name": public_name(p.publisher)}, "organization": p.organization.name if p.organization_id else None, "amount": money(p.amount),
            "period": p.period, "start_date": p.start_date, "published_at": p.published_at, "created_at": p.created_at, "applications": getattr(p, "n_apps", 0)}


class PostingList(BOView):
    bo_permission = "engagements.view"

    def get(self, request):
        p = request.query_params
        qs = EngagementPosting.objects.select_related("category", "publisher", "organization").annotate(n_apps=Count("applications", distinct=True))
        if p.get("status"):
            qs = qs.filter(status__in=[s for s in p["status"].split(",") if s])
        for field in ("mission_type", "work_relationship"):
            if p.get(field):
                qs = qs.filter(**{field: p[field]})
        q = (p.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(city__icontains=q) | Q(description__icontains=q))
        qs = apply_range(request, qs, "created_at").order_by("-created_at", "-id")
        return paginate(request, qs, _posting_row)


class PostingModerate(BOView):
    """Retire un besoin abusif ou trompeur (motif obligatoire) : il est annulé, jamais supprimé ; son auteur est prévenu."""
    bo_permission = "engagements.manage"

    def post(self, request, pk):
        try:
            reason = _reason(request)
        except EngagementError as exc:
            return _error(exc)
        with transaction.atomic():
            p = EngagementPosting.objects.select_for_update().select_related("publisher").filter(pk=pk).first()
            if p is None:
                return bad_request("not_found", "Besoin introuvable.", 404)
            if p.status in ("cancelled", "closed", "filled", "expired"):
                return bad_request("already_closed", "Ce besoin est déjà clos.", 409)
            p.status, p.closed_at, p.version = "cancelled", timezone.now(), p.version + 1
            p.save(update_fields=["status", "closed_at", "version", "updated_at"])
            EngagementApplication.objects.filter(posting=p, status__in=EngagementApplication.OPEN).update(status="rejected", decision_note="Besoin retiré par Tratra.", decided_at=timezone.now())
        audit_op(request, "engagement.posting_removed", p, reason=reason)
        notify(p.publisher, "system", f"Votre besoin « {p.title} » a été retiré par Tratra : {reason}", title="Besoin retiré", data={"kind": "posting", "id": p.pk}, dedupe_key=f"eng-posting-{p.pk}-removed")
        return Response(_posting_row(p))


# ═══ Échéances ══════════════════════════════════════════════════════════════════════════════════════════════════════

def _installment_row(i: ContractInstallment) -> dict:
    t = inst_svc.totals(i)
    c = i.contract
    return {"id": i.pk, "contract": {"id": c.pk, "title": c.title, "status": c.status}, "principal": {"id": c.principal_id, "name": public_name(c.principal)},
            "worker": {"id": c.worker_id, "name": public_name(c.worker)}, "number": i.sequence + 1, "period_start": i.period_start, "period_end": i.period_end, "due_date": i.due_date,
            "status": i.status, "total": money(t["total"]), "confirmed": money(t["confirmed"]), "declared": money(t["declared"]), "balance": money(t["balance"]), "currency": i.currency,
            "platform_fee": money(i.platform_fee), "platform_fee_status": i.platform_fee_status, "platform_fee_payer": i.platform_fee_payer}


class InstallmentList(BOView):
    bo_permission = "engagements.view"

    def get(self, request):
        p = request.query_params
        qs = ContractInstallment.objects.select_related("contract", "contract__principal", "contract__worker")
        if p.get("status"):
            qs = qs.filter(status__in=[s for s in p["status"].split(",") if s])
        if (p.get("contract") or "").isdigit():
            qs = qs.filter(contract_id=int(p["contract"]))
        if p.get("fee") in ("due", "settled", "waived"):
            qs = qs.filter(platform_fee_status=p["fee"])
        if (p.get("user") or "").isdigit():
            qs = qs.filter(Q(contract__principal_id=int(p["user"])) | Q(contract__worker_id=int(p["user"])))
        start, stop = parse_date(p.get("from") or ""), parse_date(p.get("to") or "")
        if start:
            qs = qs.filter(due_date__gte=start)
        if stop:
            qs = qs.filter(due_date__lte=stop)
        qs = qs.order_by("due_date", "id")
        return paginate(request, qs, _installment_row)


class InstallmentFee(BOView):
    """Règlement de la commission de la plateforme sur une échéance : « réglée » exige la référence du règlement fait hors plateforme,
    « abandonnée » un motif. Ne touche jamais au montant dû entre les parties."""
    bo_permission = "finance.manage"

    def post(self, request, pk):
        i = ContractInstallment.objects.select_related("contract").filter(pk=pk).first()
        if i is None:
            return bad_request("not_found", "Échéance introuvable.", 404)
        status = str(request.data.get("status") or "")
        if status not in ("settled", "waived"):
            return bad_request("invalid", "Statut attendu : settled ou waived.")
        if i.platform_fee_status != "due":
            return bad_request("not_due", "Aucune commission à régler sur cette échéance.", 409)
        note = str(request.data.get("reference" if status == "settled" else "reason") or "").strip()[:200]
        if len(note) < 3:
            return bad_request("note_required", "Référence du règlement (ou motif d'abandon) obligatoire.")
        i.platform_fee_status = status
        i.note = (f"Commission {'réglée' if status == 'settled' else 'abandonnée'} : {note}")[:300]
        i.save(update_fields=["platform_fee_status", "note", "updated_at"])
        audit_op(request, "engagement.fee_" + status, i, reference=note, amount=str(i.platform_fee))
        return Response(_installment_row(i))


# ═══ Litiges ════════════════════════════════════════════════════════════════════════════════════════════════════════

def _dispute_row(d: EngagementDispute) -> dict:
    c = d.contract
    return {"id": d.pk, "contract": {"id": c.pk, "title": c.title, "status": c.status}, "kind": d.kind, "status": d.status, "opened_by": {"id": d.opened_by_id, "name": public_name(d.opened_by)},
            "opened_by_role": "worker" if d.opened_by_id == c.worker_id else "principal", "installment": d.installment_id, "created_at": d.created_at, "resolved_at": d.resolved_at,
            "resolution_action": d.resolution_action}


class DisputeList(BOView):
    bo_permission = "engagements.view"

    def get(self, request):
        p = request.query_params
        qs = EngagementDispute.objects.select_related("contract", "opened_by")
        if p.get("status"):
            qs = qs.filter(status__in=[s for s in p["status"].split(",") if s])
        if p.get("kind"):
            qs = qs.filter(kind=p["kind"])
        if (p.get("user") or "").isdigit():
            uid = int(p["user"])
            qs = qs.filter(Q(opened_by_id=uid) | Q(contract__principal_id=uid) | Q(contract__worker_id=uid))
        return paginate(request, apply_range(request, qs, "created_at").order_by("-created_at", "-id"), _dispute_row)


class DisputeDetail(BOView):
    bo_permission = "engagements.view"

    def get(self, request, pk):
        d = EngagementDispute.objects.select_related("contract", "contract__principal", "contract__worker", "opened_by", "installment").filter(pk=pk).first()
        if d is None:
            return bad_request("not_found", "Litige introuvable.", 404)
        c = d.contract
        return Response({**_dispute_row(d), "reason": d.reason, "resolution": d.resolution, "principal": _party(c.principal, request), "worker": _party(c.worker, request),
                         "installment_detail": _installment_row(d.installment) if d.installment_id else None,
                         "events": [{"type": e.type, "at": e.created_at, "data": e.data} for e in c.events.order_by("-created_at")[:40]]})


class DisputeAction(BOView):
    """`review` (prise en charge) ou `resolve` (décision motivée ; peut suspendre ou résilier le contrat, jamais corriger un paiement)."""
    bo_permission = "engagements.manage"

    def post(self, request, pk, op):
        d = EngagementDispute.objects.select_related("contract").filter(pk=pk).first()
        if d is None:
            return bad_request("not_found", "Litige introuvable.", 404)
        try:
            with transaction.atomic():
                if op == "review":
                    d = dispute_svc.take_review(d, request.user)
                    audit_op(request, "engagement.dispute_review", d)
                elif op == "resolve":
                    accepted = request.data.get("accepted")
                    if not isinstance(accepted, bool):
                        raise EngagementError("invalid", "`accepted` doit être vrai ou faux.", 400)
                    action = str(request.data.get("resolution_action") or "none")
                    resolution = str(request.data.get("resolution") or "")
                    d = dispute_svc.resolve(d, request.user, accepted=accepted, resolution=resolution, action=action)
                    if action in ("suspend", "terminate"):
                        contract_svc.admin_decision(d.contract, request.user, action, resolution)
                    audit_op(request, "engagement.dispute_resolved", d, resolution_action=action, accepted=accepted)
                else:
                    return bad_request("unknown_action", "Action inconnue.", 404)
        except EngagementError as exc:
            return _error(exc)
        return Response(_dispute_row(EngagementDispute.objects.select_related("contract", "opened_by").get(pk=d.pk)))


# ═══ Évaluations ════════════════════════════════════════════════════════════════════════════════════════════════════

def _evaluation_row(e: EngagementEvaluation) -> dict:
    return {"id": e.pk, "contract": {"id": e.contract_id, "title": e.contract.title}, "kind": e.kind, "rating": e.rating, "comment": e.comment, "reply": e.reply,
            "author": {"id": e.author_id, "name": public_name(e.author)}, "subject": {"id": e.subject_id, "name": public_name(e.subject)}, "is_hidden": e.is_hidden,
            "hidden_reason": e.hidden_reason, "reports": getattr(e, "n_reports", 0), "created_at": e.created_at}


class EvaluationList(BOView):
    bo_permission = "engagements.view"

    def get(self, request):
        p = request.query_params
        qs = EngagementEvaluation.objects.select_related("contract", "author", "subject").annotate(n_reports=Count("reports", filter=Q(reports__is_resolved=False), distinct=True))
        if p.get("hidden") in ("true", "false"):
            qs = qs.filter(is_hidden=p["hidden"] == "true")
        if p.get("flag") == "reported":
            qs = qs.filter(n_reports__gt=0)
        return paginate(request, apply_range(request, qs, "created_at").order_by("-n_reports", "-created_at", "-id"), _evaluation_row)


class EvaluationModerate(BOView):
    """Masquer (motif obligatoire) ou rétablir une évaluation : jamais supprimée ; les signalements ouverts sont clos ; journal d'audit."""
    bo_permission = "engagements.manage"

    def post(self, request, pk, op):
        e = EngagementEvaluation.objects.select_related("contract", "author", "subject").filter(pk=pk).first()
        if e is None:
            return bad_request("not_found", "Évaluation introuvable.", 404)
        if op not in ("hide", "restore"):
            return bad_request("unknown_action", "Action inconnue.", 404)
        try:
            reason = _reason(request) if op == "hide" else str(request.data.get("reason") or "").strip()[:500]
        except EngagementError as exc:
            return _error(exc)
        hide = op == "hide"
        if e.is_hidden == hide:
            return bad_request("already", "Cette évaluation est déjà dans cet état.", 409)
        e.is_hidden, e.hidden_reason, e.hidden_by = hide, reason if hide else "", request.user if hide else None
        e.save(update_fields=["is_hidden", "hidden_reason", "hidden_by"])
        EvaluationReport.objects.filter(evaluation=e, is_resolved=False).update(is_resolved=True)
        audit_op(request, f"engagement.evaluation_{op}", e, reason=reason)
        return Response(_evaluation_row(e))


# ═══ Règles par catégorie ═══════════════════════════════════════════════════════════════════════════════════════════

BOOLS = ("allow_recurring", "allow_long_term", "allow_employment", "active")
INTS = {"max_duration_months": (1, 240), "min_notice_days_independent": (0, 365), "min_notice_days_employment": (0, 365), "max_advance_percent": (0, 100),
        "late_grace_days": (0, 60), "min_days_for_evaluation": (0, 365), "evaluation_interval_days": (7, 365), "evaluation_edit_days": (0, 60)}
DECS = {"commission_percent_independent": (Decimal("0"), Decimal("50")), "commission_percent_employment": (Decimal("0"), Decimal("50"))}


class RuleList(BOView):
    bo_permission = "engagements.view"

    def get(self, request):
        explicit = {r.category_id: r for r in EngagementRule.objects.filter(is_default=False).select_related("category")}
        default = EngagementRule.objects.filter(is_default=True).first()
        categories = [{"category": {"id": c.pk, "name": c.name}, "customized": c.pk in explicit, "active": explicit[c.pk].active if c.pk in explicit else None,
                       **rules_mod.rules_payload(rules_mod.rules_for(c.pk))} for c in ServiceCategory.objects.order_by("name")]
        return Response({"default": {**rules_mod.rules_payload(rules_mod.rules_for(None)), "customized": default is not None, "active": default.active if default else None},
                         "categories": categories, "limits": {**{k: list(v) for k, v in INTS.items()}, **{k: [str(v[0]), str(v[1])] for k, v in DECS.items()}},
                         "notice": "Règles de fonctionnement de Tratra, pas un avis juridique. L'emploi salarié reste désactivé tant qu'il n'est pas autorisé ici."})


class RuleDetail(BOView):
    """`<id>` = identifiant de catégorie, ou `default` pour la règle générale. PUT crée/modifie ; DELETE revient à la règle générale."""
    bo_permission = {"GET": "engagements.view", "PUT": "settings.manage", "DELETE": "settings.manage"}

    def _target(self, key):
        if key == "default":
            return None, EngagementRule.objects.filter(is_default=True).first(), True
        if not key.isdigit() or not ServiceCategory.objects.filter(pk=int(key)).exists():
            return None, None, None
        return int(key), EngagementRule.objects.filter(category_id=int(key)).first(), False

    def get(self, request, key):
        category_id, rule, is_default = self._target(key)
        if is_default is None:
            return bad_request("not_found", "Catégorie introuvable.", 404)
        return Response({"customized": rule is not None, **rules_mod.rules_payload(rules_mod.rules_for(category_id))})

    def put(self, request, key):
        category_id, rule, is_default = self._target(key)
        if is_default is None:
            return bad_request("not_found", "Catégorie introuvable.", 404)
        data, errors = {}, {}
        for f in BOOLS:
            if f in request.data:
                if not isinstance(request.data[f], bool):
                    errors[f] = "Booléen attendu."
                else:
                    data[f] = request.data[f]
        for f, (lo, hi) in INTS.items():
            if f in request.data:
                try:
                    v = int(request.data[f])
                    if not lo <= v <= hi:
                        raise ValueError
                    data[f] = v
                except (TypeError, ValueError):
                    errors[f] = f"Entier attendu entre {lo} et {hi}."
        for f, (lo, hi) in DECS.items():
            if f in request.data:
                try:
                    v = Decimal(str(request.data[f])).quantize(Decimal("0.01"))
                    if not lo <= v <= hi:
                        raise ValueError
                    data[f] = v
                except (InvalidOperation, ValueError, TypeError):
                    errors[f] = f"Nombre attendu entre {lo} et {hi}."
        if "commission_payer" in request.data:
            if request.data["commission_payer"] in ("principal", "worker"):
                data["commission_payer"] = request.data["commission_payer"]
            else:
                errors["commission_payer"] = "principal ou worker."
        if errors:
            return Response({"code": "invalid", "detail": "Valeurs invalides.", "fields": errors}, status=400)
        if not data:
            return bad_request("empty", "Aucune modification.")
        reason = str(request.data.get("reason") or "").strip()[:300]
        effective = rules_mod.rules_for(category_id)
        before = rules_mod.rules_payload(effective)
        with transaction.atomic():
            if rule is None:      # nouvelle règle : part des valeurs actuellement en vigueur, seules les modifications demandées changent
                rule = EngagementRule(is_default=is_default, category_id=category_id, **{f: getattr(effective, f) for f in rules_mod.FIELDS})
            for f, v in data.items():
                setattr(rule, f, v)
            rule.save()
        after = rules_mod.rules_payload(rules_mod.rules_for(category_id))
        changed = {f: {"from": before.get(f), "to": after.get(f)} for f in data if before.get(f) != after.get(f)}
        audit_op(request, "engagement.rules_updated", rule, scope="default" if is_default else f"category:{category_id}", changes=changed, reason=reason)
        return Response({"customized": True, **after})

    def delete(self, request, key):
        category_id, rule, is_default = self._target(key)
        if is_default is None or rule is None:
            return bad_request("not_found", "Aucune règle personnalisée à supprimer.", 404)
        if is_default:
            return bad_request("forbidden", "La règle générale ne se supprime pas : modifiez-la.", 409)
        audit_op(request, "engagement.rules_reset", rule, scope=f"category:{category_id}")
        rule.delete()
        return Response(status=204)
