"""Back-Office — Tratra Flash & Smart Dispatch : réglages (poids, délais, règles), historique des attributions (propositions, réponses,
délais, motifs d'exclusion), supervision des demandes sans réponse ; Tratra Trust : pénalités et contestations (décision humaine motivée).
Lecture : droit « bookings.view » ; réglages : « settings.manage » ; pénalités : « trust.manage ». Toute écriture est journalisée."""
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from rest_framework.response import Response

from backoffice.common import BOView, apply_range, audit_op, bad_request, paginate, public_name
from flash import insights
from flash.models import DispatchConfig, MissionOffer, MissionRequest
from handy.models import Booking, User
from trust import penalties
from trust.models import TrustPenalty

CONFIG_FIELDS = [f.name for f in DispatchConfig._meta.get_fields()
                 if getattr(f, "concrete", False) and f.name not in ("id", "updated_at", "updated_by")]


def _config_payload(c: DispatchConfig) -> dict:
    fields = []
    for name in CONFIG_FIELDS:
        f = DispatchConfig._meta.get_field(name)
        fields.append({"name": name, "label": str(f.verbose_name), "value": getattr(c, name), "type": "float" if f.get_internal_type() == "FloatField" else "int",
                       "group": "weights" if name.startswith("weight_") else "waves" if name in (
                           "wave_size", "max_waves", "offer_timeout_seconds", "scheduled_offer_timeout_seconds", "immediate_horizon_minutes",
                           "quote_window_hours", "max_quotes") else "rules"})
    return {"fields": fields, "updated_at": c.updated_at, "updated_by": public_name(c.updated_by) if c.updated_by_id else None}


class FlashConfigView(BOView):
    bo_permission = {"GET": "bookings.view", "PUT": "settings.manage"}

    def get(self, request):
        return Response(_config_payload(DispatchConfig.get_solo()))

    def put(self, request):
        c = DispatchConfig.get_solo()
        before = {n: getattr(c, n) for n in CONFIG_FIELDS}
        for name, value in (request.data or {}).items():
            if name not in CONFIG_FIELDS:
                continue
            try:
                setattr(c, name, float(value) if DispatchConfig._meta.get_field(name).get_internal_type() == "FloatField" else int(value))
            except (TypeError, ValueError):
                return bad_request("invalid", f"Valeur invalide pour « {DispatchConfig._meta.get_field(name).verbose_name} ».", 400)
        if sum(c.weights().values()) <= 0:
            return bad_request("invalid", "Au moins un poids du classement doit être positif.", 400)
        try:
            c.full_clean(exclude=["updated_by"])
        except ValidationError as exc:
            field, messages = next(iter(exc.message_dict.items()))
            return bad_request("invalid", f"{DispatchConfig._meta.get_field(field).verbose_name} : {messages[0]}", 400)
        c.updated_by = request.user
        c.save()
        changes = {n: [before[n], getattr(c, n)] for n in CONFIG_FIELDS if before[n] != getattr(c, n)}
        audit_op(request, "flash.config_updated", c, changes=changes)
        return Response(_config_payload(c))


def _request_row(r: MissionRequest) -> dict:
    return {"id": r.pk, "status": r.status, "status_label": r.get_status_display(), "mode": r.mode, "category": r.category.name,
            "commune": r.commune, "immediate": r.is_immediate, "amount": int(r.amount) if r.amount is not None else None,
            "client": public_name(r.client), "client_id": r.client_id, "created_at": r.created_at, "scheduled_for": r.scheduled_for,
            "wave": r.wave, "contacted": getattr(r, "n_offers", None), "assigned_to": public_name(r.assigned_to) if r.assigned_to_id else None,
            "assigned_at": r.assigned_at, "seconds_to_assign": int((r.assigned_at - r.created_at).total_seconds()) if r.assigned_at else None,
            "booking": r.booking_id, "close_reason": r.close_reason,
            "matching": r.matching, "matching_label": r.get_matching_display(), "switches": r.switches,
            "target": public_name(r.target) if r.target_id else None}


class FlashRequestList(BOView):
    bo_permission = "bookings.view"

    def get(self, request):
        p = request.query_params
        qs = MissionRequest.objects.select_related("category", "client", "assigned_to", "target").annotate(n_offers=Count("offers"))
        if p.get("matching") in dict(MissionRequest.MATCHINGS):
            qs = qs.filter(matching=p["matching"])
        if p.get("status") == "open":
            qs = qs.filter(status__in=MissionRequest.OPEN)
        elif p.get("status") in dict(MissionRequest.STATUSES):
            qs = qs.filter(status=p["status"])
        q = (p.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(category__name__icontains=q) | Q(commune__icontains=q) | Q(client__first_name__icontains=q)
                           | Q(client__last_name__icontains=q) | Q(assigned_to__first_name__icontains=q))
        qs = apply_range(request, qs, "created_at").order_by("-created_at", "-id")
        return paginate(request, qs, _request_row)


