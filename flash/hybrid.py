"""Hybrid Matching : une seule commande (`MissionRequest`), un seul flux, deux façons d'attribuer.

  AUTO   « Trouvez-moi un professionnel » : Smart Dispatch (filtrage, classement expliqué, vagues, expiration) — flash.services.
  DIRECT « Choisir mon professionnel »    : le client choisit sur profils, avis et badges ; la demande est proposée à CE professionnel
           seul (proposition ciblée : même alerte Tratra Flash, mêmes actions, même acceptation atomique, même réservation).

Le client peut passer d'un mode à l'autre, avec confirmation, sans rien ressaisir : la demande garde métier, adresse, date et prix ;
les propositions en attente sont retirées sous verrou AVANT les nouvelles (aucune attribution concurrente possible) ; les devis déjà
reçus restent valables. Si le professionnel choisi refuse ou ne répond pas, rien n'est relancé sans le client : la demande attend son
choix (autre professionnel, Smart Dispatch ou annulation). Un refus n'a jamais de conséquence pour le professionnel."""
from datetime import timedelta
from typing import Dict, List, Optional

from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone

from flash import services as S
from flash.models import DispatchConfig, DispatchEvent, MissionOffer, MissionRequest
from flash.services import FlashError
from handy.eligibility import is_publishable
from handy.models import FavoriteHandyman, HandymanProfile, Service, ServiceCategory, User

SORTS = ("recommended", "distance", "rating", "price")


# ═══ Suggestion du mode ═════════════════════════════════════════════════════════════════════════════════════════════════

def last_choice(client, category: Optional[ServiceCategory] = None) -> Optional[str]:
    """Mode choisi par le client à sa dernière demande (dans ce métier si possible) : on le lui repropose."""
    qs = DispatchEvent.objects.filter(kind="created", request__client=client).order_by("-at")
    if category is not None:
        in_trade = qs.filter(request__category_id__in=S.category_family(category)).values_list("data", flat=True).first()
        if in_trade and in_trade.get("matching"):
            return in_trade["matching"]
    data = qs.values_list("data", flat=True).first()
    return (data or {}).get("matching")


def suggest(client, category: ServiceCategory, *, when=None, quote: bool = False, lat=None, lng=None, commune: str = "") -> Dict:
    config = DispatchConfig.get_solo()
    now = timezone.now()
    immediate = S.is_immediate(when or now, config, now)
    if quote:
        suggested, reason = MissionRequest.AUTO, "Sur devis : plusieurs professionnels disponibles vous envoient leur prix, vous choisissez."
    elif immediate:
        suggested, reason = MissionRequest.AUTO, "Le plus rapide : les professionnels disponibles près de vous sont sollicités tout de suite."
    else:
        suggested, reason = MissionRequest.DIRECT, "Mission planifiée : prenez le temps de comparer les profils, les avis et les badges."
    pros = direct_pros(client, category, when=when, lat=lat, lng=lng, commune=commune, limit=200)
    favorites = [p for p in pros if p["favorite"]]
    if favorites and not quote:
        suggested, reason = MissionRequest.DIRECT, f"{favorites[0]['name']}, votre favori, est disponible pour ce métier."
    remembered = last_choice(client, category)
    preselected = remembered or suggested
    note = ""
    if preselected == MissionRequest.DIRECT and not pros:
        preselected, note = MissionRequest.AUTO, "Aucun professionnel disponible à choisir pour ce créneau : Tratra peut en chercher un."
    return {"suggested": suggested, "reason": reason, "preselected": preselected, "remembered": remembered is not None, "note": note,
            "immediate": immediate, "available_pros": len(pros), "favorites": favorites[:5],
            "options": [{"value": MissionRequest.AUTO, "label": "Trouvez-moi un professionnel",
                         "hint": "Tratra propose votre demande aux professionnels vérifiés et disponibles ; le premier qui accepte l'obtient."},
                        {"value": MissionRequest.DIRECT, "label": "Choisir mon professionnel",
                         "hint": "Vous choisissez sur les profils, avis et badges ; votre demande n'est proposée qu'à lui."}]}


# ═══ Choisir son professionnel ══════════════════════════════════════════════════════════════════════════════════════════

def _public_name(user) -> str:
    first, last = (user.first_name or "").strip(), (user.last_name or "").strip()
    return f"{first} {last[0]}." if first and last else (first or "Professionnel")


