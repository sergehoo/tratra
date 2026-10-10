"""Règles métier du suivi en direct : jalons, consentements, positions, itinéraire, instantané par participant.

Toute autorisation est décidée ici (côté serveur), jamais par le client :
- seuls le client et l'artisan de la réservation participent ; un tiers ne voit rien (404) ;
- l'artisan n'est localisé que de « Je suis en route » (consentement explicite) jusqu'à son arrivée ;
- le client ne partage sa position que s'il l'a choisi, et peut la retirer à tout moment (positions effacées) ;
- aucune position n'est acceptée hors d'une mission confirmée, dans sa fenêtre, ni après l'arrivée."""
from datetime import datetime, timedelta
from typing import Dict, Optional

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from handy.eligibility import is_publishable
from handy.models import Booking, HandymanProfile
from live import routing
from live.models import LivePosition, TrackingSession
from trust.models import audit

LIVE_OPENS_BEFORE = timedelta(hours=3)     # le suivi s'ouvre peu avant l'heure prévue…
LIVE_CLOSES_AFTER = timedelta(hours=12)    # …et se ferme quelques heures après
STALE_AFTER = 90                            # secondes : au-delà, la position est signalée comme ancienne
MAX_POSITION_AGE = timedelta(seconds=120)   # une mesure plus vieille est refusée (réseau perdu, appareil figé)
MAX_FUTURE_SKEW = timedelta(seconds=60)
MIN_INTERVAL = 2                            # secondes entre deux positions d'un même participant
MAX_KEPT = 300                              # positions conservées par participant et par mission
ROUTE_REFRESH = timedelta(seconds=30)
ROUTE_MOVE_M = 150
ARRIVAL_MAX_DISTANCE_M = 500                # au-delà, l'arrivée déclarée n'est pas créditée en ponctualité


class LiveError(Exception):
    def __init__(self, code: str, detail: str, status: int = 400):
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status

    def payload(self) -> Dict:
        return {"code": self.code, "detail": self.detail}


# ---- Rôles et phases ----------------------------------------------------------------------------------

def role_of(booking: Booking, user) -> Optional[str]:
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    if booking.handyman_id == user.id:
        return LivePosition.ARTISAN
    if booking.client_id == user.id:
        return LivePosition.CLIENT
    return None


def get_session(booking: Booking) -> TrackingSession:
    session, _ = TrackingSession.objects.get_or_create(booking=booking)
    return session


def phase_of(booking: Booking, session: TrackingSession) -> str:
    """pending | confirmed | en_route | arrived | in_progress | completed | cancelled."""
    if booking.status != "confirmed":
        return booking.status
    if session.arrived_at:
        return "arrived"
    if session.en_route_at:
        return "en_route"
    return "confirmed"


def window_open(booking: Booking, now=None) -> bool:
    now = now or timezone.now()
    return booking.booking_date - LIVE_OPENS_BEFORE <= now <= booking.booking_date + LIVE_CLOSES_AFTER


def _point(lat: float, lng: float) -> Point:
    return Point(lng, lat, srid=4326)


def _latest(session: TrackingSession, role: str) -> Optional[LivePosition]:
    return session.positions.filter(role=role).first()


def destination(booking: Booking, session: TrackingSession, now=None):
    """Lieu d'intervention : coordonnées de la réservation, sinon position partagée du client (récente)."""
    if booking.job_location:
        return {"lat": booking.job_location.y, "lng": booking.job_location.x, "source": "booking"}
    now = now or timezone.now()
    if session.client_sharing:
        p = _latest(session, LivePosition.CLIENT)
        if p and (now - p.captured_at).total_seconds() <= 300:
            return {"lat": p.loc.y, "lng": p.loc.x, "source": "client_position"}
    return None


# ---- Actions ----------------------------------------------------------------------------------------------

def _require_participant(booking, user) -> str:
    role = role_of(booking, user)
    if role is None:
        raise LiveError("not_found", "Réservation introuvable.", 404)
    return role


def start_route(booking: Booking, user, *, consent: bool) -> TrackingSession:
    """« Je suis en route » : l'artisan consent explicitement à partager sa position jusqu'à son arrivée."""
    role = _require_participant(booking, user)
    if role != LivePosition.ARTISAN:
        raise LiveError("forbidden", "Seul l'artisan de la réservation peut démarrer le trajet.", 403)
    if consent is not True:
        raise LiveError("consent_required", "Vous devez accepter de partager votre position avec le client pendant "
                                            "le trajet.")
    if booking.status != "confirmed":
        raise LiveError("booking_not_confirmed", "Le trajet n'est possible que pour une mission confirmée.", 409)
    if not window_open(booking):
        raise LiveError("outside_window", "Le suivi s'ouvre quelques heures avant l'heure prévue de l'intervention.",
                        409)
    profile = HandymanProfile.objects.select_related("user").filter(user_id=user.id).first()
    if profile is None or not is_publishable(profile):
        raise LiveError("not_verified", "Votre identité n'est pas (ou plus) vérifiée : le suivi est indisponible.", 409)
    now = timezone.now()
    with transaction.atomic():
        session = TrackingSession.objects.select_for_update().get_or_create(booking=booking)[0]
        if session.arrived_at:
            raise LiveError("already_arrived", "Vous avez déjà indiqué votre arrivée.", 409)
        session.artisan_sharing, session.artisan_consent_at = True, now
        session.en_route_at = session.en_route_at or now
        session.save()
        audit("live.en_route", actor=user, target=booking, target_type="booking")
    return session


