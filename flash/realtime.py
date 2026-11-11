"""Temps réel Tratra Flash : l'état d'une recherche (phase, rayon, compteurs) part sur la WebSocket du membre (`ws/inbox/`, déjà ouverte
par l'application) à chaque évènement du journal. Le WebSocket n'est qu'un confort : l'API (`GET /flash/requests/<id>/`) reste la
référence et sert la reprise (reconnexion, retour au premier plan, réouverture de l'application).

`seq` (`MissionRequest.seq`) croît d'une unité à chaque évènement visible, sous le verrou de la ligne de la demande : deux transactions
concurrentes sont donc ordonnées, et un état lu APRÈS la ligne de la demande n'est jamais plus ancien que son `seq`. L'application ignore
un message en double, en retard ou dans le désordre (`seq` ≤ celui affiché) et toute lecture plus ancienne que l'état affiché.

Carte du client (`search.pros`) : un repère par professionnel SOLLICITÉ, à mesure des vagues — position approchée (jamais la
position exacte), pictogramme selon le genre déclaré, état de sa proposition. Aucune identité, aucun professionnel non sollicité."""
import logging
from datetime import timedelta

from django.db import connection
from django.utils import timezone

from flash.models import DispatchConfig, MissionOffer, MissionRequest

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


# État du repère sur la carte du client. Les propositions retirées, échues ou suivies d'un désistement n'y figurent plus.
MAP_STATES = {MissionOffer.PENDING: "contacted", MissionOffer.QUOTED: "proposal", MissionOffer.COUNTERED: "proposal",
              MissionOffer.ACCEPTED: "selected", MissionOffer.DECLINED: "declined", MissionOffer.EXPIRED: "no_answer"}
MAP_LIMIT = 40          # repères au plus (les plus récents) : la carte reste lisible et la charge utile bornée


def _approx(point, offer_id: int) -> dict:
    """Position APPROCHÉE d'un professionnel : arrondie à ≈ 110 m, puis décalée de quelques dizaines de mètres selon le numéro de la
    proposition (stable d'un message à l'autre ; deux professionnels voisins restent distincts). Jamais la position exacte."""
    dy, dx = ((offer_id * 7) % 9 - 4) * 0.0001, ((offer_id * 5) % 9 - 4) * 0.0001
    return {"lat": round(round(point.y, 3) + dy, 4), "lng": round(round(point.x, 3) + dx, 4)}


def map_points(req: MissionRequest, offers) -> list:
    """Repères de la carte du client : les professionnels sollicités (vague après vague), sans identité. Rien sans lieu d'intervention,
    ni sur une demande annulée ou sans suite ; une fois la mission attribuée, le seul professionnel retenu."""
    from handy.models import HandymanProfile

    if req.location is None or req.status in (MissionRequest.CANCELLED, MissionRequest.UNFULFILLED):
        return []
    shown = [o for o in offers if o.status in MAP_STATES and (req.status != MissionRequest.ASSIGNED or o.status == MissionOffer.ACCEPTED)]
    shown = sorted(shown, key=lambda o: o.pk)[-MAP_LIMIT:]
    if not shown:
        return []
    where = {uid: (loc or zone, gender) for uid, loc, zone, gender in HandymanProfile.objects.filter(
        user_id__in=[o.handyman_id for o in shown]).values_list("user_id", "location", "service_area__center", "user__gender")}
    points = []
    for o in shown:
        origin, gender = where.get(o.handyman_id, (None, ""))
        if origin is not None:      # ni position ni zone d'intervention déclarée : pas de repère (aucune position inventée)
            points.append({"id": o.pk, **_approx(origin, o.pk), "gender": gender or None, "state": MAP_STATES[o.status]})
    return points


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
    consent_until = req.consent_asked_at + timedelta(seconds=config.far_consent_wait_seconds) if consent else None
    available = ((req.events.filter(kind="consent_asked").order_by("-id").values_list("data", flat=True).first() or {}).get("available")
                 if consent else None)
    return {
        "seq": req.seq, "phase": phase, "phase_label": PHASE_LABELS[phase], "progressive": prog,
        "radius_m": req.radius_m, "radius_label": radius_label(req.radius_m),
        "steps_m": [int(round(km * 1000)) for km in steps if km <= limit],
        "far": {"threshold_km": config.far_radius_km, "allowed": req.allow_far, "needs_consent": consent,
                "possible": prog and config.trade_goes_far(req.category) and any(km > config.far_radius_km for km in steps),
                "consent_until": consent_until, "available_beyond": available},
        "next_step_in": max(0, int((req.next_step_at - now).total_seconds())) if req.next_step_at and req.is_open else None,
        "counts": c,
        "pros": map_points(req, offers),
    }


def live_payload(req: MissionRequest) -> dict:
    return {"type": "flash_request", "id": req.pk, "status": req.status, "status_label": req.get_status_display(), "version": req.version,
            "search": search_payload(req)}


def bump(request_id: int) -> int:
    """Incrémente le numéro de synchronisation (verrou de ligne tenu jusqu'à la fin de la transaction) et le renvoie."""
    with connection.cursor() as cur:
        cur.execute(f"UPDATE {MissionRequest._meta.db_table} SET seq = seq + 1 WHERE id = %s RETURNING seq", [request_id])
        row = cur.fetchone()
    return row[0] if row else 0


_pushed: dict = {}      # demande → dernier `seq` diffusé par ce processus (plusieurs évènements d'une même transaction : un seul envoi)


def request_changed(request_id: int) -> None:
    """Diffuse l'état d'une recherche à son client. Jamais bloquant pour l'action métier (Redis coupé, etc.)."""
    from handy import inbox

    try:
        req = MissionRequest.objects.select_related("category", "category__parent").filter(pk=request_id).first()
        if req is None or _pushed.get(request_id) == req.seq:
            return
        inbox.push([req.client_id], live_payload(req))
        if len(_pushed) > 5000:
            _pushed.clear()
        _pushed[request_id] = req.seq
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
