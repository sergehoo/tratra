"""Modules « personnes » du Back-Office : Utilisateurs, KYC, Tratra Trust, Tratra ID.

 - Aucune pièce d'identité dans une réponse JSON : un document se lit via un endpoint dédié, journalisé, en no-store ;
 - aucun badge ni validation créés à la main : on déclenche la réévaluation PAR LA RÈGLE (trust.engine) ;
 - suspension = effet immédiat par la règle d'éligibilité (publication, missions, validité du Tratra ID)."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, CharField, Count, Exists, F, IntegerField, Min, OuterRef, Q, Value, When
from django.http import FileResponse
from rest_framework import status
from rest_framework.response import Response

from backoffice import services
from backoffice.common import BOView, apply_range, audit_op, bad_request, email_for, ordering, paginate, phone_for, public_name
from handy import eligibility
from handy.models import Booking, Device, Dispute, HandymanDocument, HandymanProfile, MarketingConsent, Notification, Report, User
from trust import engine, identity, metrics
from trust.models import AuditEvent, BadgeAward, BookingPass, IdentityCheck, ProfessionalId, TrustConfig

MIN_REASON = 5


def _reason(request, *, required: bool = True):
    reason = str(request.data.get("reason") or "").strip()
    if required and len(reason) < MIN_REASON:
        raise ValidationError(f"Un motif d'au moins {MIN_REASON} caractères est obligatoire.", code="reason_required")
    return reason[:500]


def _validation_response(exc: ValidationError):
    status_code = status.HTTP_409_CONFLICT if exc.code in ("kyc_incomplete", "already", "not_approved", "not_pending") else status.HTTP_400_BAD_REQUEST
    return bad_request(exc.code or "invalid", exc.messages[0], status_code)


def _history(target_type: str, target_id: int, limit: int = 15):
    rows = AuditEvent.objects.filter(target_type=target_type, target_id=target_id).select_related("actor")[:limit]
    return [{"action": e.action, "at": e.created_at, "by": public_name(e.actor) if e.actor_id else "Système",
             "reason": (e.data or {}).get("reason", "")} for e in rows]


# ═══ Utilisateurs ═══════════════════════════════════════════════════════════════════════════════════════════════════

def _kinds(u) -> list:
    kinds = []
    if hasattr(u, "handyman_profile"):
        kinds.append("artisan")
    if hasattr(u, "company_profile") or u.business_memberships.filter(is_active=True).exists():
        kinds.append("company")
    if not kinds or u.client_bookings.exists():
        kinds.append("client")
    return kinds


def _user_row(u: User, request) -> dict:
    """Ligne de liste : coordonnées masquées pour tous les rôles, complètes pour le Super Admin seulement (consultation journalisée)."""
    profile = getattr(u, "handyman_profile", None)
    return {
        "id": u.pk, "name": public_name(u), "phone": phone_for(request, u.phone), "email": email_for(request, u.email), "city": u.city or None,
        "is_active": u.is_active, "is_verified": u.is_verified, "date_joined": u.date_joined, "last_login": u.last_login,
        "is_artisan": profile is not None, "artisan_approved": bool(profile and profile.is_approved),
        "profile_id": profile.pk if profile is not None else None, "bookings": getattr(u, "n_bookings", 0),
    }


class UserList(BOView):
    bo_permission = "users.view"

    def get(self, request):
        p = request.query_params
        qs = (User.objects.filter(is_staff=False).select_related("handyman_profile")
              .annotate(n_bookings=Count("client_bookings", distinct=True) + Count("handyman_bookings", distinct=True)))
        q = (p.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(username__icontains=q)
                           | Q(email__icontains=q) | Q(phone__icontains=q))
        if p.get("city"):
            qs = qs.filter(city__iexact=p["city"][:80])
        kind = p.get("type")
        if kind == "artisan":
            qs = qs.filter(handyman_profile__isnull=False)
        elif kind == "company":
            qs = qs.filter(Q(company_profile__isnull=False) | Q(business_memberships__is_active=True)).distinct()
        elif kind == "client":
            qs = qs.filter(handyman_profile__isnull=True, company_profile__isnull=True)
        for param, field in (("active", "is_active"), ("verified", "is_verified")):
            if p.get(param) in ("true", "false"):
                qs = qs.filter(**{field: p[param] == "true"})
        qs = apply_range(request, qs, "date_joined")
        qs = qs.order_by(ordering(request, {"date_joined": "date_joined", "last_login": "last_login", "bookings": "n_bookings", "name": "first_name"}, "-date_joined"), "-id")
        return paginate(request, qs, lambda u: _user_row(u, request))


def _audit_contact_view(request, u) -> None:
    """La fiche affiche le téléphone et l'e-mail COMPLETS : une consultation = une trace (au plus une par administrateur et par compte
    toutes les 10 minutes, pour ne pas noyer le journal quand la page se recharge)."""
    from django.core.cache import cache

    if cache.add(f"bo:contact_view:{request.user.pk}:{u.pk}", 1, 600):
        audit_op(request, "user.contact_viewed", u)


class UserDetail(BOView):
    bo_permission = "users.view"

    def get(self, request, pk):
        u = User.objects.filter(pk=pk, is_staff=False).first()
        if u is None:
            return bad_request("not_found", "Compte introuvable.", 404)
        profile = getattr(u, "handyman_profile", None)
        consent = MarketingConsent.objects.filter(user=u).first()
        by_status = dict(Booking.objects.filter(client=u).values_list("status").annotate(n=Count("id")))
        missions = dict(Booking.objects.filter(handyman=u).values_list("status").annotate(n=Count("id")))
        data = _user_row(u, request)
        data.update({
            # Le détail montre les coordonnées complètes (support, vérifications) ; la liste, elles, restent masquées.
            "phone_full": u.phone, "email_full": u.email, "username": u.username, "country": u.country,
            "kinds": _kinds(u), "terms_accepted_at": u.terms_accepted_at,
            "profile": None if profile is None else {
                "id": profile.pk, "commune": profile.commune, "approved": profile.is_approved, "online": profile.online,
                "trust_score": profile.trust_score, "trust_badges": profile.trust_badges, "completed_jobs": profile.completed_jobs,
                "rating": profile.rating},
            "bookings": {"as_client": by_status, "as_artisan": missions, "active": services.active_booking_count(u)},
            "disputes": Dispute.objects.filter(Q(reporter=u) | Q(booking__client=u) | Q(booking__handyman=u)).count(),
            "reports": Report.objects.filter(reporter=u).count(),
            # Appareils : plateforme et activité seulement — JAMAIS le jeton d'appareil (FCM).
            "devices": [{"platform": d.device_type, "last_active": d.last_active} for d in Device.objects.filter(user=u).order_by("-last_active")[:10]],
            "marketing_consent": None if consent is None else {"granted": consent.granted, "granted_at": consent.granted_at,
                                                               "revoked_at": consent.revoked_at, "source": consent.source},
            "notifications_unread": Notification.objects.filter(user=u, is_read=False).count(),
            "history": _history("user", u.pk),
        })
        _audit_contact_view(request, u)
        return Response(data)


class UserSuspend(BOView):
    bo_permission = "users.manage"

    def post(self, request, pk):
        u = User.objects.filter(pk=pk).first()
        if u is None:
            return bad_request("not_found", "Compte introuvable.", 404)
        try:
            reason = _reason(request)
            result = services.suspend_user(u, by=request.user, reason=reason)
        except ValidationError as exc:
            return _validation_response(exc)
        audit_op(request, "user.suspended", u, reason=reason, **result)
        return Response({"id": u.pk, "is_active": False, **result})


class UserReactivate(BOView):
    bo_permission = "users.manage"

    def post(self, request, pk):
        u = User.objects.filter(pk=pk, is_staff=False).first()
        if u is None:
            return bad_request("not_found", "Compte introuvable.", 404)
        try:
            reason = _reason(request)
            services.reactivate_user(u)
        except ValidationError as exc:
            return _validation_response(exc)
        audit_op(request, "user.reactivated", u, reason=reason)
        return Response({"id": u.pk, "is_active": True})


# ═══ KYC ════════════════════════════════════════════════════════════════════════════════════════════════════════════

KYC_STATES = {"pending": "Pièces à examiner", "ready": "Prêt pour approbation", "approved": "Approuvé", "rejected": "Refusé", "incomplete": "Dossier incomplet"}


def kyc_profiles():
    """Profils annotés de leur état de dossier, calculé en base (filtrable, triable)."""
    docs = HandymanDocument.objects.filter(handyman=OuterRef("pk"))
    return HandymanProfile.objects.select_related("user").annotate(
        n_pending=Count("documents", filter=Q(documents__status="pending")),
        n_approved=Count("documents", filter=Q(documents__status="approved")),
        n_rejected=Count("documents", filter=Q(documents__status="rejected")),
        oldest_pending=Min("documents__uploaded_at", filter=Q(documents__status="pending")),
        id_ok=Exists(docs.filter(document_type="id_card", status="approved")),
    ).annotate(kyc_state=Case(
        When(n_pending__gt=0, then=Value("pending")),
        When(is_approved=True, then=Value("approved")),
        When(id_ok=True, then=Value("ready")),
        When(n_rejected__gt=0, then=Value("rejected")),
        default=Value("incomplete"), output_field=CharField()))


def _kyc_row(p) -> dict:
    return {"profile_id": p.pk, "user_id": p.user_id, "name": public_name(p.user), "commune": p.commune, "state": p.kyc_state,
            "state_label": KYC_STATES[p.kyc_state], "is_approved": p.is_approved, "documents": {"pending": p.n_pending, "approved": p.n_approved, "rejected": p.n_rejected},
            "oldest_pending_at": p.oldest_pending, "account_active": p.user.is_active}


class KycList(BOView):
    bo_permission = "kyc.review"

    def get(self, request):
        qs = kyc_profiles()
        state = request.query_params.get("state")
        if state in KYC_STATES:
            qs = qs.filter(kyc_state=state)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) | Q(user__username__icontains=q) | Q(commune__icontains=q))
        # La file se traite par ancienneté : les pièces en attente depuis le plus longtemps d'abord.
        qs = qs.annotate(_prio=Case(When(kyc_state="pending", then=Value(0)), default=Value(1), output_field=IntegerField())).order_by("_prio", F("oldest_pending").asc(nulls_last=True), "-id")
        return paginate(request, qs, _kyc_row)


def _doc_row(d: HandymanDocument) -> dict:
    return {"id": d.pk, "type": d.document_type, "type_label": d.get_document_type_display(), "status": d.status, "uploaded_at": d.uploaded_at,
            "reviewed_at": d.reviewed_at, "reviewed_by": public_name(d.reviewed_by) if d.reviewed_by_id else None,
            "rejection_reason": d.rejection_reason or "", "title": d.title, "issuer": d.issuer, "expires_on": d.expires_on,
            # Chemin de l'endpoint de lecture protégé (jamais l'URL de stockage) : chaque ouverture est journalisée.
            "file_path": f"/handy/backoffice/kyc/documents/{d.pk}/file/" if d.file else None}


class KycDetail(BOView):
    bo_permission = "kyc.review"

    def get(self, request, pk):
        p = kyc_profiles().filter(pk=pk).first()
        if p is None:
            return bad_request("not_found", "Dossier introuvable.", 404)
        row = _kyc_row(p)
        row.update({
            "documents": [_doc_row(d) for d in p.documents.select_related("reviewed_by").order_by("-uploaded_at")],
            "checklist": eligibility.profile_checklist(p), "publishable": eligibility.is_publishable(p),
            "documents_summary": row["documents"], "history": _history("handymanprofile", p.pk),
        })
        return Response(row)


class KycDocumentFile(BOView):
    """Lecture d'une pièce KYC : droit `kyc.review`, JAMAIS d'URL publique, no-store, chaque ouverture est journalisée."""
    bo_permission = "kyc.review"

    def get(self, request, pk):
        doc = HandymanDocument.objects.select_related("handyman").filter(pk=pk).first()
        if doc is None or not doc.file:
            return bad_request("not_found", "Document introuvable.", 404)
        try:
            opened = doc.file.open("rb")
        except (FileNotFoundError, ValueError):
            return bad_request("not_found", "Fichier introuvable.", 404)
        audit_op(request, "kyc.document_viewed", doc, profile_id=doc.handyman_id, type=doc.document_type)
        response = FileResponse(opened, as_attachment=False)
        response["Cache-Control"] = "private, no-store, max-age=0"
        response["Referrer-Policy"] = "no-referrer"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Disposition"] = 'inline; filename="document"'      # nom opaque : l'original peut contenir une identité
        return response


class KycDocumentReview(BOView):
    bo_permission = "kyc.review"

    @transaction.atomic
    def post(self, request, pk):
        doc = HandymanDocument.objects.select_for_update().select_related("handyman__user").filter(pk=pk).first()
        if doc is None:
            return bad_request("not_found", "Document introuvable.", 404)
        decision = request.data.get("action")
        if decision not in ("approve", "reject"):
            return bad_request("invalid_action", "Action invalide (approve ou reject).")
        if doc.status != "pending":
            return bad_request("not_pending", "Ce document a déjà été traité : une décision n'est pas modifiée en silence.", 409)
        try:
            reason = _reason(request, required=decision == "reject")
        except ValidationError as exc:
            return _validation_response(exc)
        doc.approve(by=request.user) if decision == "approve" else doc.reject(by=request.user, reason=reason)
        audit_op(request, f"kyc.document_{'approved' if decision == 'approve' else 'rejected'}", doc,
                 profile_id=doc.handyman_id, type=doc.document_type, reason=reason)
        return Response(_doc_row(doc))


class KycProfileApprove(BOView):
    bo_permission = "kyc.review"

    def post(self, request, pk):
        p = HandymanProfile.objects.select_related("user").filter(pk=pk).first()
        if p is None:
            return bad_request("not_found", "Dossier introuvable.", 404)
        try:
            services.approve_profile(p, by=request.user)
        except ValidationError as exc:
            return _validation_response(exc)
        audit_op(request, "kyc.profile_approved", p)
        return Response({"profile_id": p.pk, "is_approved": True})


class KycProfileSuspend(BOView):
    bo_permission = "kyc.review"

    def post(self, request, pk):
        p = HandymanProfile.objects.select_related("user").filter(pk=pk).first()
        if p is None:
            return bad_request("not_found", "Dossier introuvable.", 404)
        try:
            reason = _reason(request)
            services.suspend_profile(p, by=request.user, reason=reason)
        except ValidationError as exc:
            return _validation_response(exc)
        audit_op(request, "kyc.profile_suspended", p, reason=reason)
        return Response({"profile_id": p.pk, "is_approved": False})


# ═══ Tratra Trust ═══════════════════════════════════════════════════════════════════════════════════════════════════

def _trust_row(p) -> dict:
    return {"profile_id": p.pk, "user_id": p.user_id, "name": public_name(p.user), "commune": p.commune, "trust_score": p.trust_score,
            "badges": p.trust_badges, "evaluated_at": p.trust_evaluated_at, "completed_jobs": p.completed_jobs, "rating": p.rating,
            "approved": p.is_approved}


class TrustList(BOView):
    bo_permission = "trust.manage"

    def get(self, request):
        p = request.query_params
        qs = HandymanProfile.objects.select_related("user")
        if p.get("badge") in dict(BadgeAward.CODES):
            qs = qs.filter(trust_badges__contains=[p["badge"]])
        if p.get("no_score") == "true":
            qs = qs.filter(trust_score__isnull=True)
        for param, lookup in (("score_min", "gte"), ("score_max", "lte")):
            if (p.get(param) or "").isdigit():
                qs = qs.filter(**{f"trust_score__{lookup}": int(p[param])})
        q = (p.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) | Q(user__username__icontains=q))
        qs = qs.order_by(ordering(request, {"score": "trust_score", "evaluated": "trust_evaluated_at", "jobs": "completed_jobs"}, "-score"), "-id")
        return paginate(request, qs, _trust_row)


def _config_dict(c: TrustConfig) -> dict:
    return {f.name: getattr(c, f.name) for f in c._meta.concrete_fields if f.name not in ("id", "updated_at")}


class TrustDetail(BOView):
    """Explication en LECTURE SEULE : mesures, critères atteints ou non, historique des badges. Rien n'est écrit."""
    bo_permission = "trust.manage"

    def get(self, request, pk):
        profile = HandymanProfile.objects.select_related("user").filter(pk=pk).first()
        if profile is None:
            return bad_request("not_found", "Profil introuvable.", 404)
        config = TrustConfig.get_solo()
        measured = metrics.collect(profile, config)
        row = _trust_row(profile)
        row.update({
            "measured": measured, "score": engine.trust_score(measured, config),
            "criteria": {"expert": engine.expert_criteria(measured, config), "sure": engine.sure_criteria(measured, config)},
            "awards": [{"code": a.code, "label": a.get_code_display(), "started_at": a.started_at, "ended_at": a.ended_at,
                        "start_reason": a.start_reason, "end_reason": a.end_reason} for a in BadgeAward.objects.filter(profile=profile)[:30]],
            "history": _history("handymanprofile", profile.pk),
        })
        return Response(row)