def arrive(booking: Booking, user) -> TrackingSession:
    """« Je suis arrivé » : fin du partage de position (artisan et client). Distance au lieu conservée pour l'audit."""
    role = _require_participant(booking, user)
    if role != LivePosition.ARTISAN:
        raise LiveError("forbidden", "Seul l'artisan de la réservation peut indiquer son arrivée.", 403)
    if booking.status != "confirmed":
        raise LiveError("booking_not_confirmed", "L'arrivée ne peut être indiquée que pour une mission confirmée.", 409)
    now = timezone.now()
    with transaction.atomic():
        session = TrackingSession.objects.select_for_update().get_or_create(booking=booking)[0]
        if session.arrived_at:
            return session  # idempotent
        dest, last = destination(booking, session, now), _latest(session, LivePosition.ARTISAN)
        if dest and last and (now - last.captured_at).total_seconds() <= 300:
            session.arrival_distance_m = int(routing.haversine_m(last.loc.y, last.loc.x, dest["lat"], dest["lng"]))
        session.arrived_at = now
        session.artisan_sharing = session.client_sharing = False
        session.save()
        audit("live.arrived", actor=user, target=booking, target_type="booking", distance_m=session.arrival_distance_m)
    return session


def set_consent(booking: Booking, user, share: bool) -> TrackingSession:
    """Consentement (retirable) au partage de position. Retirer = arrêter ET effacer ses positions."""
    role = _require_participant(booking, user)
    now = timezone.now()
    with transaction.atomic():
        session = TrackingSession.objects.select_for_update().get_or_create(booking=booking)[0]
        phase = phase_of(booking, session)
        if share:
            if role == LivePosition.CLIENT:
                if phase not in ("confirmed", "en_route") or not window_open(booking, now):
                    raise LiveError("sharing_not_allowed", "Le partage de position n'est possible que pendant "
                                                           "l'intervention, avant l'arrivée de l'artisan.", 409)
                session.client_sharing, session.client_consent_at = True, now
            else:
                if phase != "en_route":
                    raise LiveError("sharing_not_allowed", "Indiquez d'abord « Je suis en route » pour partager votre "
                                                           "position.", 409)
                session.artisan_sharing, session.artisan_consent_at = True, now
        else:
            if role == LivePosition.CLIENT:
                session.client_sharing = False
            else:
                session.artisan_sharing = False
            session.positions.filter(role=role).delete()
            if role == LivePosition.ARTISAN:
                session.route_polyline, session.route_eta_seconds, session.route_distance_m = [], None, None
                session.route_source, session.route_origin = "", None
        session.save()
        audit("live.consent", actor=user, target=booking, target_type="booking", role=role, share=share)
    return session


def _clean(value, lo, hi, name):
    if value in (None, ""):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise LiveError("invalid_position", f"{name} invalide.")
    if v != v or not (lo <= v <= hi):
        raise LiveError("invalid_position", f"{name} invalide.")
    return v


def record_position(booking: Booking, user, data: Dict) -> LivePosition:
    role = _require_participant(booking, user)
    now = timezone.now()
    session = get_session(booking)
    phase = phase_of(booking, session)
    if role == LivePosition.ARTISAN:
        if phase != "en_route" or not session.artisan_sharing:
            raise LiveError("tracking_not_active", "Le suivi n'est pas actif : indiquez « Je suis en route » pour "
                                                   "partager votre position.", 409)
    else:
        if (not session.client_sharing or phase not in ("confirmed", "en_route") or not window_open(booking, now)):
            raise LiveError("tracking_not_active", "Vous n'avez pas activé le partage de votre position.", 409)

    lat = _clean(data.get("lat"), -90, 90, "Latitude")
    lng = _clean(data.get("lng"), -180, 180, "Longitude")
    if lat is None or lng is None:
        raise LiveError("invalid_position", "lat et lng sont requis.")
    accuracy = _clean(data.get("accuracy"), 0, 100000, "Précision")
    speed = _clean(data.get("speed"), 0, 200, "Vitesse")
    heading = _clean(data.get("heading"), 0, 360, "Cap")
    captured_at = now
    if data.get("captured_at"):
        parsed = parse_datetime(str(data["captured_at"]))
        if parsed is None:
            raise LiveError("invalid_position", "captured_at invalide.")
        captured_at = parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
    if captured_at < now - MAX_POSITION_AGE:
        raise LiveError("stale_position", "Cette position est trop ancienne et a été ignorée.")
    if captured_at > now + MAX_FUTURE_SKEW:
        raise LiveError("invalid_position", "Horodatage dans le futur.")
    if not cache.add(f"live:{booking.id}:{role}", 1, MIN_INTERVAL):
        raise LiveError("too_frequent", "Positions trop rapprochées.", 429)

    position = LivePosition.objects.create(session=session, role=role, loc=_point(lat, lng), accuracy=accuracy,
                                           speed=speed, heading=heading, captured_at=captured_at)
    _trim(session, role)
    if role == LivePosition.ARTISAN:
        refresh_route(booking, session, position, now)
    return position


