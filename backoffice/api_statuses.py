"""Back-Office — modération des statuts signalés : liste des signalements, retrait d'un statut (motif obligatoire, audité, auteur prévenu)
ou classement sans suite. Droit : `reviews.moderate`. Le contenu retiré n'est plus conservé (texte et média supprimés)."""
from django.utils import timezone
from rest_framework.response import Response

from backoffice.common import BOView, audit_op, bad_request, paginate, public_name
from handy import notifications
from statuses import services
from statuses.models import Status, StatusReport


def _row(r: StatusReport) -> dict:
    s = r.status
    return {"id": r.pk, "status": s.pk, "kind": s.kind, "text": s.text[:200] if s.deleted_at is None else "", "removed": s.deleted_at is not None,
            "author": {"id": s.author_id, "name": public_name(s.author)}, "reporter": public_name(r.reporter), "reason": r.reason,
            "created_at": r.created_at, "resolved": r.is_resolved, "has_media": bool(s.media)}


class StatusReportList(BOView):
    bo_permission = "reviews.moderate"

    def get(self, request):
        qs = StatusReport.objects.select_related("status", "status__author", "reporter").order_by("is_resolved", "-created_at")
        if request.query_params.get("resolved") in ("true", "false"):
            qs = qs.filter(is_resolved=request.query_params["resolved"] == "true")
        return paginate(request, qs, _row)


class StatusRemove(BOView):
    bo_permission = "reviews.moderate"

    def post(self, request, pk):
        status = Status.objects.select_related("author").filter(pk=pk).first()
        reason = str(request.data.get("reason") or "").strip()
        if status is None:
            return bad_request("not_found", "Statut introuvable.", 404)
        if len(reason) < 5:
            return bad_request("reason_required", "Un motif d'au moins 5 caractères est obligatoire.")
        services.remove_by_staff(status)
        StatusReport.objects.filter(status=status).update(is_resolved=True)
        audit_op(request, "status.removed", status, reason=reason[:255])
        notifications.notify(status.author_id, "system", "Un de vos statuts a été retiré par l'équipe Tratra car il ne respecte pas les règles d'utilisation.",
                             title="Statut retiré", data={"kind": "notifications"}, dedupe_key=f"status:{status.pk}:removed")
        return Response({"removed": True})


class StatusReportDismiss(BOView):
    bo_permission = "reviews.moderate"

    def post(self, request, pk):
        report = StatusReport.objects.filter(pk=pk).first()
        if report is None:
            return bad_request("not_found", "Signalement introuvable.", 404)
        report.is_resolved = True
        report.save(update_fields=["is_resolved"])
        audit_op(request, "status.report_dismissed", report.status)
        return Response({"resolved": True, "at": timezone.now()})