def pro_card(profile: HandymanProfile, *, request=None, category: Optional[ServiceCategory] = None, favorite: bool = False,
             distance_km=None, detail: Optional[Dict] = None) -> Dict:
    from handy.api.serializers import absolute_media_url
    from reputation.services import provider_score

    rep = provider_score(profile.user)
    services = Service.objects.filter(handyman_id=profile.user_id, is_active=True)
    if category is not None:
        services = services.filter(category_id__in=S.category_family(category))
    offers = [{"id": s.pk, "title": s.title, "price": int(s.price) if s.price is not None else None, "price_type": s.price_type,
               "category": s.category_id} for s in services.order_by("price", "id")[:5]]
    return {"id": profile.user_id, "name": _public_name(profile.user), "photo": absolute_media_url(request, profile.photo),
            "commune": profile.commune, "trust_score": profile.trust_score, "badges": profile.trust_badges or [],
            "rating": rep["average"], "reviews": rep["count"], "completed": profile.completed_jobs,
            "experience": profile.experience_label or (f"{profile.experience_years} an(s)" if profile.experience_years else ""),
            "distance_km": distance_km, "favorite": favorite, "offers": offers,
            "price_from": min((o["price"] for o in offers if o["price"] is not None), default=None),
            "why": [{"label": c["label"], "detail": c["detail"]} for c in (detail or {}).get("criteria", [])][:5],
            "score": (detail or {}).get("score")}


def _draft(client, category, *, when=None, lat=None, lng=None, commune: str = "") -> MissionRequest:
    config = DispatchConfig.get_solo()
    now = timezone.now()
    when = when or now
    return MissionRequest(client=client, category=category, commune=commune or "", scheduled_for=when,
                          is_immediate=S.is_immediate(when, config, now),
                          location=Point(float(lng), float(lat), srid=4326) if lat is not None and lng is not None else None)


def direct_pros(client, category: ServiceCategory, *, when=None, lat=None, lng=None, commune: str = "", sort: str = "recommended",
                min_rating=None, badge: str = "", favorites_only: bool = False, request=None, limit: int = 30) -> List[Dict]:
    """Professionnels que le client peut CHOISIR : mêmes règles que le Smart Dispatch (vérifiés, métier, zone, disponibles sur le
    créneau) ; les favoris sont signalés. Aucun professionnel n'est inventé : liste vide si personne n'est disponible."""
    config = DispatchConfig.get_solo()
    now = timezone.now()
    draft = _draft(client, category, when=when, lat=lat, lng=lng, commune=commune)
    favorites = set(FavoriteHandyman.objects.filter(client=client).values_list("handyman_id", flat=True)) if client else set()
    rows = []
    for cand in S.candidates(draft, config, now, listing=True):
        card = pro_card(cand.profile, request=request, category=category, favorite=cand.profile.user_id in favorites,
                        distance_km=cand.distance_km, detail=cand.detail)
        if favorites_only and not card["favorite"]:
            continue
        if min_rating is not None and (card["rating"] is None or card["rating"] < float(min_rating)):
            continue
        if badge and badge not in card["badges"]:
            continue
        rows.append(card)
    key = {"distance": lambda c: (c["distance_km"] is None, c["distance_km"] or 0),
           "rating": lambda c: (-(c["rating"] or 0), -(c["reviews"] or 0)),
           "price": lambda c: (c["price_from"] is None, c["price_from"] or 0)}.get(sort)
    if key:
        rows.sort(key=key)
    rows.sort(key=lambda c: not c["favorite"])   # favoris d'abord (tri stable : l'ordre choisi est conservé ensuite)
    return rows[:limit]


def validate_target(client, pro_id, req: MissionRequest, config: DispatchConfig, now) -> User:
    pro = User.objects.filter(pk=pro_id).select_related("handyman_profile").first() if str(pro_id or "").isdigit() else None
    profile = getattr(pro, "handyman_profile", None) if pro else None
    if pro is None or profile is None or not is_publishable(profile):
        raise FlashError("pro_unavailable", "Ce professionnel n'est pas disponible sur Tratra pour le moment.", 400)
    if pro.pk == client.pk:
        raise FlashError("self_booking_forbidden", "Vous ne pouvez pas vous choisir vous-même.", 400)
    family = S.category_family(req.category)
    offers_trade = (Service.objects.filter(handyman=pro, is_active=True, category_id__in=family).exists()
                    or profile.skills.filter(id__in=family).exists())
    if not offers_trade:
        raise FlashError("wrong_trade", f"{_public_name(pro)} ne propose pas « {req.category.name} ».", 400)
    if (profile.experience_years or 0) < S.required_experience(req.category):
        raise FlashError("wrong_trade", f"{_public_name(pro)} n'a pas l'expérience exigée pour ce métier.", 400)
    issue = S.availability_issue(profile, req, config, now)
    if issue:
        raise FlashError("pro_busy", f"{_public_name(pro)} n'est pas disponible : {issue.lower()}. Choisissez un autre créneau, un autre "
                                     "professionnel ou « Trouvez-moi un professionnel ».", 409, reason=issue)
    return pro


