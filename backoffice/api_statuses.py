"""Back-Office — modération des statuts signalés : signalements (filtres, recherche), contenu du statut signalé (consultation journalisée),
retrait motivé (l'auteur est prévenu) ou classement sans suite. Droit : `reviews.moderate`. Un statut retiré n'est plus conservé (texte et
média supprimés) ; un statut déjà supprimé par son auteur ou expiré n'a plus de contenu : seul le signalement reste."""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.response import Response

from backoffice.common import BOView, apply_range, audit_op, bad_request, ordering, paginate, public_name
from handy import messaging, notifications
from statuses import services
from statuses.models import Status, StatusReport

MIN_REASON = 5


def _state(s: Status) -> str:
    if s.removed_by_staff:
        return "removed_by_staff"
    if s.deleted_at is not None:
        return "deleted_by_author"
    if s.expires_at <= timezone.now():
        return "expired"
    return "active"


def _row(r: StatusReport) -> dict:
    s = r.status
    return {"id": r.pk, "status": s.pk, "kind": s.kind, "text": (s.text or "")[:200], "state": _state(s), "has_media": bool(s.media),
            "author": {"id": s.author_id, "name": public_name(s.author)}, "reporter": public_name(r.reporter), "reason": r.reason,
            "created_at": r.created_at, "resolved": r.is_resolved}


def _reason(request, errors: dict) -> str:
    value = str(request.data.get("reason") or "").strip()
    if len(value) < MIN_REASON:
        errors["reason"] = f"Un motif d'au moins {MIN_REASON} caractères est obligatoire."
    return value[:255]


class StatusReportList(BOView):
    bo_permission = "reviews.moderate"

    def get(self, request):
        p = request.query_params
        qs = StatusReport.objects.select_related("status", "status__author", "reporter")
        if p.get("resolved") in ("true", "false"):
            qs = qs.filter(is_resolved=p["resolved"] == "true")
        elif p.get("resolved") != "all":
            qs = qs.filter(is_resolved=False)
        q = (p.get("q") or "").strip()
        if q:
            cond = (Q(reason__icontains=q) | Q(status__text__icontains=q) | Q(reporter__first_name__icontains=q) | Q(reporter__last_name__icontains=q)
                    | Q(status__author__first_name__icontains=q) | Q(status__author__last_name__icontains=q))
            qs = qs.filter(cond | Q(pk=int(q)) | Q(status_id=int(q))) if q.isdigit() else qs.filter(cond)
        qs = apply_range(request, qs, "created_at").order_by(ordering(request, {"created_at": "created_at"}, "-created_at"), "-id")
        return paginate(request, qs, _row)


class StatusDetail(BOView):
    """Contenu d'un statut signalé et ses signalements. Consulter un contenu privé est un accès sensible : une trace par consultation."""
    bo_permission = "reviews.moderate"

    def get(self, request, pk):
        s = Status.objects.select_related("author").filter(pk=pk, reports__isnull=False).distinct().first()
        if s is None:
            return bad_request("not_found", "Statut signalé introuvable.", 404)
        audit_op(request, "status.viewed", s)
        content = s.deleted_at is None and s.media_purged_at is None
        return Response({
            "id": s.pk, "kind": s.kind, "type": s.type, "state": _state(s), "audience": s.audience, "created_at": s.created_at, "expires_at": s.expires_at,
            "author": {"id": s.author_id, "name": public_name(s.author), "active": s.author.is_active},
            "text": s.text,
            "media": ({"url": messaging.media_url(s.media, request), "mime": s.media_mime, **(s.media_meta or {})} if s.media and content else None),
            "reports": [{"id": r.pk, "reporter": public_name(r.reporter), "reason": r.reason, "created_at": r.created_at, "resolved": r.is_resolved}
                        for r in s.reports.select_related("reporter").order_by("-created_at")],
        })


class StatusRemove(BOView):
    bo_permission = "reviews.moderate"

    @transaction.atomic
    def post(self, request, pk):
        status = Status.objects.select_for_update(of=("self",)).select_related("author").filter(pk=pk).first()
        errors: dict = {}
        reason = _reason(request, errors)
        if status is None:
            return bad_request("not_found", "Statut introuvable.", 404)
        if errors:
            return Response({"code": "invalid", "detail": "Formulaire invalide.", "fields": errors}, status=400)
        if status.deleted_at is not None:
            StatusReport.objects.filter(status=status).update(is_resolved=True)
            return bad_request("already", "Ce statut est déjà retiré ou supprimé.", 409)
        services.remove_by_staff(status)
        StatusReport.objects.filter(status=status).update(is_resolved=True)
        audit_op(request, "status.removed", status, reason=reason)
        notifications.notify(status.author_id, "system", "Un de vos statuts a été retiré par l'équipe Tratra car il ne respecte pas les règles d'utilisation.",
                             title="Statut retiré", data={"kind": "notifications"}, dedupe_key=f"status:{status.pk}:removed")
        return Response({"removed": True})


class StatusReportDismiss(BOView):
    bo_permission = "reviews.moderate"

    @transaction.atomic
    def post(self, request, pk):
        report = StatusReport.objects.select_for_update(of=("self",)).select_related("status").filter(pk=pk).first()
        errors: dict = {}
        reason = _reason(request, errors)
        if report is None:
            return bad_request("not_found", "Signalement introuvable.", 404)
        if errors:
            return Response({"code": "invalid", "detail": "Formulaire invalide.", "fields": errors}, status=400)
        if report.is_resolved:
            return bad_request("already", "Ce signalement est déjà traité.", 409)
        report.is_resolved = True
        report.save(update_fields=["is_resolved"])
        audit_op(request, "status.report_dismissed", report.status, reason=reason, report=report.pk)
        return Response({"resolved": True})
