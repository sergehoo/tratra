"""API Tratra Flash (web et application). Toutes les routes exigent une session ; une demande n'existe que pour son client, une proposition
que pour son professionnel (404 sinon). Les écritures acceptent `Idempotency-Key` : un double appui ne crée ni deux demandes, ni deux
réponses. Refus métier → `{code, detail, ...}`."""
import functools

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from continuity.idempotency import run_idempotent
from flash import services
from flash.models import DispatchConfig, MissionOffer, MissionRequest
from flash.notify import money, offer_payload, when_label, zone_label
from flash.services import FlashError
from handy.eligibility import eligibility_summary, is_publishable
from handy.models import HandymanProfile, ServiceCategory

TAG = "Tratra Flash"


def endpoint(methods, summary, *, idempotent=None):
    def decorate(fn):
        @functools.wraps(fn)
        def inner(request, *args, **kwargs):
            def call():
                try:
                    return fn(request, *args, **kwargs)
                except FlashError as exc:
                    return Response({"code": exc.code, "detail": exc.message, **exc.extra}, status=exc.status)
            if idempotent and request.method == "POST":
                return run_idempotent(request, f"flash.{idempotent}", call)
            return call()
        return extend_schema(tags=[TAG], summary=summary)(api_view(methods)(permission_classes([permissions.IsAuthenticated])(inner)))
    return decorate


def _first(user) -> str:
    return (getattr(user, "first_name", "") or "").strip() or "Professionnel"


# ═══ Côté client ════════════════════════════════════════════════════════════════════════════════════════════════════════

def _pro_card(user, request) -> dict:
    from handy.api.serializers import absolute_media_url
    from reputation.services import provider_score

    profile = getattr(user, "handyman_profile", None)
    rep = provider_score(user)
    return {"id": user.pk, "name": _first(user), "photo": absolute_media_url(request, profile.photo) if profile else None,
            "trust_score": profile.trust_score if profile else None, "badges": profile.trust_badges if profile else [],
            "rating": rep["average"], "reviews": rep["count"], "verified": bool(profile and is_publishable(profile))}


def request_payload(req: MissionRequest, request) -> dict:
    offers = list(req.offers.select_related("handyman", "handyman__handyman_profile"))
    count = lambda st: sum(1 for o in offers if o.status == st)   # noqa: E731
    data = {
        "id": req.pk, "status": req.status, "status_label": req.get_status_display(), "mode": req.mode, "mode_label": req.get_mode_display(),
        "category": {"id": req.category_id, "name": req.category.name}, "description": req.description, "address": req.address,
        "commune": req.commune, "city": req.city, "scheduled_for": req.scheduled_for, "when_label": when_label(req),
        "immediate": req.is_immediate, "amount": int(req.amount) if req.amount is not None else None,
        "amount_label": money(req.amount) if req.amount is not None else "Sur devis", "wave": req.wave,
        "progress": {"contacted": len(offers), "waiting": count(MissionOffer.PENDING), "declined": count(MissionOffer.DECLINED),
                     "no_answer": count(MissionOffer.EXPIRED), "quotes": sum(1 for o in offers if o.quote_amount is not None)},
        "quote_deadline": req.quote_deadline, "created_at": req.created_at, "assigned_at": req.assigned_at, "closed_at": req.closed_at,
        "close_reason": req.close_reason, "booking": req.booking_id, "version": req.version,
        "assigned_to": _pro_card(req.assigned_to, request) if req.assigned_to_id else None,
        "can_cancel": req.is_open, "can_relaunch": req.status in (MissionRequest.UNFULFILLED, MissionRequest.CANCELLED)
        or (req.status == MissionRequest.ASSIGNED and req.booking is not None and req.booking.status == "cancelled"),
    }
    if req.mode == MissionRequest.QUOTE:
        data["quotes"] = [{"offer": o.pk, "amount": int(o.quote_amount), "amount_label": money(o.quote_amount), "message": o.quote_message,
                           "status": o.status, "at": o.responded_at, "distance_km": o.distance_km, "pro": _pro_card(o.handyman, request)}
                          for o in offers if o.quote_amount is not None]
    return data