class FlashRequestDetail(BOView):
    bo_permission = "bookings.view"

    def get(self, request, pk):
        r = MissionRequest.objects.select_related("category", "client", "assigned_to", "target").filter(pk=pk).first()
        if r is None:
            return bad_request("not_found", "Demande introuvable.", 404)
        offers = [{"id": o.pk, "pro": public_name(o.handyman), "pro_id": o.handyman_id, "wave": o.wave, "rank": o.rank, "score": o.score,
                   "criteria": o.score_detail.get("criteria", []), "distance_km": o.distance_km, "status": o.status, "status_label": o.get_status_display(),
                   "sent_at": o.sent_at, "expires_at": o.expires_at, "seen_at": o.seen_at, "responded_at": o.responded_at,
                   "response_seconds": o.response_seconds, "decline_reason": o.get_decline_reason_display() if o.decline_reason else "",
                   "quote_amount": int(o.quote_amount) if o.quote_amount is not None else None, "push_status": o.push_status,
                   "targeted": o.targeted}
                  for o in r.offers.select_related("handyman").order_by("wave", "rank")]
        events = [{"kind": e.kind, "label": e.get_kind_display(), "at": e.at, "actor": public_name(e.actor) if e.actor_id else None, "data": e.data}
                  for e in r.events.select_related("actor")]
        return Response({**_request_row(r), "description": r.description, "offers": offers, "events": events})


class FlashSupervision(BOView):
    bo_permission = "bookings.view"

    def get(self, request):
        try:
            days = max(1, min(int(request.query_params.get("days", 7)), 90))
        except ValueError:
            days = 7
        data = insights.overview(days)
        waiting = (MissionRequest.objects.filter(status__in=MissionRequest.OPEN).select_related("category", "client", "assigned_to", "target")
                   .annotate(n_offers=Count("offers")).order_by("created_at")[:30])
        data["open_requests"] = [_request_row(r) for r in waiting]
        data["recent_unfulfilled"] = [_request_row(r) for r in MissionRequest.objects.filter(status=MissionRequest.UNFULFILLED)
                                      .select_related("category", "client", "assigned_to", "target").annotate(n_offers=Count("offers"))
                                      .order_by("-closed_at")[:20]]
        return Response(data)


# ═══ Tratra Trust : pénalités et contestations ═════════════════════════════════════════════════════════════════════════

def _penalty_row(p: TrustPenalty) -> dict:
    return {**penalties.payload(p), "user": public_name(p.user), "user_id": p.user_id,
            "created_by": public_name(p.created_by) if p.created_by_id else "Constat automatique",
            "decided_by": public_name(p.decided_by) if p.decided_by_id else None}


class PenaltyList(BOView):
    bo_permission = "trust.manage"

    def get(self, request):
        qs = TrustPenalty.objects.select_related("user", "created_by", "decided_by")
        st = request.query_params.get("status")
        if st in dict(TrustPenalty.STATUSES):
            qs = qs.filter(status=st)
        return paginate(request, qs.order_by("-contested_at", "-created_at"), _penalty_row)

    def post(self, request):
        """Constat de l'équipe (absence, manquement) sur UNE mission du professionnel, expliqué et étayé."""
        user = User.objects.filter(pk=request.data.get("user")).first()
        booking = Booking.objects.filter(pk=request.data.get("booking")).first()
        if user is None:
            return bad_request("not_found", "Professionnel introuvable.", 404)
        try:
            p = penalties.record_by_staff(user=user, kind=str(request.data.get("kind") or ""), booking=booking,
                                          explanation=str(request.data.get("explanation") or ""),
                                          evidence={"note": str(request.data.get("evidence") or "")[:500]}, staff=request.user)
        except penalties.PenaltyError as e:
            return bad_request(e.code, e.message, e.status)
        audit_op(request, "trust.penalty_created", p, user=user.pk, kind=p.kind, booking=booking.pk if booking else None)
        return Response(_penalty_row(p), status=201)


class PenaltyDecide(BOView):
    bo_permission = "trust.manage"

    def post(self, request, pk):
        decision = str(request.data.get("decision") or "")
        if decision not in ("cancel", "uphold"):
            return bad_request("invalid", "Décision attendue : « cancel » (contestation retenue) ou « uphold » (pénalité maintenue).", 400)
        try:
            p = penalties.decide(pk, request.user, uphold_contest=decision == "cancel", note=str(request.data.get("note") or ""))
        except penalties.PenaltyError as e:
            return bad_request(e.code, e.message, e.status)
        audit_op(request, f"trust.penalty_{decision}", p, user=p.user_id)
        return Response(_penalty_row(p))
