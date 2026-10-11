"""Modules « pilotage » du Back-Office : Notifications, Continuité, Statistiques et exports, Réglages, Sécurité.

 - Réglages : chaque modification est validée (bornes), journalisée avec l'ancienne et la nouvelle valeur ; le statut des
   intégrations ne renvoie QUE des booléens et des noms de fournisseur — jamais une clé, un jeton ou un identifiant ;
 - Sécurité : aucun jeton de session dans les réponses (identifiants et empreintes seulement), pas d'auto-modification de rôle,
   toujours au moins un super administrateur actif ;
 - Exports : droit par jeu de données, plafond de lignes, cellules neutralisées contre l'injection de formules, journalisés."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.response import Response

from backoffice import mfa, rbac, services
from backoffice.common import (
    BOView, apply_range, audit_op, bad_request, csv_response, day_bounds, last_days, email_for, money, ordering, paginate, public_name,
)
from continuity.models import IdempotencyRecord
from handy import push, sms
from handy.models import (
    Booking, CancellationPolicy, Coupon, Device, Dispute, Notification, OTPCode, Payment, Payout, PricingRule, Review, ServiceCategory, User,
)
from trust.models import AuditEvent, TrustConfig

MIN_REASON = 5
EXPORT_MAX_ROWS = 50_000


def _reason(request) -> str:
    value = str(request.data.get("reason") or "").strip()
    if len(value) < MIN_REASON:
        raise ValidationError(f"Un motif d'au moins {MIN_REASON} caractères est obligatoire.", code="reason_required")
    return value[:500]


def _form_errors(errors: dict) -> Response:
    return Response({"code": "invalid", "detail": "Formulaire invalide.", "fields": errors}, status=400)


# ═══ Notifications ══════════════════════════════════════════════════════════════════════════════════════════════════

def _sms_status() -> dict:
    name = sms.backend_name() or None
    try:
        sms.get_backend()
        ready = True
    except Exception:    # noqa: BLE001 - fournisseur absent, mal configuré ou réservé au développement
        ready = False
    return {"provider": name, "ready": ready}


def integrations_status() -> dict:
    """État des intégrations : booléens et NOMS seulement. Aucune clé, aucun jeton, aucun identifiant de projet."""
    from django.conf import settings

    return {
        "push_fcm": {"configured": push.is_configured()},
        "sms": _sms_status(),
        "email": {"backend": settings.EMAIL_BACKEND.rsplit(".", 2)[-2] if "." in settings.EMAIL_BACKEND else settings.EMAIL_BACKEND,
                  "real_delivery": "console" not in settings.EMAIL_BACKEND and "locmem" not in settings.EMAIL_BACKEND},
        # Disponible = tous les identifiants du prestataire sont configurés (jamais leur valeur) ; « espèces » est manuel.
        "payments": {m: _provider_available(m) for m in ("om", "mtn", "card", "cash")},
        "routing_osrm": {"configured": bool(getattr(settings, "ROUTING_OSRM_URL", ""))},
        "object_storage": {"enabled": bool(getattr(settings, "MINIO_ENABLED", False))},
    }


def _provider_available(method: str) -> bool:
    from handy.services.gateway import provider_for_method

    try:
        return bool(provider_for_method(method).is_available)
    except Exception:    # noqa: BLE001
        return False


class NotificationSummary(BOView):
    bo_permission = "notifications.view"

    def get(self, request):
        hours = int(request.query_params["hours"]) if (request.query_params.get("hours") or "").isdigit() else 24
        hours = max(1, min(hours, 720))
        now = timezone.now()
        since = now - timedelta(hours=hours)
        window = Notification.objects.filter(created_at__gte=since)
        by_status = {(k or "none"): n for k, n in window.values_list("push_status").annotate(n=Count("id"))}
        otp = OTPCode.objects.filter(created_at__gte=since)
        return Response({
            "window_hours": hours, "notifications": window.count(),
            "push": {"by_status": by_status, "failed": by_status.get("failed", 0), "sent": by_status.get("sent", 0),
                     # « en file » depuis plus de 15 min = un worker ne consomme plus la file : à traiter.
                     "queued_stuck": Notification.objects.filter(push_status="queued", created_at__lt=now - timedelta(minutes=15)).count()},
            "by_category": dict(window.values_list("category").annotate(n=Count("id"))),
            "devices": {"total": Device.objects.count(), "by_platform": dict(Device.objects.values_list("device_type").annotate(n=Count("id"))),
                        "active_7d": Device.objects.filter(last_active__gte=now - timedelta(days=7)).count()},
            # SMS : seuls des COMPTES de codes demandés / utilisés ; jamais un code ni un numéro.
            "otp": {"requested": otp.count(), "used": otp.filter(used=True).count(), "by_purpose": dict(otp.values_list("purpose").annotate(n=Count("id")))},
            "integrations": {k: v for k, v in integrations_status().items() if k in ("push_fcm", "sms", "email")},
        })


def _notification_row(n: Notification) -> dict:
    # Titre et type seulement : le corps d'un message peut contenir des détails de réservation ou de paiement.
    return {"id": n.pk, "user_id": n.user_id, "user": public_name(n.user), "type": n.notification_type, "category": n.category, "title": n.title or None,
            "push_status": n.push_status or None, "push_sent_at": n.push_sent_at, "is_read": n.is_read, "created_at": n.created_at}


class NotificationList(BOView):
    bo_permission = "notifications.view"

    def get(self, request):
        p = request.query_params
        qs = Notification.objects.select_related("user")
        if p.get("push_status") in dict(Notification.PUSH_STATUSES):
            qs = qs.filter(push_status=p["push_status"])
        if p.get("category") in dict(Notification.CATEGORIES):
            qs = qs.filter(category=p["category"])
        if (p.get("user") or "").isdigit():
            qs = qs.filter(user_id=int(p["user"]))
        q = (p.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(notification_type__icontains=q))
        return paginate(request, apply_range(request, qs, "created_at").order_by("-created_at", "-id"), _notification_row)


# ═══ Continuité ═════════════════════════════════════════════════════════════════════════════════════════════════════

STUCK_RULES = {
    "pending_old": ("En attente depuis plus de 24 h", lambda now: Q(status="pending", created_at__lt=now - timedelta(hours=24))),
    "confirmed_late": ("Confirmée, l'heure est passée depuis plus de 6 h sans démarrage", lambda now: Q(status="confirmed", booking_date__lt=now - timedelta(hours=6))),
    "in_progress_long": ("En cours depuis plus de 24 h", lambda now: Q(status="in_progress", booking_date__lt=now - timedelta(hours=24))),
}


class ContinuityOverview(BOView):
    """Activités en cours et signaux de synchronisation. Lecture seule : l'administration ne force jamais une activité."""
    bo_permission = "continuity.view"

    def get(self, request):
        now = timezone.now()
        active = dict(Booking.objects.filter(status__in=("pending", "confirmed", "in_progress")).values_list("status").annotate(n=Count("id")))
        day = now - timedelta(hours=24)
        return Response({
            "active": {s: active.get(s, 0) for s in ("pending", "confirmed", "in_progress")},
            "stuck": {key: Booking.objects.filter(rule(now)).count() for key, (_, rule) in STUCK_RULES.items()},
            "stuck_labels": {key: label for key, (label, _) in STUCK_RULES.items()},
            # Écritures rejouables (double appui, reprise après coupure) menées à terme ces 24 h, par type d'opération.
            "idempotent_writes_24h": {"total": IdempotencyRecord.objects.filter(created_at__gte=day).count(),
                                      "by_scope": {k.split(":")[0]: n for k, n in IdempotencyRecord.objects.filter(created_at__gte=day).values_list("scope").annotate(n=Count("id"))}},
            "sync": {"push_failed_24h": Notification.objects.filter(push_status="failed", created_at__gte=day).count(),
                     "push_queued_stuck": Notification.objects.filter(push_status="queued", created_at__lt=now - timedelta(minutes=15)).count(),
                     "payouts_failed": Payout.objects.filter(status="failed").count()},
            "devices": {"total": Device.objects.count(), "active_7d": Device.objects.filter(last_active__gte=now - timedelta(days=7)).count()},
        })