def send_targeted(req: MissionRequest, pro: User, config: DispatchConfig, now) -> MissionOffer:
    """Proposition au professionnel CHOISI (demande verrouillée par l'appelant). Même alerte, mêmes actions, même attribution."""
    profile = HandymanProfile.objects.select_related("user", "service_area").get(user=pro)
    _, distance = S.zone_of(profile, req, config)
    detail = S.score(profile, distance, config, now)
    timeout = config.direct_offer_timeout_seconds if req.is_immediate else config.direct_scheduled_offer_timeout_seconds
    req.wave += 1
    req.status = MissionRequest.SEARCHING
    req.save(update_fields=["wave", "status", "updated_at"])
    offer = MissionOffer.objects.create(request=req, handyman=pro, wave=req.wave, rank=1, score=detail["score"], score_detail=detail,
                                        distance_km=distance, expires_at=now + timedelta(seconds=timeout), targeted=True)
    S.log(req, "targeted", offer=offer, handyman=pro.pk, distance_km=distance, expires_at=offer.expires_at.isoformat())
    transaction.on_commit(lambda: S._after_wave(req.pk, req.wave, [offer.pk], timeout))
    return offer


def after_targeted_response(req: MissionRequest, config: DispatchConfig, now) -> None:
    """Appelé par le moteur (demande verrouillée, aucune proposition en attente) pour une demande « Choisir mon professionnel »."""
    if req.offers.filter(status=MissionOffer.QUOTED).exists():
        if req.status != MissionRequest.QUOTING:
            req.status, req.quote_deadline = MissionRequest.QUOTING, now + timedelta(hours=config.quote_window_hours)
            req.save(update_fields=["status", "quote_deadline", "updated_at"])
        return
    if req.status != MissionRequest.SEARCHING:
        return
    last = req.offers.filter(targeted=True).order_by("-wave", "-id").first()
    reason = "n'a pas répondu à temps" if last is not None and last.status == MissionOffer.EXPIRED else "n'est pas disponible pour cette demande"
    req.status = MissionRequest.AWAITING
    req.version += 1
    req.save(update_fields=["status", "version", "updated_at"])
    S.log(req, "awaiting", offer=last, reason=reason)
    rid = req.pk
    transaction.on_commit(lambda: _notify_choice(rid, reason))


def _notify_choice(request_id: int, reason: str) -> None:
    from flash import notify

    notify.choice_needed(request_id, reason)


def close_stale_awaiting(now=None) -> int:
    """Une demande en attente du choix du client depuis plus de `quote_window_hours` est close (le client est prévenu)."""
    now = now or timezone.now()
    config = DispatchConfig.get_solo()
    closed = 0
    for rid in MissionRequest.objects.filter(status=MissionRequest.AWAITING,
                                             updated_at__lt=now - timedelta(hours=config.quote_window_hours)).values_list("pk", flat=True):
        with transaction.atomic():
            req = MissionRequest.objects.select_for_update(of=("self",)).get(pk=rid)
            if req.status != MissionRequest.AWAITING:
                continue
            S._close(req, MissionRequest.UNFULFILLED, "Aucun choix du client dans le délai.", now)
            S.log(req, "unfulfilled", reason="awaiting_choice_elapsed")
            transaction.on_commit(lambda r=rid: S._notify_unfulfilled(r))
            closed += 1
    return closed


def start_direct(request_id: int, target: User) -> None:
    config = DispatchConfig.get_solo()
    now = timezone.now()
    with transaction.atomic():
        req = MissionRequest.objects.select_for_update(of=("self",)).select_related("category").get(pk=request_id)
        if req.status == MissionRequest.SEARCHING and not req.offers.exists():
            send_targeted(req, target, config, now)


# ═══ Changer de mode ════════════════════════════════════════════════════════════════════════════════════════════════════