def _client_request(request, pk) -> MissionRequest:
    return get_object_or_404(MissionRequest.objects.select_related("category", "assigned_to", "booking"), pk=pk, client=request.user)


def _float(value, name):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise FlashError("invalid", f"`{name}` invalide.")


@endpoint(["GET", "POST"], "Mes demandes Tratra Flash / nouvelle demande", idempotent="request.create")
def requests_view(request):
    if request.method == "GET":
        qs = MissionRequest.objects.filter(client=request.user).select_related("category", "assigned_to", "booking")[:30]
        return Response({"results": [request_payload(r, request) for r in qs]})
    d = request.data
    category = ServiceCategory.objects.filter(pk=d.get("category")).first() if str(d.get("category") or "").isdigit() else None
    if category is None:
        raise FlashError("category_required", "Choisissez le métier recherché.")
    when = parse_datetime(str(d.get("scheduled_for"))) if d.get("scheduled_for") else None
    if d.get("scheduled_for") and when is None:
        raise FlashError("invalid_date", "Date de la mission invalide.")
    if when is not None and timezone.is_naive(when):
        when = timezone.make_aware(when)
    amount = d.get("amount")
    if amount not in (None, ""):
        try:
            amount = int(str(amount).replace(" ", "").replace(" ", ""))
        except ValueError:
            raise FlashError("invalid_amount", "Montant invalide.")
    else:
        amount = None
    lat, lng = _float(d.get("lat"), "lat"), _float(d.get("lng"), "lng")
    if (lat is None) != (lng is None):
        raise FlashError("invalid", "Position incomplète.")
    req = services.create_request(request.user, category=category, address=str(d.get("address") or ""), scheduled_for=when,
                                  mode=str(d.get("mode") or MissionRequest.FIRM), amount=amount, commune=str(d.get("commune") or ""),
                                  city=str(d.get("city") or "Abidjan"), postal_code=str(d.get("postal_code") or ""),
                                  description=str(d.get("description") or ""), lat=lat, lng=lng)
    return Response(request_payload(req, request), status=201)


@endpoint(["GET"], "Détail d'une demande Tratra Flash")
def request_detail(request, pk):
    return Response(request_payload(_client_request(request, pk), request))


@endpoint(["POST"], "Annuler une demande en cours", idempotent="request.cancel")
def request_cancel(request, pk):
    _client_request(request, pk)
    return Response(request_payload(services.cancel_request(pk, request.user), request))


@endpoint(["POST"], "Retenir un devis (la mission est attribuée)", idempotent="quote.choose")
def request_choose_quote(request, pk, offer_id):
    _client_request(request, pk)
    return Response(request_payload(services.choose_quote(pk, request.user, offer_id), request))


@endpoint(["POST"], "Relancer une demande (aucun pro, annulée, ou réservation annulée)", idempotent="request.relaunch")
def request_relaunch(request, pk):
    old = _client_request(request, pk)
    payload = request_payload(old, request)
    if not payload["can_relaunch"]:
        raise FlashError("not_relaunchable", "Cette demande est encore en cours.", 409)
    d = request.data
    when = parse_datetime(str(d.get("scheduled_for"))) if d.get("scheduled_for") else None
    if when is not None and timezone.is_naive(when):
        when = timezone.make_aware(when)
    amount = d.get("amount", old.amount)
    req = services.create_request(
        request.user, category=old.category, address=old.address, scheduled_for=when or max(old.scheduled_for, timezone.now()),
        mode=old.mode, amount=int(amount) if amount not in (None, "") else None, commune=old.commune, city=old.city,
        postal_code=old.postal_code, description=old.description,
        lat=old.location.y if old.location else None, lng=old.location.x if old.location else None)
    services.log(req, "created", actor=request.user, relaunch_of=old.pk)
    return Response(request_payload(req, request), status=201)


# ═══ Côté professionnel ═════════════════════════════════════════════════════════════════════════════════════════════════

