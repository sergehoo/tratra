"""Temps réel Tratra Flash : l'état d'une recherche (phase, rayon, compteurs) part sur la WebSocket du membre (`ws/inbox/`, déjà ouverte
par l'application) à chaque évènement du journal. Le WebSocket n'est qu'un confort : l'API (`GET /flash/requests/<id>/`) reste la
référence et sert la reprise (reconnexion, retour au premier plan, réouverture de l'application). `seq` (dernier évènement du journal)
est croissant : un message en double ou arrivé en retard est ignoré par l'application. Aucune position de professionnel n'est diffusée."""
import logging
from datetime import timedelta

from django.utils import timezone

from flash.models import DispatchConfig, DispatchEvent, MissionOffer, MissionRequest

logger = logging.getLogger(__name__)

PHASE_LABELS = {
    "search": "Recherche en cours", "extension": "Élargir la recherche ?", "proposals": "Propositions reçues",
    "selection": "Choisissez une proposition", "confirmed": "Confirmé", "unavailable": "Aucun professionnel disponible",
    "cancelled": "Annulée", "awaiting": "Votre choix est attendu",
}


def radius_label(meters: int) -> str:
    if not meters:
        return "Votre commune"
    return f"{meters} m" if meters < 1000 else f"{str(round(meters / 1000, 1)).rstrip('0').rstrip('.').replace('.', ',')} km"


def counts(offers) -> dict:
    st = [o.status for o in offers]
    # `proposals` : propositions de prix REÇUES (le compteur ne retombe pas après le choix) ; `open_proposals` : encore choisissables.
    return {"contacted": len(st), "pending": st.count(MissionOffer.PENDING),
            "responses": sum(1 for s in st if s in MissionOffer.ANSWERED),
            "proposals": sum(1 for o in offers if o.quote_amount is not None),
            "open_proposals": sum(1 for o in offers if o.status in MissionOffer.PROPOSALS),
            "declined": st.count(MissionOffer.DECLINED), "no_answer": st.count(MissionOffer.EXPIRED)}


def search_payload(req: MissionRequest, offers=None, *, config: DispatchConfig = None, now=None) -> dict:
    """Bloc « recherche » commun à l'API et au WebSocket : phase, rayon, paliers permis, compteurs exacts, échéances."""
    from flash import services

    config = config or DispatchConfig.current()
    now = now or timezone.now()
    offers = list(req.offers.all()) if offers is None else offers
    c = counts(offers)
    c["eligible"] = max(req.eligible_count, c["contacted"])
    prog = services.progressive(req, config)
    steps = config.steps_km() if prog else []
    consent = req.status == MissionRequest.SEARCHING and req.consent_asked_at is not None and not req.allow_far
    phase = {MissionRequest.CANCELLED: "cancelled", MissionRequest.UNFULFILLED: "unavailable", MissionRequest.ASSIGNED: "confirmed",
             MissionRequest.QUOTING: "selection", MissionRequest.AWAITING: "awaiting"}.get(req.status)
    if phase is None:
        phase = "extension" if consent else "proposals" if c["open_proposals"] else "search"
    limit = services.limit_km(req, config) if prog else 0
    last = req.events.order_by("-id").values_list("id", flat=True).first() or 0
    consent_until = req.consent_asked_at + timedelta(seconds=config.far_consent_wait_seconds) if consent else None
    available = ((req.events.filter(kind="consent_asked").order_by("-id").values_list("data", flat=True).first() or {}).get("available")
                 if consent else None)
    return {
        "seq": last, "phase": phase, "phase_label": PHASE_LABELS[phase], "progressive": prog,
        "radius_m": req.radius_m, "radius_label": radius_label(req.radius_m),
        "steps_m": [int(round(km * 1000)) for km in steps if km <= limit],
        "far": {"threshold_km": config.far_radius_km, "allowed": req.allow_far, "needs_consent": consent,
                "possible": prog and config.trade_goes_far(req.category) and any(km > config.far_radius_km for km in steps),
                "consent_until": consent_until, "available_beyond": available},
        "next_step_in": max(0, int((req.next_step_at - now).total_seconds())) if req.next_step_at and req.is_open else None,
        "counts": c,
    }


def live_payload(req: MissionRequest) -> dict:
    return {"type": "flash_request", "id": req.pk, "status": req.status, "status_label": req.get_status_display(), "version": req.version,
            "search": search_payload(req)}


def request_changed(request_id: int) -> None:
    """Diffuse l'état d'une recherche à son client. Jamais bloquant pour l'action métier (Redis coupé, etc.)."""
    from handy import inbox

    try:
        req = MissionRequest.objects.select_related("category", "category__parent").filter(pk=request_id).first()
        if req is not None:
            inbox.push([req.client_id], live_payload(req))
    except Exception:
        logger.warning("Diffusion temps réel Flash impossible (demande #%s)", request_id, exc_info=True)


def offer_changed(offer_id: int) -> None:
    """Le professionnel voit en direct une contre-offre ou la fermeture de sa proposition."""
    from handy import inbox

    try:
        offer = MissionOffer.objects.filter(pk=offer_id).only("handyman_id", "status", "counter_amount", "counter_expires_at").first()
        if offer is not None:
            inbox.push([offer.handyman_id], {"type": "flash_offer", "id": offer.pk, "status": offer.status,
                                             "counter_amount": int(offer.counter_amount) if offer.counter_amount is not None else None,
                                             "counter_expires_at": offer.counter_expires_at})
    except Exception:
        logger.warning("Diffusion temps réel Flash impossible (proposition #%s)", offer_id, exc_info=True)


QUIET = {"offer_sent", "seen"}      # évènements sans effet visible pour le client (une vague en produit un seul : « wave »)


def last_seq(request_id: int) -> int:
    return DispatchEvent.objects.filter(request_id=request_id).order_by("-id").values_list("id", flat=True).first() or 0