class TrustReevaluate(BOView):
    """Réévalue PAR LA RÈGLE (jamais d'attribution manuelle d'un badge). Idempotent, journalisé."""
    bo_permission = "trust.manage"

    @transaction.atomic
    def post(self, request, pk):
        profile = HandymanProfile.objects.select_related("user").filter(pk=pk).first()
        if profile is None:
            return bad_request("not_found", "Profil introuvable.", 404)
        result = engine.evaluate_profile(profile, trigger="backoffice", actor=request.user)
        audit_op(request, "trust.reevaluated", profile, **{k: result[k] for k in ("awarded", "revoked", "badges", "score")})
        return Response(result)


class TrustConfigView(BOView):
    bo_permission = "trust.manage"

    def get(self, request):
        return Response(_config_dict(TrustConfig.get_solo()))


# ═══ Tratra ID ══════════════════════════════════════════════════════════════════════════════════════════════════════

def _id_row(pid: ProfessionalId) -> dict:
    last = pid.checks.first()
    return {"id": pid.pk, "code": pid.code, "profile_id": pid.profile_id, "name": public_name(pid.profile.user), "valid": identity.is_valid(pid.profile),
            "issued_at": pid.created_at, "checks": pid.checks.count(), "last_check_at": last.verified_at if last else None}