def offer_view_payload(offer: MissionOffer, request) -> dict:
    from reputation.services import requester_score

    req = offer.request
    now = timezone.now()
    data = {**offer_payload(offer), "status": offer.status, "status_label": offer.get_status_display(),
            "seconds_left": max(0, int((offer.expires_at - now).total_seconds())) if offer.status == MissionOffer.PENDING else 0,
            "description": req.description, "sent_at": offer.sent_at, "responded_at": offer.responded_at,
            "decline_reason": offer.decline_reason, "quote_amount": int(offer.quote_amount) if offer.quote_amount is not None else None,
            "quote_message": offer.quote_message, "why": offer.score_detail.get("criteria", []),
            "client_reputation": {k: v for k, v in requester_score(req.client).items() if k in ("count", "average", "public")},
            "decline_reasons": [{"code": c, "label": label} for c, label in MissionOffer.DECLINE_REASONS],
            "request_status": req.status}
    if offer.status == MissionOffer.ACCEPTED and req.assigned_to_id == request.user.pk:
        # Après l'attribution seulement : adresse exacte et prénom du client (la réservation donne le reste).
        data.update(address=req.address, client_name=(req.client.first_name or "").strip() or "Client", booking=req.booking_id)
    return data


def _pro_offer(request, pk) -> MissionOffer:
    return get_object_or_404(MissionOffer.objects.select_related("request", "request__category", "request__client"), pk=pk,
                             handyman=request.user)


@endpoint(["GET"], "Mes propositions Tratra Flash")
def offers_view(request):
    qs = MissionOffer.objects.filter(handyman=request.user).select_related("request", "request__category", "request__client")
    if request.query_params.get("status") == "pending":
        qs = qs.filter(status=MissionOffer.PENDING, expires_at__gt=timezone.now())
    return Response({"results": [offer_view_payload(o, request) for o in qs[:30]]})


@endpoint(["GET"], "Détail d'une proposition (marquée « vue »)")
def offer_detail(request, pk):
    offer = _pro_offer(request, pk)
    services.mark_seen(offer.pk, request.user)
    return Response(offer_view_payload(offer, request))


@endpoint(["POST"], "Accepter (prix ferme) : la mission vous est attribuée si personne ne l'a prise", idempotent="offer.accept")
def offer_accept(request, pk):
    services.accept(pk, request.user)
    return Response(offer_view_payload(_pro_offer(request, pk), request))


@endpoint(["POST"], "Refuser (sans aucune conséquence)", idempotent="offer.decline")
def offer_decline(request, pk):
    services.decline(pk, request.user, str(request.data.get("reason") or ""))
    return Response(offer_view_payload(_pro_offer(request, pk), request))


@endpoint(["POST"], "Envoyer un devis (demande sur devis)", idempotent="offer.quote")
def offer_quote(request, pk):
    services.send_quote(pk, request.user, request.data.get("amount"), str(request.data.get("message") or ""))
    return Response(offer_view_payload(_pro_offer(request, pk), request))


@endpoint(["GET"], "Ma disponibilité Tratra Flash")
def availability_view(request):
    profile = HandymanProfile.objects.select_related("user").filter(user=request.user).first()
    if profile is None:
        raise FlashError("no_profile", "Aucun profil professionnel sur ce compte.", 404)
    return Response(availability_payload(profile))


def availability_payload(profile: HandymanProfile) -> dict:
    eligible = is_publishable(profile)
    blockers = eligibility_summary(profile)["publication"]["blockers"] if not eligible else []
    slots = list(profile.availability_slots.order_by("weekday", "start_time").values("weekday", "start_time", "end_time"))
    return {"online": bool(profile.online), "eligible": eligible,
            "reason": None if eligible else (blockers[0]["label"] if blockers else "Profil pas encore vérifié : impossible de recevoir des missions."),
            "missed_streak": services.missed_streak(profile.user_id), "auto_pause_after": DispatchConfig.get_solo().auto_pause_after_missed,
            "schedule": [{"weekday": s["weekday"], "start": s["start_time"].strftime("%H:%M"), "end": s["end_time"].strftime("%H:%M")} for s in slots],
            "pending_offers": MissionOffer.objects.filter(handyman_id=profile.user_id, status=MissionOffer.PENDING,
                                                          expires_at__gt=timezone.now()).count()}
