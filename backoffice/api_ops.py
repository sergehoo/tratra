"""Modules opérationnels du Back-Office : Services, Réservations et litiges, Suivi en direct, Avis.

 - le Back-Office ne contourne jamais la machine à états ni l'escrow : annulations par `transition_to`, litiges par
   `Dispute.resolve` (les mouvements d'argent exigent en plus `finance.manage`) ;
 - GPS : AUCUNE coordonnée par défaut (état, consentements, ancienneté) ; l'accès à une position exige un motif, est limité
   à une mission active dont l'artisan partage, arrondi à ~100 m et journalisé ;
 - contenu des échanges privés : jamais exposé (seul le nombre de messages d'une réservation)."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone
from rest_framework.response import Response

from backoffice import rbac
from backoffice.common import BOView, apply_range, audit_op, bad_request, phone_for, ordering, paginate, public_name
from handy import eligibility
from handy.models import Booking, Dispute, Message, Notification, Payment, Report, Review, Service, ServiceCategory
from handy.notifications import notify
from live import services as live_services
from live.models import LivePosition, TrackingSession
from trust.models import AuditEvent, BookingPass, IdentityCheck

MIN_REASON = 5


def _reason(request, *, required: bool = True) -> str:
    reason = str(request.data.get("reason") or "").strip()
    if required and len(reason) < MIN_REASON:
        raise ValidationError(f"Un motif d'au moins {MIN_REASON} caractères est obligatoire.", code="reason_required")
    return reason[:500]


def _invalid(exc: ValidationError):
    conflict = exc.code in ("not_open", "already", "invalid_transition")
    return bad_request(exc.code or "invalid", exc.messages[0], 409 if conflict else 400)


def _history(target_type: str, target_id: int, limit: int = 15):
    rows = AuditEvent.objects.filter(target_type=target_type, target_id=target_id).select_related("actor")[:limit]
    return [{"action": e.action, "at": e.created_at, "by": public_name(e.actor) if e.actor_id else "Système",
             "reason": (e.data or {}).get("reason", "")} for e in rows]


# ═══ Services ═══════════════════════════════════════════════════════════════════════════════════════════════════════

def _service_row(s: Service) -> dict:
    return {"id": s.pk, "title": s.title, "category": s.category.name if s.category_id else None, "price_type": s.price_type,
            "price": str(s.price) if s.price is not None else None, "is_active": s.is_active,
            "artisan_id": s.handyman_id, "artisan": public_name(s.handyman), "created_at": s.created_at,
            "published": bool(s.is_active and eligibility.is_user_publishable(s.handyman)), "bookings": getattr(s, "n_bookings", 0)}


class ServiceList(BOView):
    bo_permission = "services.moderate"

    def get(self, request):
        p = request.query_params
        qs = Service.objects.select_related("category", "handyman").annotate(n_bookings=Count("bookings"))
        q = (p.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(handyman__first_name__icontains=q) | Q(handyman__last_name__icontains=q))
        if (p.get("category") or "").isdigit():
            qs = qs.filter(category_id=int(p["category"]))
        if p.get("active") in ("true", "false"):
            qs = qs.filter(is_active=p["active"] == "true")
        qs = apply_range(request, qs, "created_at").order_by(ordering(request, {"created_at": "created_at", "title": "title", "bookings": "n_bookings"}, "-created_at"), "-id")
        return paginate(request, qs, _service_row)


class ServiceDetail(BOView):
    bo_permission = "services.moderate"

    def get(self, request, pk):
        s = Service.objects.select_related("category", "handyman").annotate(n_bookings=Count("bookings")).filter(pk=pk).first()
        if s is None:
            return bad_request("not_found", "Service introuvable.", 404)
        row = _service_row(s)
        row.update({"description": s.description, "duration": s.duration, "images": s.images.count(), "history": _history("service", s.pk)})
        return Response(row)


class ServiceModeration(BOView):
    """Masquer / republier un service : modération de visibilité, jamais de réécriture du contenu de l'artisan."""
    bo_permission = "services.moderate"
    hide = True

    def post(self, request, pk):
        s = Service.objects.select_related("handyman").filter(pk=pk).first()
        if s is None:
            return bad_request("not_found", "Service introuvable.", 404)
        try:
            reason = _reason(request, required=self.hide)
            if s.is_active != self.hide:
                raise ValidationError("Ce service est déjà dans cet état.", code="already")
        except ValidationError as exc:
            return _invalid(exc)
        s.is_active = not self.hide
        s.save(update_fields=["is_active", "updated_at"])
        if self.hide:
            notify(s.handyman_id, "system", f"Votre service « {s.title} » a été masqué par l'équipe Tratra.", title="Service masqué",
                   data={"kind": "notifications"}, dedupe_key=f"service:{s.pk}:hidden:{int(timezone.now().timestamp())}")
        audit_op(request, "service.hidden" if self.hide else "service.restored", s, reason=reason)
        return Response(_service_row(s))