def switch(request_id: int, client, to: str, *, target_id=None, expected_version=None, confirm: bool = False, now=None) -> MissionRequest:
    """Bascule AUTO ⇄ DIRECT sur la MÊME demande. Verrou sur la demande (comme l'acceptation) : les propositions en attente sont
    retirées avant toute nouvelle proposition ; une acceptation arrivée avant la bascule l'emporte (la bascule est alors refusée)."""
    if to not in (MissionRequest.AUTO, MissionRequest.DIRECT):
        raise FlashError("invalid_mode", "Mode inconnu : « auto » ou « direct ».")
    if not confirm:
        raise FlashError("confirmation_required", "Confirmez le changement : la proposition en cours sera retirée (les devis reçus restent "
                                                  "valables).", 400)
    now = now or timezone.now()
    config = DispatchConfig.get_solo()
    with transaction.atomic():
        req = MissionRequest.objects.select_for_update(of=("self",)).select_related("category").filter(pk=request_id, client=client).first()
        if req is None:
            raise FlashError("not_found", "Demande introuvable.", 404)
        if req.status == MissionRequest.ASSIGNED:
            raise FlashError("already_assigned", "Un professionnel a déjà accepté : la demande est attribuée.", 409, booking=req.booking_id)
        if not req.is_open:
            raise FlashError("request_closed", "Cette demande n'est plus ouverte : relancez-la.", 409)
        if expected_version is not None and int(expected_version) != req.version:
            raise FlashError("version_conflict", "La demande a changé entre-temps : rechargez-la.", 409, version=req.version)
        before = req.matching
        pro = None
        if to == MissionRequest.DIRECT:
            pro = validate_target(client, target_id, req, config, now)
            if req.offers.filter(handyman=pro).exists():
                raise FlashError("already_contacted", f"{_public_name(pro)} a déjà reçu cette demande : choisissez un autre professionnel.", 409)
        elif before == MissionRequest.AUTO and req.status == MissionRequest.SEARCHING:
            return req   # déjà en Smart Dispatch : rien à faire (rejeu)
        pending = list(req.offers.filter(status=MissionOffer.PENDING).values_list("pk", flat=True))
        if pending:
            MissionOffer.objects.filter(pk__in=pending).update(status=MissionOffer.WITHDRAWN)
            transaction.on_commit(lambda ids=pending: S._closed(ids))
        req.matching, req.target = to, pro
        req.switches += 1
        req.version += 1
        req.status = MissionRequest.SEARCHING
        req.save(update_fields=["matching", "target", "switches", "version", "status", "updated_at"])
        S.log(req, "switched", actor=client, **{"from": before, "to": to, "target": pro.pk if pro else None, "withdrawn": pending})
        if pro is not None:
            send_targeted(req, pro, config, now)
        else:
            rid = req.pk
            transaction.on_commit(lambda: S.launch_wave(rid))
    req.refresh_from_db()
    return req


# ═══ Favoris ════════════════════════════════════════════════════════════════════════════════════════════════════════════

def favorites(client, request=None) -> List[Dict]:
    rows = []
    for fav in FavoriteHandyman.objects.filter(client=client).select_related("handyman", "handyman__handyman_profile").order_by("-created_at"):
        profile = getattr(fav.handyman, "handyman_profile", None)
        if profile is None:
            continue
        card = pro_card(profile, request=request, favorite=True)
        card["bookable"] = is_publishable(profile)
        card["available_now"] = bool(profile.online) and card["bookable"]
        card["trades"] = sorted({c for c in Service.objects.filter(handyman=fav.handyman, is_active=True)
                                 .values_list("category__name", flat=True)})
        rows.append(card)
    return rows


def add_favorite(client, pro_id) -> FavoriteHandyman:
    pro = User.objects.filter(pk=pro_id).select_related("handyman_profile").first() if str(pro_id or "").isdigit() else None
    profile = getattr(pro, "handyman_profile", None) if pro else None
    if profile is None or not is_publishable(profile):
        raise FlashError("pro_unavailable", "Ce professionnel n'est pas disponible sur Tratra.", 404)
    if pro.pk == client.pk:
        raise FlashError("self_favorite", "Vous ne pouvez pas vous ajouter vous-même.", 400)
    fav, _ = FavoriteHandyman.objects.get_or_create(client=client, handyman=pro)
    return fav


def remove_favorite(client, pro_id) -> None:
    FavoriteHandyman.objects.filter(client=client, handyman_id=pro_id).delete()