def _trim(session: TrackingSession, role: str) -> None:
    if session.positions.filter(role=role).count() > MAX_KEPT + 60:
        keep = list(session.positions.filter(role=role).values_list("pk", flat=True)[:MAX_KEPT])
        session.positions.filter(role=role).exclude(pk__in=keep).delete()


def refresh_route(booking: Booking, session: TrackingSession, position: LivePosition, now=None) -> None:
    """Recalcule l'itinéraire / l'ETA si nécessaire (toutes les 30 s ou après 150 m de déplacement)."""
    now = now or timezone.now()
    dest = destination(booking, session, now)
    if dest is None:
        if session.route_updated_at:
            TrackingSession.objects.filter(pk=session.pk).update(route_polyline=[], route_eta_seconds=None,
                                                                 route_distance_m=None, route_source="")
        return
    moved = (routing.haversine_m(position.loc.y, position.loc.x, session.route_origin.y, session.route_origin.x)
             if session.route_origin else None)
    if (session.route_updated_at and now - session.route_updated_at < ROUTE_REFRESH
            and (moved is None or moved < ROUTE_MOVE_M)):
        return
    route = routing.compute_route((position.loc.y, position.loc.x), (dest["lat"], dest["lng"]))
    TrackingSession.objects.filter(pk=session.pk).update(
        route_polyline=route["polyline"], route_eta_seconds=route["eta_seconds"], route_distance_m=route["distance_m"],
        route_source=route["source"], route_updated_at=now, route_origin=position.loc)
    session.route_polyline, session.route_eta_seconds = route["polyline"], route["eta_seconds"]
    session.route_distance_m, session.route_source = route["distance_m"], route["source"]
    session.route_updated_at, session.route_origin = now, position.loc


def end_session(booking: Booking) -> None:
    """Mission terminée ou annulée : plus aucun partage ; les positions seront purgées (live.tasks)."""
    TrackingSession.objects.filter(booking=booking).update(artisan_sharing=False, client_sharing=False)


# ---- Instantané (ce que voit CHAQUE participant) ---------------------------------------------------------------

def _pos(p: Optional[LivePosition], now) -> Optional[Dict]:
    if p is None:
        return None
    age = max(0, int((now - p.captured_at).total_seconds()))
    return {"lat": p.loc.y, "lng": p.loc.x, "accuracy": p.accuracy, "speed": p.speed, "heading": p.heading,
            "captured_at": p.captured_at, "age_seconds": age, "stale": age > STALE_AFTER}


def snapshot(booking: Booking, user) -> Dict:
    role = _require_participant(booking, user)
    now = timezone.now()
    session = get_session(booking)
    phase = phase_of(booking, session)
    open_ = booking.status in ("confirmed", "in_progress") and window_open(booking, now)
    live = phase == "en_route" and session.artisan_sharing
    artisan_pos = _pos(_latest(session, LivePosition.ARTISAN), now) if live else None
    client_pos = (_pos(_latest(session, LivePosition.CLIENT), now)
                  if session.client_sharing and phase in ("confirmed", "en_route") else None)
    dest = destination(booking, session, now) if phase in ("confirmed", "en_route", "arrived") else None
    route = None
    if phase == "en_route" and session.route_updated_at and session.route_eta_seconds is not None:
        route = {"eta_seconds": session.route_eta_seconds, "eta_minutes": max(1, round(session.route_eta_seconds / 60)),
                 "distance_m": session.route_distance_m, "polyline": session.route_polyline,
                 "source": session.route_source, "updated_at": session.route_updated_at}
    is_artisan = role == LivePosition.ARTISAN
    return {
        "booking_id": booking.id,
        "role": role,
        "phase": phase,
        "status": booking.status,
        "server_time": now,
        "window_open": open_,
        "stale_after_seconds": STALE_AFTER,
        "consent": {"artisan": session.artisan_sharing, "client": session.client_sharing},
        "can": {
            "start_route": is_artisan and phase == "confirmed" and open_,
            "arrive": is_artisan and phase in ("confirmed", "en_route") and open_,
            "share_position": (phase in ("confirmed", "en_route") and open_) if not is_artisan else phase == "en_route",
        },
        "artisan": {"sharing": session.artisan_sharing, "position": artisan_pos},
        "client": {"sharing": session.client_sharing,
                   "position": client_pos if (role == LivePosition.CLIENT or session.client_sharing) else None},
        "destination": dest,
        "route": route,
        "milestones": {"en_route_at": session.en_route_at, "arrived_at": session.arrived_at},
    }