class ServiceHide(ServiceModeration):
    hide = True


class ServiceRestore(ServiceModeration):
    hide = False


def _category_row(c: ServiceCategory) -> dict:
    from handy import catalog

    key = catalog.icon_key(c.icon, c.slug)
    return {"id": c.pk, "name": c.name, "slug": c.slug, "description": c.description or "", "icon": c.icon or "", "icon_key": key, "icon_known": catalog.icon_known(key),
            "is_active": c.is_active, "parent": c.parent_id, "kind": catalog.kind_of(c.parent_id), "position": c.position, "is_featured": c.is_featured,
            "services": getattr(c, "n_services", 0), "artisans": getattr(c, "n_artisans", 0)}


def _position(raw):
    """Ordre d'affichage : entier de 0 à 9999 (None si invalide)."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 9999 else None


class CategoryList(BOView):
    """Catégories / métiers : liste (GET) et création (POST, droit `services.moderate`)."""
    bo_permission = "services.moderate"

    def get(self, request):
        qs = ServiceCategory.objects.annotate(n_services=Count("services", distinct=True), n_artisans=Count("handymen", distinct=True)).order_by("position", "name")
        return paginate(request, qs, _category_row, page_size=100)

    def post(self, request):
        data = request.data
        name, slug = str(data.get("name") or "").strip(), str(data.get("slug") or "").strip().lower()
        errors = {}
        if not name:
            errors["name"] = "Le nom est obligatoire."
        if not slug or not slug.replace("-", "").isalnum():
            errors["slug"] = "Identifiant requis (lettres, chiffres, tirets)."
        elif ServiceCategory.objects.filter(slug=slug).exists():
            errors["slug"] = "Cet identifiant existe déjà."
        parent = None
        if data.get("parent"):
            parent = ServiceCategory.objects.filter(pk=data["parent"]).first()
            if parent is None:
                errors["parent"] = "Catégorie parente inconnue."
        position = 100
        if "position" in data and data["position"] not in (None, ""):
            position = _position(data["position"])
            if position is None:
                errors["position"] = "L'ordre est un nombre entier de 0 à 9999."
        if errors:
            return Response({"code": "invalid", "detail": "Formulaire invalide.", "fields": errors}, status=400)
        c = ServiceCategory.objects.create(name=name[:100], slug=slug, description=str(data.get("description") or "")[:500] or None,
                                           icon=str(data.get("icon") or "")[:50] or None, parent=parent, position=position,
                                           is_featured=bool(data.get("is_featured")))
        audit_op(request, "category.created", c, name=c.name)
        return Response(_category_row(c), status=201)


class CategoryDetail(BOView):
    bo_permission = "services.moderate"

    def patch(self, request, pk):
        c = ServiceCategory.objects.filter(pk=pk).first()
        if c is None:
            return bad_request("not_found", "Catégorie introuvable.", 404)
        changed = {}
        for field, limit in (("name", 100), ("description", 500), ("icon", 50)):
            if field in request.data:
                value = str(request.data[field] or "").strip()[:limit]
                if field == "name" and not value:
                    return Response({"code": "invalid", "detail": "Formulaire invalide.", "fields": {"name": "Le nom est obligatoire."}}, status=400)
                setattr(c, field, value or None)
                changed[field] = value
        if "is_active" in request.data:
            c.is_active = bool(request.data["is_active"])
            changed["is_active"] = c.is_active
        if "is_featured" in request.data:
            c.is_featured = bool(request.data["is_featured"])
            changed["is_featured"] = c.is_featured
        if "position" in request.data:
            position = _position(request.data["position"])
            if position is None:
                return Response({"code": "invalid", "detail": "Formulaire invalide.", "fields": {"position": "L'ordre est un nombre entier de 0 à 9999."}}, status=400)
            c.position = position
            changed["position"] = position
        if changed:
            c.save()
            audit_op(request, "category.updated", c, **{k: str(v)[:80] for k, v in changed.items()})
        return Response(_category_row(c))


# ═══ Réservations et litiges ════════════════════════════════════════════════════════════════════════════════════════

def _booking_row(b: Booking) -> dict:
    payment = getattr(b, "payment", None)
    return {"id": b.pk, "status": b.status, "version": b.version, "service": b.service.title if b.service_id else None, "client": public_name(b.client),
            "client_id": b.client_id, "artisan": public_name(b.handyman), "artisan_id": b.handyman_id, "booking_date": b.booking_date, "city": b.city or None,
            "payment_status": payment.status if payment else None, "disputes": getattr(b, "n_disputes", 0), "created_at": b.created_at}


class BookingList(BOView):
    bo_permission = "bookings.view"

    def get(self, request):
        p = request.query_params
        qs = (Booking.objects.select_related("client", "handyman", "service", "payment").annotate(n_disputes=Count("disputes")))
        if p.get("status") in dict(Booking.STATUS_CHOICES):
            qs = qs.filter(status=p["status"])
        if p.get("active") == "true":
            qs = qs.filter(status__in=("pending", "confirmed", "in_progress"))
        if (p.get("user") or "").isdigit():  # toutes les réservations d'un compte, en tant que client OU artisan (fiche utilisateur)
            qs = qs.filter(Q(client_id=int(p["user"])) | Q(handyman_id=int(p["user"])))
        if (p.get("category") or "").isdigit():
            qs = qs.filter(service__category_id=int(p["category"]))
        if p.get("payment_status") in dict(Payment.PAYMENT_STATUS):
            qs = qs.filter(payment__status=p["payment_status"])
        if p.get("disputed") == "true":
            qs = qs.filter(n_disputes__gt=0)
        q = (p.get("q") or "").strip()
        if q:
            cond = (Q(client__first_name__icontains=q) | Q(client__last_name__icontains=q) | Q(handyman__first_name__icontains=q)
                    | Q(handyman__last_name__icontains=q) | Q(city__icontains=q) | Q(service__title__icontains=q))
            qs = qs.filter(cond | Q(pk=int(q))) if q.isdigit() else qs.filter(cond)
        qs = apply_range(request, qs, "booking_date").order_by(ordering(request, {"created_at": "created_at", "date": "booking_date", "status": "status"}, "-created_at"), "-id")
        return paginate(request, qs, _booking_row)


def _cash_summary(booking, user):
    """Règlement en espèces vu par le personnel : lecture seule (aucune action, aucun justificatif)."""
    from handy.services import cash as cash_svc
    summary = cash_svc.summary(booking, user)
    return summary if summary["history"] or summary["state"] != "none" else None


class BookingDetail(BOView):
    bo_permission = "bookings.view"

    def get(self, request, pk):
        b = Booking.objects.select_related("client", "handyman", "service").filter(pk=pk).first()
        if b is None:
            return bad_request("not_found", "Réservation introuvable.", 404)
        perms = rbac.user_permissions(request.user)
        row = _booking_row(b)
        payment = getattr(b, "payment", None)
        session = TrackingSession.objects.filter(booking=b).first()
        review = getattr(b, "review", None)
        row.update({
            "description": b.description,
            # L'adresse complète sert à la médiation : réservée aux rôles qui agissent (jamais finance / analyse).
            "address": b.address if "bookings.manage" in perms else None, "client_phone": phone_for(request, b.client.phone), "artisan_phone": phone_for(request, b.handyman.phone),
            "timeline": [{"status": t.status, "previous_status": t.previous_status or None, "at": t.at,
                          "by": "system" if t.actor_id is None else ("client" if t.actor_id == b.client_id else "handyman" if t.actor_id == b.handyman_id else "admin")}
                         for t in b.timeline.order_by("at", "id")],
            "payment": None if payment is None else {"status": payment.status, "method": payment.method,
                                                      **({"amount": str(payment.amount), "platform_fee": str(payment.platform_fee), "refunded": str(payment.refunded_amount)} if "finance.view" in perms else {})},
            "cash": _cash_summary(b, request.user) if "finance.view" in perms else None,
            "disputes": [{"id": d.pk, "status": d.status, "created_at": d.created_at} for d in b.disputes.all()],
            "live": None if session is None else {"artisan_sharing": session.artisan_sharing, "en_route_at": session.en_route_at, "arrived_at": session.arrived_at},
            "identity_verified": IdentityCheck.objects.filter(booking=b).exists(),
            "review": None if review is None else {"id": review.pk, "rating": review.rating, "hidden": review.is_hidden},
            "messages": Message.objects.filter(conversation__booking=b).count(),            # le CONTENU des échanges n'est jamais exposé
            "can_cancel": "bookings.manage" in perms and b.can_transition_to("cancelled"),
            "history": _history("booking", b.pk),
        })
        return Response(row)


class BookingCancel(BOView):
    """Annulation par l'administration : passe par la machine à états (politique de pénalité, escrow, notifications)."""
    bo_permission = "bookings.manage"

    @transaction.atomic
    def post(self, request, pk):
        b = Booking.objects.select_for_update().filter(pk=pk).first()
        if b is None:
            return bad_request("not_found", "Réservation introuvable.", 404)
        try:
            reason = _reason(request)
            if not b.can_transition_to("cancelled"):
                raise ValidationError(f"Une réservation « {b.get_status_display().lower()} » ne peut plus être annulée.", code="invalid_transition")
            b.transition_to("cancelled", actor=request.user)
        except ValidationError as exc:
            return _invalid(exc)
        audit_op(request, "booking.cancelled", b, reason=reason, cancellation_fee=str(b.cancellation_fee))
        return Response(_booking_row(b))