class ContinuityStuck(BOView):
    bo_permission = "continuity.view"

    def get(self, request):
        now = timezone.now()
        kind = request.query_params.get("kind")
        rules = [STUCK_RULES[kind]] if kind in STUCK_RULES else list(STUCK_RULES.values())
        cond = Q()
        for _, rule in rules:
            cond |= rule(now)
        qs = Booking.objects.filter(cond).select_related("client", "handyman", "service").order_by("booking_date", "id")

        def row(b):
            reason = next((label for label, rule in STUCK_RULES.values() if Booking.objects.filter(rule(now), pk=b.pk).exists()), "")
            return {"id": b.pk, "status": b.status, "reason": reason, "service": b.service.title if b.service_id else None, "client": public_name(b.client),
                    "artisan": public_name(b.handyman), "booking_date": b.booking_date, "created_at": b.created_at, "version": b.version,
                    "age_hours": int((now - (b.booking_date if b.status != "pending" else b.created_at)).total_seconds() // 3600)}
        return paginate(request, qs, row)


# ═══ Statistiques et exports ════════════════════════════════════════════════════════════════════════════════════════

def _range(request, default_days: int = 30):
    start = day_bounds(request.query_params.get("from")) or last_days(default_days)
    stop = day_bounds(request.query_params.get("to"), end=True) or timezone.now()
    return start, stop


def _daily(qs, field: str, start, stop):
    rows = {r["d"]: r["n"] for r in qs.filter(**{f"{field}__gte": start, f"{field}__lte": stop}).annotate(d=TruncDate(field)).values("d").annotate(n=Count("id"))}
    days = (stop.date() - start.date()).days + 1
    return [{"date": (start.date() + timedelta(days=i)).isoformat(), "count": rows.get(start.date() + timedelta(days=i), 0)} for i in range(min(days, 366))]


class AnalyticsOverview(BOView):
    """Statistiques AGRÉGÉES : aucune donnée personnelle. Les montants exigent `finance.view`."""
    bo_permission = "analytics.view"

    def get(self, request):
        start, stop = _range(request)
        perms = rbac.user_permissions(request.user)
        bookings = Booking.objects.filter(created_at__gte=start, created_at__lte=stop)
        total = bookings.count()
        by_status = dict(bookings.values_list("status").annotate(n=Count("id")))
        rate = lambda n: round(n / total, 4) if total else None    # noqa: E731
        reviews = Review.objects.filter(created_at__gte=start, created_at__lte=stop, is_hidden=False)
        disputes = Dispute.objects.filter(created_at__gte=start, created_at__lte=stop).count()
        out = {
            "range": {"from": start.date().isoformat(), "to": stop.date().isoformat()},
            "signups": _daily(User.objects.filter(is_staff=False), "date_joined", start, stop),
            "bookings": {"total": total, "by_status": {s: by_status.get(s, 0) for s, _ in Booking.STATUS_CHOICES}, "daily": _daily(Booking.objects, "created_at", start, stop),
                         "completion_rate": rate(by_status.get("completed", 0)), "cancellation_rate": rate(by_status.get("cancelled", 0)),
                         "dispute_rate": rate(disputes)},
            "top_categories": [{"name": n or "Sans catégorie", "bookings": c} for n, c in
                               bookings.values_list("service__category__name").annotate(c=Count("id")).order_by("-c")[:8]],
            "top_cities": [{"name": n or "Non renseignée", "bookings": c} for n, c in bookings.values_list("city").annotate(c=Count("id")).order_by("-c")[:8]],
            "active_artisans": Booking.objects.filter(status="completed", updated_at__gte=start, updated_at__lte=stop).values("handyman").distinct().count(),
            "reviews": {"count": reviews.count(), "average": round(reviews.aggregate(a=Avg("rating"))["a"], 2) if reviews.exists() else None},
        }
        if "finance.view" in perms:
            paid = Payment.objects.filter(status__in=Payment.PAID_STATUSES, created_at__gte=start, created_at__lte=stop)
            agg = paid.aggregate(gmv=Sum("amount"), fee=Sum("platform_fee"), avg=Avg("amount"))
            out["finance"] = {"currency": "XOF", "gmv": money(agg["gmv"]), "commission": money(agg["fee"]), "average_basket": money(agg["avg"]),
                              "paid_share": round(paid.count() / total, 4) if total else None}
        return Response(out)


def _users_rows(request, perms):
    qs = apply_range(request, User.objects.filter(is_staff=False).select_related("handyman_profile"), "date_joined").order_by("id")[:EXPORT_MAX_ROWS]
    header = ["id", "inscrit_le", "ville", "actif", "telephone_verifie", "artisan", "artisan_approuve"]
    return header, ([u.pk, u.date_joined.date(), u.city or "", int(u.is_active), int(u.is_verified), int(hasattr(u, "handyman_profile")),
                     int(bool(getattr(getattr(u, "handyman_profile", None), "is_approved", False)))] for u in qs)


def _bookings_rows(request, perms):
    qs = apply_range(request, Booking.objects.select_related("service__category", "payment"), "created_at").order_by("id")[:EXPORT_MAX_ROWS]
    money_cols = "finance.view" in perms
    header = ["id", "cree_le", "date_prevue", "statut", "ville", "service", "categorie", "statut_paiement"] + (["montant", "commission"] if money_cols else [])

    def rows():
        for b in qs:
            payment = getattr(b, "payment", None)
            base = [b.pk, b.created_at.date(), b.booking_date.date() if b.booking_date else "", b.status, b.city or "", b.service.title if b.service_id else "",
                    b.service.category.name if b.service_id and b.service.category_id else "", payment.status if payment else ""]
            yield base + ([money(payment.amount), money(payment.platform_fee)] if money_cols and payment else (["", ""] if money_cols else []))
    return header, rows()


def _payments_rows(request, perms):
    qs = apply_range(request, Payment.objects.all(), "created_at").order_by("id")[:EXPORT_MAX_ROWS]
    header = ["id", "reservation", "cree_le", "montant", "commission", "net", "moyen", "statut", "rembourse"]
    return header, ([p.pk, p.booking_id, p.created_at.date(), money(p.amount), money(p.platform_fee), money(p.amount - p.platform_fee), p.method, p.status,
                     money(p.refunded_amount)] for p in qs)       # jamais la référence du fournisseur


def _reviews_rows(request, perms):
    qs = apply_range(request, Review.objects.all(), "created_at").order_by("id")[:EXPORT_MAX_ROWS]
    return ["id", "reservation", "note", "masque", "cree_le"], ([r.pk, r.booking_id, r.rating, int(r.is_hidden), r.created_at.date()] for r in qs)     # aucun commentaire


def _audit_rows(request, perms):
    qs = apply_range(request, AuditEvent.objects.select_related("actor"), "created_at").order_by("id")[:EXPORT_MAX_ROWS]
    return ["id", "date", "auteur", "action", "cible", "cible_id"], ([e.pk, e.created_at.isoformat(timespec="seconds"), public_name(e.actor) if e.actor_id else "Système",
                                                                    e.action, e.target_type, e.target_id or ""] for e in qs)


def _engagement_contract_rows(request, perms):
    from engagements.models import EngagementContract

    qs = apply_range(request, EngagementContract.objects.select_related("category"), "created_at").order_by("id")[:EXPORT_MAX_ROWS]
    header = ["id", "cree_le", "statut", "type", "relation", "categorie", "debut", "fin", "periodicite", "montant", "renouvellements"]
    return header, ([c.pk, c.created_at.date(), c.status, c.mission_type, c.work_relationship, c.category.name, c.start_date, c.end_date or "", c.period, money(c.amount),
                     c.renewal_count] for c in qs)       # aucun nom, contact ni adresse


def _engagement_installment_rows(request, perms):
    from engagements.models import ContractInstallment
    from engagements.services import installments as inst_svc

    qs = apply_range(request, ContractInstallment.objects.all(), "created_at").order_by("id")[:EXPORT_MAX_ROWS]
    header = ["id", "contrat", "numero", "debut", "fin", "echeance", "statut", "total", "confirme", "solde", "commission", "statut_commission"]

    def rows():
        for i in qs:
            t = inst_svc.totals(i)
            yield [i.pk, i.contract_id, i.sequence + 1, i.period_start, i.period_end, i.due_date, i.status, money(t["total"]), money(t["confirmed"]), money(t["balance"]),
                   money(i.platform_fee), i.platform_fee_status]
    return header, rows()


# jeu de données → (droit supplémentaire exigé, constructeur de lignes)
EXPORTS = {"users": ("users.view", _users_rows), "bookings": ("bookings.view", _bookings_rows), "payments": ("finance.view", _payments_rows),
           "reviews": ("reviews.moderate", _reviews_rows), "audit": ("security.manage", _audit_rows),
           "engagements": ("engagements.view", _engagement_contract_rows), "engagement_installments": ("engagements.view", _engagement_installment_rows)}


class AnalyticsExport(BOView):
    bo_permission = "analytics.view"

    def get(self, request, dataset):
        spec = EXPORTS.get(dataset)
        if spec is None:
            return bad_request("unknown_dataset", "Jeu de données inconnu.", 404)
        required, build = spec
        perms = rbac.user_permissions(request.user)
        if required not in perms:
            return bad_request("forbidden_dataset", f"Ce jeu de données exige le droit « {required} ».", 403)
        header, rows = build(request, perms)
        rows = list(rows)
        audit_op(request, "export.downloaded", target_type="export", target_id=None, dataset=dataset, rows=len(rows),
                 range=[request.query_params.get("from") or "", request.query_params.get("to") or ""])
        return csv_response(f"tratra-{dataset}-{timezone.localdate().isoformat()}.csv", header, rows)


# ═══ Réglages ═══════════════════════════════════════════════════════════════════════════════════════════════════════

def _dec(raw, lo, hi, errors, key, *, places: int = 2):
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        errors[key] = "Nombre invalide."
        return None
    if not (lo <= value <= hi):
        errors[key] = f"Valeur attendue entre {lo} et {hi}."
        return None
    return value.quantize(Decimal(1).scaleb(-places))


def _int(raw, lo, hi, errors, key):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        errors[key] = "Nombre entier invalide."
        return None
    if not (lo <= value <= hi):
        errors[key] = f"Valeur attendue entre {lo} et {hi}."
        return None
    return value


def _rule_row(r: PricingRule) -> dict:
    return {"id": r.pk, "category": r.category_id, "category_name": r.category.name if r.category_id else None, "fee_percent": str(r.fee_percent),
            "fee_min_xof": r.fee_min_xof, "active": r.active}


def _policy_row(p: CancellationPolicy) -> dict:
    return {"id": p.pk, "name": p.name, "free_until_minutes": p.free_until_minutes, "fee_percent": str(p.fee_percent), "active": p.active}


def _coupon_row(c: Coupon) -> dict:
    return {"id": c.pk, "code": c.code, "percent_off": str(c.percent_off) if c.percent_off is not None else None,
            "amount_off": str(c.amount_off) if c.amount_off is not None else None, "valid_from": c.valid_from, "valid_to": c.valid_to,
            "active": c.active, "valid_now": c.is_valid(), "used": c.payments.count()}


TRUST_BOUNDS = {name: (0, 100) for name in ("weight_identity", "weight_satisfaction", "weight_reliability", "weight_reactivity", "weight_track_record", "weight_certifications")}
TRUST_BOUNDS.update({"expert_min_certifications": (0, 20), "expert_min_completed": (0, 1000), "expert_min_reviews": (0, 1000), "expert_min_experience_years": (0, 60),
                     "sure_min_completed": (0, 1000), "sure_min_punctuality_sample": (0, 1000), "sure_min_reviews": (0, 1000), "sure_window_days": (7, 1095),
                     "punctuality_tolerance_minutes": (0, 240), "min_sample": (1, 100), "reevaluation_hours": (1, 168)})
TRUST_RATIOS = {"sure_min_punctuality": (0, 1), "sure_max_dispute_rate": (0, 1)}
TRUST_RATINGS = {"expert_min_rating": (1, 5), "sure_min_rating": (1, 5)}


def _trust_dict(c: TrustConfig) -> dict:
    return {f.name: getattr(c, f.name) for f in c._meta.concrete_fields if f.name not in ("id", "updated_at")}


class SettingsOverview(BOView):
    bo_permission = "settings.manage"

    def get(self, request):
        return Response({
            "pricing_rules": [_rule_row(r) for r in PricingRule.objects.select_related("category").order_by("id")],
            "cancellation_policies": [_policy_row(p) for p in CancellationPolicy.objects.order_by("id")],
            "trust": _trust_dict(TrustConfig.get_solo()),
            "trust_labels": {f.name: str(f.verbose_name) for f in TrustConfig._meta.concrete_fields if f.name not in ("id", "updated_at")},
            "coupons": [_coupon_row(c) for c in Coupon.objects.order_by("-valid_to", "-id")[:50]],
            "integrations": integrations_status(),
        })


def _audit_changes(request, action, target, changes: dict):
    if changes:
        audit_op(request, action, target, changes={k: {"old": str(o), "new": str(n)} for k, (o, n) in changes.items()})


class PricingRuleCreate(BOView):
    bo_permission = "settings.manage"

    def post(self, request):
        errors = {}
        fee = _dec(request.data.get("fee_percent"), Decimal("0"), Decimal("50"), errors, "fee_percent")
        minimum = _int(request.data.get("fee_min_xof", 0), 0, 100000, errors, "fee_min_xof")
        category = None
        if request.data.get("category"):
            category = ServiceCategory.objects.filter(pk=request.data["category"]).first()
            if category is None:
                errors["category"] = "Catégorie inconnue."
        if category is None and not errors and PricingRule.objects.filter(category__isnull=True, active=True).exists() and request.data.get("active", True):
            errors["category"] = "Une règle générale est déjà active : désactivez-la ou choisissez une catégorie."
        if errors:
            return _form_errors(errors)
        rule = PricingRule.objects.create(category=category, fee_percent=fee, fee_min_xof=minimum, active=bool(request.data.get("active", True)))
        audit_op(request, "settings.pricing_rule_created", rule, fee_percent=str(fee), fee_min_xof=minimum, category=category.pk if category else None)
        return Response(_rule_row(rule), status=201)


class PricingRuleUpdate(BOView):
    bo_permission = "settings.manage"

    def patch(self, request, pk):
        rule = PricingRule.objects.select_related("category").filter(pk=pk).first()
        if rule is None:
            return bad_request("not_found", "Règle introuvable.", 404)
        errors, changes = {}, {}
        if "fee_percent" in request.data:
            v = _dec(request.data["fee_percent"], Decimal("0"), Decimal("50"), errors, "fee_percent")
            if v is not None and v != rule.fee_percent:
                changes["fee_percent"] = (rule.fee_percent, v)
        if "fee_min_xof" in request.data:
            v = _int(request.data["fee_min_xof"], 0, 100000, errors, "fee_min_xof")
            if v is not None and v != rule.fee_min_xof:
                changes["fee_min_xof"] = (rule.fee_min_xof, v)
        if "active" in request.data and bool(request.data["active"]) != rule.active:
            changes["active"] = (rule.active, bool(request.data["active"]))
        if errors:
            return _form_errors(errors)
        for k, (_, new) in changes.items():
            setattr(rule, k, new)
        if changes:
            rule.save()
            _audit_changes(request, "settings.pricing_rule_updated", rule, changes)
        return Response(_rule_row(rule))


class CancellationPolicyUpsert(BOView):
    """Au plus UNE politique active (la première active s'applique) : en activer une désactive les autres."""
    bo_permission = "settings.manage"

    @transaction.atomic
    def post(self, request, pk=None):
        policy = None
        if pk is not None:
            policy = CancellationPolicy.objects.filter(pk=pk).first()
            if policy is None:
                return bad_request("not_found", "Politique introuvable.", 404)
        errors, data = {}, request.data
        name = str(data.get("name", policy.name if policy else "")).strip()
        if not name or len(name) > 50:
            errors["name"] = "Nom requis (50 caractères maximum)."
        free = _int(data.get("free_until_minutes", policy.free_until_minutes if policy else 60), 0, 43200, errors, "free_until_minutes")
        fee = _dec(data.get("fee_percent", policy.fee_percent if policy else 0), Decimal("0"), Decimal("100"), errors, "fee_percent")
        active = bool(data.get("active", policy.active if policy else True))
        if errors:
            return _form_errors(errors)
        before = None if policy is None else {"free_until_minutes": policy.free_until_minutes, "fee_percent": policy.fee_percent, "active": policy.active}
        if policy is None:
            policy = CancellationPolicy.objects.create(name=name, free_until_minutes=free, fee_percent=fee, active=active)
        else:
            policy.name, policy.free_until_minutes, policy.fee_percent, policy.active = name, free, fee, active
            policy.save()
        if active:
            CancellationPolicy.objects.exclude(pk=policy.pk).filter(active=True).update(active=False)
        after = {"free_until_minutes": free, "fee_percent": fee, "active": active}
        audit_op(request, "settings.cancellation_policy_saved", policy, changes={k: {"old": str(before[k]) if before else None, "new": str(v)} for k, v in after.items()
                                                                              if before is None or before[k] != v})
        return Response(_policy_row(policy), status=200 if pk else 201)


class TrustSettingsUpdate(BOView):
    """Seuils et poids de Tratra Trust. Appliqués à la PROCHAINE réévaluation (périodique ou par événement) : aucun badge
    n'est retiré ni attribué à la volée par ce formulaire."""
    bo_permission = "settings.manage"

    def patch(self, request):
        cfg = TrustConfig.get_solo()
        errors, changes = {}, {}
        for key, raw in request.data.items():
            if key in TRUST_BOUNDS:
                v = _int(raw, *TRUST_BOUNDS[key], errors, key)
            elif key in TRUST_RATIOS:
                v = _dec(raw, Decimal(str(TRUST_RATIOS[key][0])), Decimal(str(TRUST_RATIOS[key][1])), errors, key, places=3)
                v = float(v) if v is not None else None
            elif key in TRUST_RATINGS:
                v = _dec(raw, Decimal(str(TRUST_RATINGS[key][0])), Decimal(str(TRUST_RATINGS[key][1])), errors, key, places=1)
                v = float(v) if v is not None else None
            else:
                errors[key] = "Réglage inconnu."
                continue
            if v is not None and v != getattr(cfg, key):
                changes[key] = (getattr(cfg, key), v)
        if errors:
            return _form_errors(errors)
        for k, (_, new) in changes.items():
            setattr(cfg, k, new)
        if changes:
            cfg.save()
            _audit_changes(request, "settings.trust_updated", cfg, changes)
        return Response({"trust": _trust_dict(cfg), "applied_by": f"prochaine réévaluation (au plus {cfg.reevaluation_hours} h)"})


class CouponList(BOView):
    bo_permission = "settings.manage"

    def post(self, request):
        d, errors = request.data, {}
        code = str(d.get("code") or "").strip().upper()
        if not (4 <= len(code) <= 30) or not code.replace("-", "").replace("_", "").isalnum():
            errors["code"] = "Code de 4 à 30 caractères (lettres, chiffres, - _)."
        elif Coupon.objects.filter(code=code).exists():
            errors["code"] = "Ce code existe déjà."
        percent = amount = None
        has_p, has_a = d.get("percent_off") not in (None, ""), d.get("amount_off") not in (None, "")
        if has_p == has_a:
            errors["percent_off"] = "Choisissez une réduction en pourcentage OU en montant."
        elif has_p:
            percent = _dec(d["percent_off"], Decimal("1"), Decimal("100"), errors, "percent_off")
        else:
            amount = _dec(d["amount_off"], Decimal("1"), Decimal("10000000"), errors, "amount_off")
        start, end = parse_datetime(str(d.get("valid_from") or "")), parse_datetime(str(d.get("valid_to") or ""))
        if start is None:
            errors["valid_from"] = "Date de début invalide."
        if end is None:
            errors["valid_to"] = "Date de fin invalide."
        elif start is not None and end <= start:
            errors["valid_to"] = "La fin doit suivre le début."
        if errors:
            return _form_errors(errors)
        coupon = Coupon.objects.create(code=code, percent_off=percent, amount_off=amount, valid_from=start, valid_to=end, active=bool(d.get("active", True)))
        audit_op(request, "settings.coupon_created", coupon, code=code)
        return Response(_coupon_row(coupon), status=201)


class CouponUpdate(BOView):
    bo_permission = "settings.manage"

    def patch(self, request, pk):
        coupon = Coupon.objects.filter(pk=pk).first()
        if coupon is None:
            return bad_request("not_found", "Code promotionnel introuvable.", 404)
        if "active" not in request.data:
            return _form_errors({"active": "Seule l'activation / désactivation d'un code est modifiable."})
        new = bool(request.data["active"])
        if new != coupon.active:
            audit_op(request, "settings.coupon_toggled", coupon, code=coupon.code, old=coupon.active, new=new)
            coupon.active = new
            coupon.save(update_fields=["active"])
        return Response(_coupon_row(coupon))


# ═══ Sécurité ═══════════════════════════════════════════════════════════════════════════════════════════════════════

def _staff_row(u: User, request) -> dict:
    return {"id": u.pk, "name": public_name(u), "email": email_for(request, u.email), "is_active": u.is_active, "is_superuser": u.is_superuser,
            "roles": sorted(rbac.user_roles(u)), "last_login": u.last_login, "date_joined": u.date_joined, "mfa_enrolled": mfa.confirmed_device(u) is not None}


def _super_admins():
    rbac.ensure_roles()
    return User.objects.filter(is_active=True, is_staff=True).filter(Q(is_superuser=True) | Q(groups__name=rbac.role_group_name("super_admin"))).distinct()


class RoleList(BOView):
    bo_permission = "security.manage"

    def get(self, request):
        rbac.ensure_roles()
        counts = {r: User.objects.filter(groups__name=rbac.role_group_name(r), is_staff=True).count() for r in rbac.ROLES}
        return Response({"roles": [{"id": r, "members": counts[r], "permissions": sorted(perms)} for r, perms in rbac.ROLES.items()],
                         "permissions": {code: label for code, label in rbac.PERMISSIONS.items()}})


class StaffList(BOView):
    bo_permission = "security.manage"

    def get(self, request):
        p = request.query_params
        qs = User.objects.filter(is_staff=True)
        q = (p.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q) | Q(username__icontains=q))
        if p.get("active") in ("true", "false"):
            qs = qs.filter(is_active=p["active"] == "true")
        role = p.get("role")
        if role == "super_admin":
            qs = qs.filter(is_superuser=True)
        elif role in rbac.ROLES:
            qs = qs.filter(groups__name=rbac.role_group_name(role)).distinct()
        if p.get("mfa") in ("enrolled", "missing"):  # contrôle de la double authentification : qui n'a pas encore activé son appareil ?
            from backoffice.models import StaffMFA
            enrolled = StaffMFA.objects.filter(confirmed_at__isnull=False).values("user_id")
            qs = qs.filter(pk__in=enrolled) if p["mfa"] == "enrolled" else qs.exclude(pk__in=enrolled)
        qs = qs.order_by("-is_superuser", "first_name", "id")
        return paginate(request, qs, lambda u: _staff_row(u, request))

    @transaction.atomic
    def post(self, request):
        """Donne un accès d'administration à un compte existant (actif, téléphone vérifié) avec au moins un rôle."""
        roles = request.data.get("roles") or []
        if not isinstance(roles, list) or not roles or any(r not in rbac.ROLES for r in roles):
            return _form_errors({"roles": "Choisissez au moins un rôle valide."})
        u = User.objects.filter(pk=request.data.get("user_id"), is_staff=False).first()
        if u is None:
            return _form_errors({"user_id": "Compte introuvable (ou déjà administrateur)."})
        if not u.is_active or not u.is_verified:
            return _form_errors({"user_id": "Le compte doit être actif et son téléphone vérifié."})
        rbac.ensure_roles()
        u.is_staff = True
        u.save(update_fields=["is_staff"])
        u.groups.add(*Group.objects.filter(name__in=[rbac.role_group_name(r) for r in roles]))
        audit_op(request, "security.staff_added", u, roles=sorted(roles))
        return Response(_staff_row(u, request), status=201)


class StaffRoles(BOView):
    bo_permission = "security.manage"

    @transaction.atomic
    def put(self, request, pk):
        u = User.objects.filter(pk=pk, is_staff=True).first()
        if u is None:
            return bad_request("not_found", "Compte d'administration introuvable.", 404)
        if u.pk == request.user.pk:
            return bad_request("self", "Vous ne pouvez pas modifier vos propres rôles.", 409)
        roles = request.data.get("roles")
        if not isinstance(roles, list) or not roles or any(r not in rbac.ROLES for r in roles):
            return _form_errors({"roles": "Choisissez au moins un rôle valide."})
        rbac.ensure_roles()
        before = sorted(rbac.user_roles(u))
        was_super = u in _super_admins()
        keep = u.groups.exclude(name__startswith=rbac.GROUP_PREFIX)
        u.groups.set(list(keep) + list(Group.objects.filter(name__in=[rbac.role_group_name(r) for r in roles])))
        if was_super and not u.is_superuser and "super_admin" not in roles and not _super_admins().exclude(pk=u.pk).exists():
            transaction.set_rollback(True)
            return bad_request("last_super_admin", "Il doit rester au moins un super administrateur actif.", 409)
        audit_op(request, "security.roles_changed", u, before=before, after=sorted(roles))
        return Response(_staff_row(u, request))


class StaffMfaReset(BOView):
    """Réinitialise la double authentification d'un compte d'administration (appareil perdu) : motif obligatoire, journalisé,
    jetons déjà vérifiés invalidés. Jamais sur soi-même (un autre super administrateur doit le faire)."""
    bo_permission = "security.manage"

    @transaction.atomic
    def post(self, request, pk):
        u = User.objects.filter(pk=pk, is_staff=True).first()
        if u is None:
            return bad_request("not_found", "Compte d'administration introuvable.", 404)
        if u.pk == request.user.pk:
            return bad_request("self", "Vous ne pouvez pas réinitialiser votre propre double authentification.", 409)
        try:
            reason = _reason(request)
        except ValidationError as exc:
            return bad_request(exc.code, exc.messages[0])
        had = mfa.reset(u, by=request.user, reason=reason)
        revoked = services.revoke_all_sessions(u)
        return Response({"id": u.pk, "mfa_enrolled": False, "had_device": had, "sessions_revoked": revoked})


class StaffRemove(BOView):
    """Retire l'accès d'administration (le compte utilisateur reste) et révoque ses sessions."""
    bo_permission = "security.manage"

    @transaction.atomic
    def post(self, request, pk):
        u = User.objects.filter(pk=pk, is_staff=True).first()
        if u is None:
            return bad_request("not_found", "Compte d'administration introuvable.", 404)
        if u.pk == request.user.pk:
            return bad_request("self", "Vous ne pouvez pas retirer votre propre accès.", 409)
        try:
            reason = _reason(request)
        except ValidationError as exc:
            return bad_request(exc.code, exc.messages[0])
        if u in _super_admins() and not _super_admins().exclude(pk=u.pk).exists():
            return bad_request("last_super_admin", "Il doit rester au moins un super administrateur actif.", 409)
        u.is_staff = False
        u.is_superuser = False
        u.save(update_fields=["is_staff", "is_superuser"])
        u.groups.remove(*u.groups.filter(name__startswith=rbac.GROUP_PREFIX))
        revoked = services.revoke_all_sessions(u)
        audit_op(request, "security.staff_removed", u, reason=reason, sessions_revoked=revoked)
        return Response({"id": u.pk, "is_staff": False, "sessions_revoked": revoked})


def _session_row(t, blacklisted_ids) -> dict:
    # Identifiants et empreinte courte seulement : JAMAIS le jeton lui-même.
    return {"id": t.pk, "user_id": t.user_id, "user": public_name(t.user) if t.user_id else "—", "is_staff": bool(t.user_id and t.user.is_staff),
            "created_at": t.created_at, "expires_at": t.expires_at, "fingerprint": f"…{t.jti[-6:]}", "revoked": t.pk in blacklisted_ids,
            "expired": t.expires_at is not None and t.expires_at <= timezone.now()}


class SessionList(BOView):
    bo_permission = "security.manage"

    def get(self, request):
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

        p = request.query_params
        qs = OutstandingToken.objects.select_related("user")
        if p.get("staff") == "true":
            qs = qs.filter(user__is_staff=True)
        if (p.get("user") or "").isdigit():
            qs = qs.filter(user_id=int(p["user"]))
        if p.get("active") == "true":
            qs = qs.filter(expires_at__gt=timezone.now()).exclude(pk__in=BlacklistedToken.objects.values("token_id"))
        black = set(BlacklistedToken.objects.values_list("token_id", flat=True))
        return paginate(request, qs.order_by("-created_at", "-id"), lambda t: _session_row(t, black))


class SessionRevoke(BOView):
    bo_permission = "security.manage"

    def post(self, request, pk):
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

        t = OutstandingToken.objects.select_related("user").filter(pk=pk).first()
        if t is None:
            return bad_request("not_found", "Session introuvable.", 404)
        _, created = BlacklistedToken.objects.get_or_create(token=t)
        audit_op(request, "security.session_revoked", t.user if t.user_id else None, session_id=t.pk, already=not created)
        return Response({"id": t.pk, "revoked": True})


class UserSessionsRevoke(BOView):
    """Déconnecte un compte de tous ses appareils (compte volé, départ d'un collaborateur)."""
    bo_permission = "security.manage"

    def post(self, request, pk):
        u = User.objects.filter(pk=pk).first()
        if u is None:
            return bad_request("not_found", "Compte introuvable.", 404)
        n = services.revoke_all_sessions(u)
        audit_op(request, "security.sessions_revoked", u, sessions_revoked=n)
        return Response({"id": u.pk, "sessions_revoked": n})


def _audit_row(e: AuditEvent) -> dict:
    return {"id": e.pk, "at": e.created_at, "actor_id": e.actor_id, "actor": public_name(e.actor) if e.actor_id else "Système", "action": e.action,
            "target_type": e.target_type, "target_id": e.target_id, "data": e.data or {}}


class AuditList(BOView):
    bo_permission = "security.manage"

    def get(self, request):
        p = request.query_params
        qs = AuditEvent.objects.select_related("actor")
        if (p.get("actor") or "").isdigit():
            qs = qs.filter(actor_id=int(p["actor"]))
        if p.get("action"):
            qs = qs.filter(action__startswith=p["action"][:80])
        if p.get("target_type"):
            qs = qs.filter(target_type=p["target_type"][:60])
        if (p.get("target_id") or "").isdigit():
            qs = qs.filter(target_id=int(p["target_id"]))
        if p.get("backoffice") == "true":
            qs = qs.filter(action__startswith="backoffice.")
        return paginate(request, apply_range(request, qs, "created_at").order_by("-created_at", "-id"), _audit_row, page_size=50)


class AuditActions(BOView):
    bo_permission = "security.manage"

    def get(self, request):
        return Response({"actions": list(AuditEvent.objects.order_by().values_list("action", flat=True).distinct()[:300])})
