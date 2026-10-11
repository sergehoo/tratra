"""Back-Office — surveillance des évaluations et contestations. La détection PROPOSE ; ces vues enregistrent des décisions HUMAINES
motivées, historisées et journalisées. Suspension et bannissement exigent le droit de gestion des comptes ; le bannissement, un Super Admin."""
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.response import Response

from backoffice import rbac
from backoffice.common import BOView, apply_range, audit_op, bad_request, ordering, paginate, public_name
from handy.models import User
from reputation import watch as watch_svc
from reputation.models import ClientReview, EvaluationContest, EvaluationWatch


def _watch_row(w: EvaluationWatch, *, detail: bool = False) -> dict:
    row = {"id": w.pk, "subject_id": w.subject_id, "subject_name": public_name(w.subject), "subject_active": w.subject.is_active, "kind": w.kind, "kind_label": w.get_kind_display(),
           "status": w.status, "status_label": w.get_status_display(), "priority": w.priority, "explanation": w.explanation, "detected_at": w.detected_at,
           "last_detected_at": w.last_detected_at, "decisions": getattr(w, "n_decisions", None)}
    if detail:
        row["evidence"] = w.evidence
        row["history"] = [{"decision": d.decision, "decision_label": d.get_decision_display(), "reason": d.reason, "at": d.at, "by": public_name(d.actor) if d.actor_id else None} for d in w.decisions.select_related("actor")]
        row["allowed"] = sorted(k for k, v in watch_svc.ALLOWED.items() if w.status in v)
    return row


class WatchList(BOView):
    bo_permission = "reviews.moderate"

    def get(self, request):
        p = request.query_params
        qs = EvaluationWatch.objects.select_related("subject").annotate(n_decisions=Count("decisions"))
        status = p.get("status", "active")
        if status == "active":
            qs = qs.filter(status__in=EvaluationWatch.ACTIVE)
        elif status in dict(EvaluationWatch.STATUSES):
            qs = qs.filter(status=status)
        if p.get("kind") in dict(EvaluationWatch.KINDS):
            qs = qs.filter(kind=p["kind"])
        q = (p.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(subject__first_name__icontains=q) | Q(subject__last_name__icontains=q) | Q(subject__username__icontains=q) | Q(subject__phone__icontains=q))
        qs = apply_range(request, qs, "detected_at")
        qs = qs.order_by(ordering(request, {"priority": "priority", "detected_at": "detected_at", "status": "status"}, "-priority"), "-detected_at", "-id")
        return paginate(request, qs, _watch_row)


class WatchDetail(BOView):
    bo_permission = "reviews.moderate"

    def get(self, request, pk):
        w = EvaluationWatch.objects.select_related("subject").filter(pk=pk).first()
        if w is None:
            return bad_request("not_found", "Dossier introuvable.", 404)
        return Response(_watch_row(w, detail=True))


class WatchDecide(BOView):
    bo_permission = "reviews.moderate"

    def post(self, request, pk):
        w = EvaluationWatch.objects.select_related("subject").filter(pk=pk).first()
        if w is None:
            return bad_request("not_found", "Dossier introuvable.", 404)
        decision = str(request.data.get("decision") or "")
        if decision in ("suspend", "ban", "reinstate") and not rbac.has_permission(request.user, "users.manage"):
            return bad_request("forbidden", "Cette décision exige le droit de gérer les comptes.", 403)
        if decision == "ban" and not (request.user.is_superuser or "super_admin" in rbac.user_roles(request.user)):
            return bad_request("forbidden", "Seul un Super Admin peut décider un bannissement.", 403)
        before = w.status
        try:
            w = watch_svc.decide(w, by=request.user, decision=decision, reason=str(request.data.get("reason") or ""))
        except ValidationError as exc:
            return bad_request(getattr(exc, "code", None) or "invalid", exc.messages[0], 400)
        audit_op(request, f"reputation.watch_{decision}", w, subject=w.subject_id, from_status=before, to_status=w.status, reason=str(request.data.get("reason"))[:300])
        return Response(_watch_row(w, detail=True))


def _contest_row(c: EvaluationContest) -> dict:
    r = c.client_review
    return {"id": c.pk, "status": c.status, "status_label": c.get_status_display(), "reason": c.reason, "created_at": c.created_at, "resolution": c.resolution,
            "author_name": public_name(c.author), "evaluation": {"id": r.pk, "rating": r.rating, "comment": r.comment, "from": public_name(r.author), "hidden": r.is_hidden} if r else None}


class ContestList(BOView):
    bo_permission = "reviews.moderate"

    def get(self, request):
        qs = EvaluationContest.objects.select_related("author", "client_review", "client_review__author")
        status = request.query_params.get("status", "open")
        if status in dict(EvaluationContest.STATUSES):
            qs = qs.filter(status=status)
        return paginate(request, qs.order_by("-created_at", "-id"), _contest_row)


class ContestResolve(BOView):
    bo_permission = "reviews.moderate"

    def post(self, request, pk):
        c = EvaluationContest.objects.select_related("client_review", "author").filter(pk=pk).first()
        if c is None:
            return bad_request("not_found", "Contestation introuvable.", 404)
        if c.status != "open":
            return bad_request("not_open", "Cette contestation est déjà traitée.", 409)
        outcome, reason = str(request.data.get("outcome") or ""), str(request.data.get("reason") or "").strip()
        if outcome not in ("upheld", "rejected") or len(reason) < 10:
            return bad_request("invalid", "Choisissez une issue et motivez-la (10 caractères minimum).", 400)
        c.status, c.resolution, c.resolved_by, c.resolved_at = outcome, reason[:500], request.user, timezone.now()
        c.save()
        if outcome == "upheld" and c.client_review_id:
            ClientReview.objects.filter(pk=c.client_review_id).update(is_hidden=True, hidden_reason=reason[:500])     # masquée, jamais supprimée
        audit_op(request, f"reputation.contest_{outcome}", c, evaluation=c.client_review_id, reason=reason[:300])
        return Response(_contest_row(c))


class ReputationSummary(BOView):
    bo_permission = "reviews.moderate"

    def get(self, request):
        return Response({"watch_open": EvaluationWatch.objects.filter(status="open").count(), "watch_active": EvaluationWatch.objects.filter(status__in=EvaluationWatch.ACTIVE).count(),
                         "contests_open": EvaluationContest.objects.filter(status="open").count()})