def _dispute_row(d: Dispute, perms) -> dict:
    payment = getattr(d.booking, "payment", None)
    return {"id": d.pk, "booking_id": d.booking_id, "status": d.status, "reporter": public_name(d.reporter), "reason": d.reason[:200],
            "created_at": d.created_at, "resolved_at": d.resolved_at, "resolution_action": d.resolution_action or None,
            "payment_status": payment.status if payment else None,
            "amount": str(payment.amount) if payment and "finance.view" in perms else None}


class DisputeList(BOView):
    bo_permission = "bookings.view"

    def get(self, request):
        perms = rbac.user_permissions(request.user)
        qs = Dispute.objects.select_related("booking", "booking__payment", "reporter")
        p = request.query_params
        if p.get("status") in dict(Dispute.STATUS_CHOICES):
            qs = qs.filter(status=p["status"])
        elif p.get("status") == "todo" or p.get("open") == "true":   # « à traiter » = ouverts ET en examen
            qs = qs.filter(status__in=("open", "under_review"))
        if (p.get("user") or "").isdigit():
            uid = int(p["user"])
            qs = qs.filter(Q(reporter_id=uid) | Q(booking__client_id=uid) | Q(booking__handyman_id=uid))
        q = (p.get("q") or "").strip()
        if q:
            cond = (Q(reason__icontains=q) | Q(reporter__first_name__icontains=q) | Q(reporter__last_name__icontains=q)
                    | Q(booking__service__title__icontains=q))
            qs = qs.filter(cond | Q(pk=int(q)) | Q(booking_id=int(q))) if q.isdigit() else qs.filter(cond)
        qs = apply_range(request, qs, "created_at").order_by(ordering(request, {"created_at": "created_at", "status": "status"}, "-created_at"), "-id")
        return paginate(request, qs, lambda d: _dispute_row(d, perms))


