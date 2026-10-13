"""Back-Office — KYC biométrique. Distinction stricte :
 - `kyc.review` : statut, anomalies, historique, contrôles requis, rapport documentaire (aucune donnée biométrique) ; demander une capture ou des pièces,
   ouvrir une revue manuelle ;
 - `kyc.biometric` (Super Admin par défaut) : scores, captures du visage (accès temporaire, no-store, journalisé), approuver ou refuser.
Aucune approbation sans les contrôles requis ; aucune décision sans motif ; tout est audité."""
from django.http import HttpResponse
from rest_framework.response import Response

from backoffice import rbac
from backoffice.common import BOView, audit_op, bad_request, public_name
from biometrics import services
from biometrics.crypto import BiometricUnavailable
from biometrics.models import BiometricCapture, BiometricVerification
from handy.models import HandymanProfile
from intelligence.models import DocumentAnalysis

NEEDS_BIOMETRIC_RIGHT = {"approve_manual", "approve_alternative", "reject"}


def _has_bio(request) -> bool:
    return rbac.has_permission(request.user, "kyc.biometric")


def _document_report(profile):
    doc = services.id_document(profile)
    a = DocumentAnalysis.objects.filter(document=doc).first() if doc else None
    return {"document_status": doc.status if doc else None, "analysis": {"risk_level": a.risk_level, "risk_label": a.get_risk_level_display(), "summary": a.summary, "ai_report": a.ai_report,
                                                                        "checks": a.checks, "at": a.created_at, "disclaimer": a.ocr_disclaimer} if a else None}


def biometric_block(profile, request) -> dict:
    ver = BiometricVerification.objects.filter(profile=profile).first()
    can_bio = _has_bio(request)
    base = {"status": ver.status if ver else "not_started", "status_label": ver.get_status_display() if ver else "Non commencée", "satisfied": bool(ver and ver.satisfied),
            "can_view_captures": can_bio, "can_decide_biometric": can_bio, "enabled": services.enabled(), "document": _document_report(profile)}
    if ver is None:
        return {**base, "sessions": [], "decisions": [], "missing_checks": ["aucune vérification commencée"], "consent": None}
    sessions = []
    for s in ver.sessions.all()[:20]:
        row = {"id": s.pk, "attempt": s.attempt_no, "status": s.status, "outcome": s.outcome, "outcome_label": s.get_outcome_display() if s.outcome else "—", "anomalies": s.anomalies,
               "provider": s.provider or "—", "created_at": s.created_at, "completed_at": s.completed_at, "challenges": s.challenges}
        if can_bio:                                                   # scores et captures : réservés aux administrateurs autorisés
            row.update({"liveness_passed": s.liveness_passed, "liveness_score": s.liveness_score, "match_score": s.match_score, "thresholds": s.thresholds,
                        "captures": [{"id": c.pk, "index": c.index, "kind": c.kind, "deleted": c.deleted_at is not None, "quality": c.quality}
                                     for c in s.captures.all()]})
        sessions.append(row)
    consent = profile.user.biometric_consents.first()
    return {**base, "human_review_requested_at": ver.human_review_requested_at, "human_review_reason": ver.human_review_reason, "decision_reason": ver.decision_reason,
            "decided_at": ver.decided_at, "decided_by": public_name(ver.decided_by) if ver.decided_by_id else None, "sessions": sessions,
            "decisions": [{"decision": d.decision, "decision_label": d.get_decision_display(), "reason": d.reason, "at": d.at, "by": public_name(d.actor) if d.actor_id else None}
                          for d in ver.decisions.select_related("actor")],
            "missing_checks": services.approval_checks(ver),
            "consent": {"version": consent.version, "granted_at": consent.granted_at, "withdrawn_at": consent.withdrawn_at} if consent else None}


class BiometricDetail(BOView):
    bo_permission = "kyc.review"

    def get(self, request, pk):
        profile = HandymanProfile.objects.select_related("user").filter(pk=pk).first()
        if profile is None:
            return bad_request("not_found", "Dossier introuvable.", 404)
        return Response(biometric_block(profile, request))


class BiometricDecision(BOView):
    bo_permission = "kyc.review"

    def post(self, request, pk):
        profile = HandymanProfile.objects.select_related("user").filter(pk=pk).first()
        if profile is None:
            return bad_request("not_found", "Dossier introuvable.", 404)
        decision = str(request.data.get("decision") or "")
        if decision in NEEDS_BIOMETRIC_RIGHT and not _has_bio(request):
            return bad_request("forbidden", "Cette décision exige l'accès aux données biométriques.", 403)
        ver = services.verification_for(profile)
        before = ver.status
        try:
            ver = services.decide(ver, by=request.user, decision=decision, reason=str(request.data.get("reason") or ""))
        except services.BiometricError as exc:
            return Response({"code": exc.code, "detail": exc.detail, **exc.extra}, status=exc.status)
        audit_op(request, f"kyc.biometric_{decision}", profile, from_status=before, to_status=ver.status, reason=str(request.data.get("reason"))[:300])
        return Response(biometric_block(profile, request))


class BiometricCaptureFile(BOView):
    """Lecture d'une capture du visage : droit `kyc.biometric`, déchiffrée en mémoire, jamais d'URL, no-store, chaque ouverture journalisée."""
    bo_permission = "kyc.biometric"

    def get(self, request, pk):
        cap = BiometricCapture.objects.select_related("session__verification__profile").filter(pk=pk).first()
        if cap is None or cap.deleted_at is not None:
            return bad_request("not_found", "Capture introuvable ou supprimée.", 404)
        try:
            data = services.read_capture(cap)
        except (BiometricUnavailable, OSError, ValueError):
            return bad_request("unreadable", "Capture illisible.", 422)
        audit_op(request, "kyc.biometric_capture_viewed", cap.session.verification.profile, session=cap.session_id, index=cap.index)
        response = HttpResponse(data, content_type="image/jpeg")
        response["Cache-Control"] = "private, no-store, max-age=0"
        response["Referrer-Policy"] = "no-referrer"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Disposition"] = 'inline; filename="capture"'
        return response
