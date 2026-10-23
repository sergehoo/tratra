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
    first, last = (user.first_name or "").strip(), (user.last_name or "").strip()
    name = f"{first} {last[0]}." if first and last else _first(user)        # « Prénom N. », comme partout ailleurs
    return {"id": user.pk, "name": name, "photo": absolute_media_url(request, profile.photo) if profile else None,
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
        # Hybrid Matching : mode courant, professionnel choisi, bascule possible (avec confirmation) tant que la demande est ouverte.
        "matching": req.matching, "matching_label": req.get_matching_display(), "switches": req.switches,
        "target": _pro_card(req.target, request) if req.target_id else None,
        "service": {"id": req.service_id, "title": req.service.title} if req.service_id else None,
        "can_switch": req.is_open,
        "awaiting_reason": (req.events.filter(kind="awaiting").order_by("-at").values_list("data", flat=True).first() or {}).get("reason")
        if req.status == MissionRequest.AWAITING else None,
        "can_cancel": req.is_open, "can_relaunch": req.status in (MissionRequest.UNFULFILLED, MissionRequest.CANCELLED)
        or (req.status == MissionRequest.ASSIGNED and req.booking is not None and req.booking.status == "cancelled"),
    }
    if req.mode == MissionRequest.QUOTE:
        data["quotes"] = [{"offer": o.pk, "amount": int(o.quote_amount), "amount_label": money(o.quote_amount), "message": o.quote_message,
                           "status": o.status, "at": o.responded_at, "distance_km": o.distance_km, "pro": _pro_card(o.handyman, request)}
                          for o in offers if o.quote_amount is not None]
    return data


def _client_request(request, pk) -> MissionRequest:
    return get_object_or_404(MissionRequest.objects.select_related("category", "assigned_to", "booking", "target", "service"), pk=pk,
                             client=request.user)


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
        qs = MissionRequest.objects.filter(client=request.user).select_related("category", "assigned_to", "booking", "target", "service")[:30]
        return Response({"results": [request_payload(r, request) for r in qs]})
    from antifraud.permissions import ensure_verified

    ensure_verified(request.user)        # anti-fraude : commande réservée aux numéros prouvés
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
    matching = str(d.get("matching") or MissionRequest.AUTO)
    mode = str(d.get("mode") or MissionRequest.FIRM)
    service_id = d.get("service") if str(d.get("service") or "").isdigit() else None
    if matching == MissionRequest.DIRECT and service_id and amount is None and mode == MissionRequest.FIRM:
        from handy.models import Service

        svc = Service.objects.filter(pk=service_id, is_active=True).first()
        if svc is not None and svc.price_type == "fixed" and svc.price is not None:
            amount = int(svc.price)   # réservation d'une offre à prix fixe : le prix affiché de l'offre
        elif svc is not None and svc.price_type == "quote":
            mode = MissionRequest.QUOTE
    req = services.create_request(request.user, category=category, address=str(d.get("address") or ""), scheduled_for=when,
                                  mode=mode, amount=amount, commune=str(d.get("commune") or ""),
                                  city=str(d.get("city") or "Abidjan"), postal_code=str(d.get("postal_code") or ""),
                                  description=str(d.get("description") or ""), lat=lat, lng=lng,
                                  matching=matching, target_id=d.get("target"), service_id=service_id)
    return Response(request_payload(req, request), status=201)


@endpoint(["POST"], "Changer de mode (Trouvez-moi un professionnel ⇄ Choisir mon professionnel), avec confirmation", idempotent="request.switch")
def request_switch(request, pk):
    from flash import hybrid

    _client_request(request, pk)
    d = request.data
    req = hybrid.switch(pk, request.user, str(d.get("to") or ""), target_id=d.get("target"), expected_version=d.get("expected_version"),
                        confirm=d.get("confirm") in (True, "true", "1", 1))
    return Response(request_payload(req, request))


def _when(raw):
    if not raw:
        return None
    when = parse_datetime(str(raw))
    if when is None:
        raise FlashError("invalid_date", "Date invalide.")
    return timezone.make_aware(when) if timezone.is_naive(when) else when


def _category(raw) -> ServiceCategory:
    category = ServiceCategory.objects.filter(pk=raw, is_active=True).first() if str(raw or "").isdigit() else None
    if category is None:
        raise FlashError("category_required", "Choisissez le métier recherché.")
    return category


@endpoint(["GET"], "Mode conseillé pour ce métier (immédiat, planifié ou sur devis), dernier choix du client")
def suggest_view(request):
    from flash import hybrid

    p = request.query_params
    return Response(hybrid.suggest(request.user, _category(p.get("category")), when=_when(p.get("when")), quote=p.get("mode") == "quote",
                                   lat=_float(p.get("lat"), "lat"), lng=_float(p.get("lng"), "lng"), commune=p.get("commune", "")))


@endpoint(["GET"], "Professionnels disponibles à choisir (profils, avis, badges, favoris)")
def pros_view(request):
    from flash import hybrid

    p = request.query_params
    sort = p.get("sort", "recommended")
    rows = hybrid.direct_pros(request.user, _category(p.get("category")), when=_when(p.get("when")), lat=_float(p.get("lat"), "lat"),
                              lng=_float(p.get("lng"), "lng"), commune=p.get("commune", ""),
                              sort=sort if sort in hybrid.SORTS else "recommended", min_rating=_float(p.get("min_rating"), "min_rating"),
                              badge=p.get("badge", "") if p.get("badge") in ("VERIFIE", "EXPERT", "SUR") else "",
                              favorites_only=p.get("favorites") in ("1", "true"), request=request)
    return Response({"count": len(rows), "results": rows})


@endpoint(["GET", "POST"], "Mes professionnels favoris / ajouter un favori", idempotent="favorite.add")
def favorites_view(request):
    from flash import hybrid

    if request.method == "POST":
        hybrid.add_favorite(request.user, request.data.get("handyman"))
        return Response({"results": hybrid.favorites(request.user, request)}, status=201)
    return Response({"results": hybrid.favorites(request.user, request)})


@endpoint(["DELETE"], "Retirer un favori")
def favorite_delete(request, handyman_id):
    from flash import hybrid

    hybrid.remove_favorite(request.user, handyman_id)
    return Response({"results": hybrid.favorites(request.user, request)})


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
        lat=old.location.y if old.location else None, lng=old.location.x if old.location else None,
        # Le choix du client est conservé (même mode, même professionnel) sauf s'il en indique un autre.
        matching=str(d.get("matching") or old.matching), target_id=d.get("target", old.target_id), service_id=old.service_id)
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