class DisputeDetail(BOView):
    bo_permission = "bookings.view"

    def get(self, request, pk):
        d = Dispute.objects.select_related("booking", "booking__payment", "booking__client", "booking__handyman", "reporter", "resolved_by").filter(pk=pk).first()
        if d is None:
            return bad_request("not_found", "Litige introuvable.", 404)
        perms = rbac.user_permissions(request.user)
        row = _dispute_row(d, perms)
        row.update({"reason": d.reason, "resolution": d.resolution or "", "resolved_by": public_name(d.resolved_by) if d.resolved_by_id else None,
                    "client": public_name(d.booking.client), "artisan": public_name(d.booking.handyman),
                    "reporter_role": "client" if d.reporter_id == d.booking.client_id else "artisan",
                    "can_decide": "bookings.manage" in perms and d.status in ("open", "under_review"),
                    "can_move_money": "finance.manage" in perms, "history": _history("dispute", d.pk)})
        return Response(row)


class DisputeAction(BOView):
    """Prise en charge, résolution ou rejet. Rembourser le client / verser l'artisan = mouvement d'argent → `finance.manage`
    en plus (séparation des tâches : le support médie, la finance exécute)."""
    bo_permission = "bookings.manage"

    @transaction.atomic
    def post(self, request, pk, op):
        d = Dispute.objects.select_for_update().select_related("booking").filter(pk=pk).first()
        if d is None:
            return bad_request("not_found", "Litige introuvable.", 404)
        if d.status not in ("open", "under_review"):
            return bad_request("not_open", "Ce litige est déjà clos.", 409)
        try:
            if op == "review":
                if d.status == "under_review":
                    raise ValidationError("Ce litige est déjà en examen.", code="already")
                d.status = "under_review"
                d.save(update_fields=["status", "updated_at"])
                audit_op(request, "dispute.under_review", d)
                return Response({"id": d.pk, "status": d.status})
            resolution = _reason(request)
            if op == "reject":
                d.reject(by=request.user, resolution=resolution)
            elif op == "resolve":
                action = request.data.get("action")
                if action not in dict(Dispute.RESOLUTION_ACTIONS):
                    raise ValidationError("Action de résolution invalide.", code="invalid_action")
                if action in ("refund_client", "release_artisan") and not rbac.has_permission(request.user, "finance.manage"):
                    return bad_request("finance_required", "Un remboursement ou un versement exige le droit « finance.manage ».", 403)
                d.resolve(action, by=request.user, resolution=resolution)
            else:
                return bad_request("invalid_action", "Opération inconnue.", 404)
        except ValidationError as exc:
            return _invalid(exc)
        audit_op(request, f"dispute.{'rejected' if op == 'reject' else 'resolved'}", d, reason=resolution, resolution_action=d.resolution_action)
        return Response({"id": d.pk, "status": d.status, "resolution_action": d.resolution_action or None})