class TratraIdList(BOView):
    bo_permission = "tratra_id.manage"

    def get(self, request):
        p = request.query_params
        qs = ProfessionalId.objects.select_related("profile", "profile__user")
        q = (p.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(code__icontains=q) | Q(profile__user__first_name__icontains=q) | Q(profile__user__last_name__icontains=q))
        if p.get("valid") in ("true", "false"):
            valid_ids = eligibility.publishable().values("pk")
            qs = qs.filter(profile_id__in=valid_ids) if p["valid"] == "true" else qs.exclude(profile_id__in=valid_ids)
        return paginate(request, qs.order_by("-created_at", "-id"), _id_row)


class TratraIdStats(BOView):
    """Indicateurs : QR de mission (émis, utilisés, révoqués) et vérifications réussies — agrégats, aucun jeton."""
    bo_permission = "tratra_id.manage"

    def get(self, request):
        passes = BookingPass.objects
        return Response({
            "ids_issued": ProfessionalId.objects.count(),
            "ids_valid": ProfessionalId.objects.filter(profile_id__in=eligibility.publishable().values("pk")).count(),
            "mission_qr_issued": passes.count(), "mission_qr_used": passes.filter(used_at__isnull=False).count(),
            "mission_qr_revoked": passes.filter(revoked_at__isnull=False).count(),
            "checks_total": IdentityCheck.objects.count(),
        })


