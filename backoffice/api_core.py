"""Socle du Back-Office : identité et droits de l'utilisateur connecté, tableau de bord (indicateurs réels)."""
from datetime import timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from backoffice import rbac
from backoffice.common import BOView, last_days, money, public_name
from backoffice.modules import modules_for
from business.models import InterventionRequest
from handy.models import (
    Booking, Dispute, HandymanDocument, HandymanProfile, Notification, Payment, Payout, Report, Review, User,
)
from live.models import TrackingSession


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me(request):
    """Qui suis-je dans le Back-Office : rôles, droits et modules accessibles. 403 sans aucun rôle (jamais un menu vide)."""
    roles = sorted(rbac.user_roles(request.user))
    if not roles:
        return Response({"code": "not_backoffice_staff", "detail": "Ce compte n'a aucun rôle d'administration."}, status=403)
    return Response({
        "user": {"id": request.user.pk, "name": public_name(request.user), "is_superuser": request.user.is_superuser},
        "roles": roles,
        "permissions": sorted(rbac.user_permissions(request.user)),
        "modules": modules_for(request.user),
    })


def _series(qs, field: str, days: int):
    """Comptage par jour sur les `days` derniers jours, jours sans événement inclus (courbe sans trou)."""
    start = last_days(days)
    rows = {r["d"]: r["n"] for r in qs.filter(**{f"{field}__gte": start}).annotate(d=TruncDate(field)).values("d").annotate(n=Count("id"))}
    today = timezone.localtime().date()
    return [{"date": (today - timedelta(days=i)).isoformat(), "count": rows.get(today - timedelta(days=i), 0)} for i in range(days - 1, -1, -1)]


class DashboardView(BOView):
    """Indicateurs RÉELS, filtrés par droit : un rôle ne voit que les sections qu'il a le droit de consulter
    (les montants exigent `finance.view`, les comptes `users.view`…). Aucune donnée simulée : un indicateur indisponible est absent."""
    bo_permission = "dashboard.view"

    def get(self, request):
        perms = rbac.user_permissions(request.user)
        now = timezone.now()
        d7, d30 = now - timedelta(days=7), now - timedelta(days=30)
        out = {"generated_at": now, "kpis": {}, "series": {}, "alerts": []}

        if "users.view" in perms or "analytics.view" in perms:
            out["kpis"]["users"] = {
                "total": User.objects.filter(is_staff=False).count(),
                "new_7d": User.objects.filter(is_staff=False, date_joined__gte=d7).count(),
                "new_30d": User.objects.filter(is_staff=False, date_joined__gte=d30).count(),
                "artisans": HandymanProfile.objects.count(),
                "artisans_approved": HandymanProfile.objects.filter(is_approved=True).count(),
            }
            out["series"]["signups"] = _series(User.objects.filter(is_staff=False), "date_joined", 30)

        if "bookings.view" in perms or "analytics.view" in perms:
            by_status = dict(Booking.objects.values_list("status").annotate(n=Count("id")))
            out["kpis"]["bookings"] = {
                "total": sum(by_status.values()),
                "by_status": {s: by_status.get(s, 0) for s, _ in Booking.STATUS_CHOICES},
                "active": sum(by_status.get(s, 0) for s in ("pending", "confirmed", "in_progress")),
                "created_7d": Booking.objects.filter(created_at__gte=d7).count(),
                "completed_30d": Booking.objects.filter(status="completed", updated_at__gte=d30).count(),
            }
            out["series"]["bookings"] = _series(Booking.objects, "created_at", 30)

        if "finance.view" in perms:
            paid = Payment.objects.filter(status__in=Payment.PAID_STATUSES, created_at__gte=d30)
            agg = paid.aggregate(gmv=Sum("amount"), fee=Sum("platform_fee"))
            pending = Payout.objects.filter(status="pending").aggregate(n=Count("id"), total=Sum("amount"))
            out["kpis"]["finance"] = {
                "currency": "XOF",
                "gmv_30d": money(agg["gmv"]),
                "commission_30d": money(agg["fee"]),
                "refunded_30d": money(Payment.objects.filter(refunded_amount__gt=0, updated_at__gte=d30).aggregate(t=Sum("refunded_amount"))["t"]),
                "escrow_held": money(Payment.objects.filter(status="held").aggregate(t=Sum("amount"))["t"]),
                "payouts_pending": pending["n"] or 0,
                "payouts_pending_amount": money(pending["total"]),
            }

        if "live.view" in perms:
            out["kpis"]["live"] = {"sharing_sessions": TrackingSession.objects.filter(artisan_sharing=True).count()}   # aucun GPS ici

        # À traiter : chaque ligne renvoie au module concerné et n'apparaît que si le rôle peut agir dessus.
        def alert(key, label, count, href, severity="warning"):
            if count:
                out["alerts"].append({"key": key, "label": label, "count": count, "href": href, "severity": severity})

        if "kyc.review" in perms:
            alert("kyc_pending", "Pièces KYC à examiner", HandymanDocument.objects.filter(status="pending").count(), "/backoffice/kyc")
        if "bookings.manage" in perms or "support.manage" in perms:
            alert("disputes_open", "Litiges ouverts", Dispute.objects.filter(status__in=("open", "under_review")).count(), "/backoffice/bookings?tab=disputes", "danger")
        if "reviews.moderate" in perms:
            alert("reports_open", "Signalements non traités", Report.objects.filter(is_resolved=False).count(), "/backoffice/reviews")
        if "finance.manage" in perms:
            alert("payouts_pending", "Retraits en attente", Payout.objects.filter(status="pending").count(), "/backoffice/finance")
        if "business.manage" in perms:
            alert("business_pending", "Demandes Business en attente de validation", InterventionRequest.objects.filter(status="pending_approval").count(), "/backoffice/business", "info")
        if "notifications.view" in perms:
            alert("push_failed", "Notifications push en échec (24 h)", Notification.objects.filter(push_status="failed", created_at__gte=now - timedelta(hours=24)).count(), "/backoffice/notifications")
        return Response(out)
