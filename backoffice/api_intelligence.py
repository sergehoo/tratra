"""Back-Office — contrôle intelligent : analyse assistée des documents KYC, dossiers de risque, état des fournisseurs d'IA.
L'IA et les règles PROPOSENT ; ces vues n'effectuent AUCUNE sanction, validation KYC ou attribution de badge."""
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from rest_framework.response import Response

from backoffice.common import BOView, apply_range, audit_op, bad_request, ordering, paginate, public_name
from handy.models import HandymanDocument
from intelligence import ai, documents, risk
from intelligence.models import DocumentAnalysis, RiskCase


def analysis_row(a: DocumentAnalysis) -> dict:
    return {"id": a.pk, "created_at": a.created_at, "risk_level": a.risk_level, "risk_label": a.get_risk_level_display(), "summary": a.summary, "ai_report": a.ai_report, "ai_provider": a.ai_provider, "checks": a.checks, "fields": a.fields,
            "ocr_engine": a.ocr_engine, "external_used": a.external_used, "disclaimer": a.ocr_disclaimer, "needs_human": True}


class DocumentAnalyze(BOView):
    bo_permission = "kyc.review"

    def post(self, request, pk):
        doc = HandymanDocument.objects.select_related("handyman", "handyman__user").filter(pk=pk).first()
        if doc is None or not doc.file:
            return bad_request("not_found", "Document introuvable.", 404)
        try:
            a = documents.analyze(doc, by=request.user)
        except (FileNotFoundError, ValueError, OSError):
            return bad_request("unreadable", "Le fichier du document est illisible.", 422)
        audit_op(request, "kyc.document_analyzed", doc, profile_id=doc.handyman_id, risk=a.risk_level, ocr=a.ocr_engine, external=a.external_used)
        return Response(analysis_row(a), status=201)


class DocumentAnalysisLast(BOView):
    bo_permission = "kyc.review"

    def get(self, request, pk):
        a = DocumentAnalysis.objects.filter(document_id=pk).first()
        return Response({"analysis": analysis_row(a) if a else None, "ai": ai.status(), "local_ocr": documents.local_ocr_available()})


def _case_row(c: RiskCase, *, detail: bool = False) -> dict:
    row = {"id": c.pk, "subject_id": c.subject_id, "subject_name": public_name(c.subject), "kind": c.kind, "kind_label": c.get_kind_display(), "status": c.status,
           "status_label": c.get_status_display(), "priority": c.priority, "explanation": c.explanation, "evidence": c.evidence, "related_users": c.related_users,
           "source": c.source, "detected_at": c.detected_at, "allowed": sorted(k for k, v in risk.ALLOWED.items() if c.status in v)}
    if detail:
        row["history"] = [{"decision": d.decision, "decision_label": d.get_decision_display(), "reason": d.reason, "at": d.at, "by": public_name(d.actor) if d.actor_id else None} for d in c.decisions.select_related("actor")]
    return row


class RiskCaseList(BOView):
    bo_permission = "kyc.review"

    def get(self, request):
        p = request.query_params
        qs = RiskCase.objects.select_related("subject")
        status = p.get("status", "active")
        if status == "active":
            qs = qs.filter(status__in=RiskCase.ACTIVE)
        elif status in dict(RiskCase.STATUSES):
            qs = qs.filter(status=status)
        if p.get("kind") in dict(RiskCase.KINDS):
            qs = qs.filter(kind=p["kind"])
        q = (p.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(subject__first_name__icontains=q) | Q(subject__last_name__icontains=q) | Q(subject__phone__icontains=q))
        qs = apply_range(request, qs, "detected_at")
        qs = qs.order_by(ordering(request, {"priority": "priority", "detected_at": "detected_at", "status": "status"}, "-priority"), "-detected_at", "-id")
        return paginate(request, qs, _case_row)


class RiskCaseDetail(BOView):
    bo_permission = "kyc.review"

    def get(self, request, pk):
        c = RiskCase.objects.select_related("subject").filter(pk=pk).first()
        return Response(_case_row(c, detail=True)) if c else bad_request("not_found", "Dossier introuvable.", 404)


class RiskCaseDecide(BOView):
    bo_permission = "kyc.review"

    def post(self, request, pk):
        c = RiskCase.objects.select_related("subject").filter(pk=pk).first()
        if c is None:
            return bad_request("not_found", "Dossier introuvable.", 404)
        decision, before = str(request.data.get("decision") or ""), c.status
        try:
            c = risk.decide(c, by=request.user, decision=decision, reason=str(request.data.get("reason") or ""))
        except ValidationError as exc:
            return bad_request(getattr(exc, "code", None) or "invalid", exc.messages[0], 400)
        audit_op(request, f"risk.case_{decision}", c, subject=c.subject_id, kind=c.kind, from_status=before, to_status=c.status, reason=str(request.data.get("reason"))[:300])
        return Response(_case_row(c, detail=True))


class RiskSummary(BOView):
    bo_permission = "kyc.review"

    def get(self, request):
        agg = RiskCase.objects.filter(status__in=RiskCase.ACTIVE).aggregate(active=Count("id"), high=Count("id", filter=Q(priority=3)))
        return Response({"active": agg["active"], "high": agg["high"], "open": RiskCase.objects.filter(status="open").count(), "ai": ai.status()})


class AIStatus(BOView):
    bo_permission = "settings.manage"

    def get(self, request):
        return Response({**ai.status(), "local_ocr": documents.local_ocr_available()})