class TratraIdSuspend(BOView):
    """Révocation du Tratra ID = suspension du dossier (la validité est recalculée par la règle d'éligibilité)."""
    bo_permission = "tratra_id.manage"

    def post(self, request, pk):
        pid = ProfessionalId.objects.select_related("profile", "profile__user").filter(pk=pk).first()
        if pid is None:
            return bad_request("not_found", "Tratra ID introuvable.", 404)
        try:
            reason = _reason(request)
            services.suspend_profile(pid.profile, by=request.user, reason=reason)
        except ValidationError as exc:
            return _validation_response(exc)
        audit_op(request, "tratra_id.revoked", pid.profile, code=pid.code, reason=reason)
        return Response({"id": pid.pk, "valid": identity.is_valid(pid.profile)})


class MissionPassRevoke(BOView):
    """Invalide les QR de mission encore actifs d'une réservation (QR divulgué, litige d'identité)."""
    bo_permission = "tratra_id.manage"

    def post(self, request, booking_id):
        from django.utils import timezone

        reason = ""
        try:
            reason = _reason(request)
        except ValidationError as exc:
            return _validation_response(exc)
        n = BookingPass.objects.filter(booking_id=booking_id, used_at__isnull=True, revoked_at__isnull=True).update(revoked_at=timezone.now())
        audit_op(request, "tratra_id.mission_qr_revoked", target_type="booking", target_id=booking_id, revoked=n, reason=reason)
        return Response({"booking_id": booking_id, "revoked": n})