# ═══ Suivi en direct (aucune coordonnée par défaut) ═════════════════════════════════════════════════════════════════

ARRIVAL_FAR_M = 500


def _live_row(s: TrackingSession, now) -> dict:
    last = s.positions.filter(role=LivePosition.ARTISAN).order_by("-captured_at").first()
    age = max(0, int((now - last.captured_at).total_seconds())) if last else None
    b = s.booking
    phase = live_services.phase_of(b, s)
    flags = []
    if s.arrival_distance_m and s.arrival_distance_m > ARRIVAL_FAR_M:
        flags.append("arrival_far")                      # arrivée déclarée loin du lieu
    if s.artisan_sharing and phase == "en_route" and (age is None or age > live_services.STALE_AFTER):
        flags.append("position_stale")                   # l'artisan est « en route » mais ne transmet plus
    return {"booking_id": b.pk, "status": b.status, "phase": phase, "artisan": public_name(b.handyman), "client": public_name(b.client),
            "artisan_sharing": s.artisan_sharing, "client_sharing": s.client_sharing, "en_route_at": s.en_route_at, "arrived_at": s.arrived_at,
            "arrival_distance_m": s.arrival_distance_m, "last_position_age_s": age, "flags": flags, "updated_at": s.updated_at}


class LiveList(BOView):
    bo_permission = "live.view"

    def get(self, request):
        now = timezone.now()
        qs = TrackingSession.objects.select_related("booking", "booking__client", "booking__handyman")
        if request.query_params.get("all") != "true":
            qs = qs.filter(Q(artisan_sharing=True) | Q(client_sharing=True) | Q(booking__status="in_progress")).filter(booking__status__in=("confirmed", "in_progress"))
        return paginate(request, qs.order_by("-updated_at", "-id"), lambda s: _live_row(s, now))


class LiveDetail(BOView):
    bo_permission = "live.view"

    def get(self, request, booking_id):
        s = TrackingSession.objects.select_related("booking", "booking__client", "booking__handyman").filter(booking_id=booking_id).first()
        if s is None:
            return bad_request("not_found", "Aucun suivi pour cette réservation.", 404)
        row = _live_row(s, timezone.now())
        row.update({"artisan_consent_at": s.artisan_consent_at, "client_consent_at": s.client_consent_at, "route_eta_seconds": s.route_eta_seconds,
                    "positions_kept": s.positions.count(), "stale_after_seconds": live_services.STALE_AFTER, "history": _history("booking", booking_id)})
        return Response(row)


class LivePositionAccess(BOView):
    """Position APPROXIMATIVE (~100 m) de l'artisan, uniquement si : motif écrit, mission active, partage consenti, position
    récente. Chaque accès est journalisé. Aucune position du client, aucun historique."""
    bo_permission = "live.view"

    def post(self, request, booking_id):
        try:
            reason = _reason(request)
        except ValidationError as exc:
            return _invalid(exc)
        s = TrackingSession.objects.select_related("booking").filter(booking_id=booking_id).first()
        if s is None or s.booking.status not in ("confirmed", "in_progress") or not s.artisan_sharing:
            return bad_request("not_available", "Aucune position n'est partagée pour cette mission.", 409)
        last = s.positions.filter(role=LivePosition.ARTISAN).order_by("-captured_at").first()
        now = timezone.now()
        if last is None or (now - last.captured_at).total_seconds() > live_services.STALE_AFTER:
            return bad_request("stale", "La dernière position est trop ancienne pour être consultée.", 409)
        audit_op(request, "live.position_viewed", s.booking, reason=reason)
        return Response({"booking_id": booking_id, "lat": round(last.loc.y, 3), "lng": round(last.loc.x, 3), "precision_m": 100,
                         "age_seconds": int((now - last.captured_at).total_seconds())})


# ═══ Avis ═══════════════════════════════════════════════════════════════════════════════════════════════════════════

def _review_row(r: Review) -> dict:
    return {"id": r.pk, "booking_id": r.booking_id, "rating": r.rating, "comment": (r.comment or "")[:200], "author": public_name(r.booking.client),
            "artisan": public_name(r.booking.handyman), "is_hidden": r.is_hidden, "reports": getattr(r, "n_reports", 0), "has_reply": bool(r.reply_text), "created_at": r.created_at}


class ReviewList(BOView):
    bo_permission = "reviews.moderate"

    def get(self, request):
        p = request.query_params
        qs = Review.objects.select_related("booking", "booking__client", "booking__handyman").annotate(n_reports=Count("reports", filter=Q(reports__is_resolved=False)))
        if p.get("hidden") in ("true", "false"):
            qs = qs.filter(is_hidden=p["hidden"] == "true")
        if p.get("reported") == "true":
            qs = qs.filter(n_reports__gt=0)
        if (p.get("rating") or "").isdigit():
            qs = qs.filter(rating=int(p["rating"]))
        q = (p.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(comment__icontains=q) | Q(booking__handyman__first_name__icontains=q) | Q(booking__handyman__last_name__icontains=q))
        if not p.get("ordering"):  # par défaut : les plus signalés d'abord (file de modération) ; sinon tri choisi
            return paginate(request, apply_range(request, qs, "created_at").order_by("-n_reports", "-created_at", "-id"), _review_row)
        qs = apply_range(request, qs, "created_at").order_by(ordering(request, {"created_at": "created_at", "rating": "rating"}, "-created_at"), "-id")
        return paginate(request, qs, _review_row)


class ReviewDetail(BOView):
    bo_permission = "reviews.moderate"

    def get(self, request, pk):
        r = Review.objects.select_related("booking", "booking__client", "booking__handyman").filter(pk=pk).first()
        if r is None:
            return bad_request("not_found", "Avis introuvable.", 404)
        row = _review_row(r)
        row.update({"comment": r.comment or "", "reply": r.reply_text or "", "reply_at": r.reply_at,
                    "criteria": {c: getattr(r, c) for c in Review.CRITERIA if getattr(r, c) is not None},
                    "photos": r.media.count() if hasattr(r, "media") else 0,
                    "reports": [{"id": x.pk, "reason": x.reason, "reporter": public_name(x.reporter), "is_resolved": x.is_resolved, "created_at": x.created_at} for x in r.reports.select_related("reporter")],
                    "history": _history("review", r.pk)})
        return Response(row)


class ReviewVisibility(BOView):
    """Masquer / republier un avis (jamais de réécriture ni de suppression : la note redevient comptée à la republication)."""
    bo_permission = "reviews.moderate"
    hide = True

    @transaction.atomic
    def post(self, request, pk):
        r = Review.objects.select_for_update().select_related("booking").filter(pk=pk).first()
        if r is None:
            return bad_request("not_found", "Avis introuvable.", 404)
        try:
            reason = _reason(request)
            if r.is_hidden == self.hide:
                raise ValidationError("Cet avis est déjà dans cet état.", code="already")
        except ValidationError as exc:
            return _invalid(exc)
        r.is_hidden = self.hide
        r.save(update_fields=["is_hidden", "updated_at"])     # la note de l'artisan et ses badges se recalculent par signal
        if self.hide:
            Report.objects.filter(review=r, is_resolved=False).update(is_resolved=True)
        audit_op(request, "review.hidden" if self.hide else "review.restored", r, reason=reason)
        return Response(_review_row(r))


class ReviewHide(ReviewVisibility):
    hide = True


class ReviewRestore(ReviewVisibility):
    hide = False


def _report_row(rep: Report) -> dict:
    return {"id": rep.pk, "type": rep.report_type, "reason": rep.reason, "reporter": public_name(rep.reporter), "created_at": rep.created_at, "is_resolved": rep.is_resolved,
            "review_id": rep.review_id, "excerpt": (rep.review.comment if rep.review_id else (rep.message.content if rep.message_id else "")or "")[:300]}


class ReportList(BOView):
    bo_permission = "reviews.moderate"

    def get(self, request):
        p = request.query_params
        qs = Report.objects.select_related("reporter", "review", "message")
        if p.get("resolved") in ("true", "false"):
            qs = qs.filter(is_resolved=p["resolved"] == "true")
        elif p.get("resolved") != "all":
            qs = qs.filter(is_resolved=False)
        q = (p.get("q") or "").strip()
        if q:
            cond = (Q(reason__icontains=q) | Q(reporter__first_name__icontains=q) | Q(reporter__last_name__icontains=q)
                    | Q(review__comment__icontains=q) | Q(message__content__icontains=q))
            qs = qs.filter(cond | Q(pk=int(q))) if q.isdigit() else qs.filter(cond)
        qs = apply_range(request, qs, "created_at").order_by(ordering(request, {"created_at": "created_at"}, "-created_at"), "-id")
        return paginate(request, qs, _report_row)


class ReportResolve(BOView):
    bo_permission = "reviews.moderate"

    @transaction.atomic
    def post(self, request, pk):
        rep = Report.objects.select_for_update(of=("self",)).select_related("review").filter(pk=pk).first()
        if rep is None:
            return bad_request("not_found", "Signalement introuvable.", 404)
        if rep.is_resolved:
            return bad_request("already", "Ce signalement est déjà traité.", 409)
        try:
            reason = _reason(request)
        except ValidationError as exc:
            return _invalid(exc)
        rep.is_resolved = True
        rep.save(update_fields=["is_resolved"])
        audit_op(request, "report.resolved", rep, reason=reason, report_type=rep.report_type)
        return Response(_report_row(rep))
