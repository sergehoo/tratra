"""Calcul déterministe des frais de déplacement (aller-retour prestataire ↔ lieu de mission), côté serveur uniquement.

Règles : activation et tarifs viennent de la configuration (rien en dur) ; distance routière (OSRM configuré) ; sous le seuil = 0 ;
au-delà, tarif de la tranche horaire applicable (heure d'Abidjan, jour, zone) ; sans tarif applicable ou sans distance => forfait de
secours (signalé) ; jamais de facturation du retour en double : le mode de calcul fixe UNE fois le multiplicateur. L'adresse privée du
prestataire n'apparaît dans aucun résultat."""
import unicodedata
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.utils import timezone

from transport.models import TransportBand, TransportConfig

TZ = ZoneInfo("Africa/Abidjan")  # fuseau de référence des tranches, indépendamment du fuseau du serveur
Point = Tuple[float, float]


def _norm(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (text or "").lower()) if unicodedata.category(c) != "Mn").strip()


def local(when: datetime) -> datetime:
    if timezone.is_naive(when):
        when = timezone.make_aware(when, TZ)
    return when.astimezone(TZ)


def road_distance_km(origin: Point, dest: Point) -> Optional[float]:
    """Distance routière en km via le service d'itinéraire configuré ; None s'il est indisponible (jamais une estimation à vol d'oiseau)."""
    from live.routing import osrm_route

    key = "transport:dist:%.4f,%.4f:%.4f,%.4f" % (*origin, *dest)
    hit = cache.get(key)
    if hit is not None:
        return hit or None
    route = osrm_route(origin, dest)
    km = round(route["distance_m"] / 1000, 3) if route and route.get("distance_m") is not None else None
    if km is not None:
        cache.set(key, km, 3600)
    return km


def _band_valid(b: TransportBand, day: date) -> bool:
    return b.is_active and (b.valid_from is None or b.valid_from <= day) and (b.valid_to is None or day <= b.valid_to)


def find_band(when: datetime, commune: str = "", city: str = "") -> Optional[TransportBand]:
    """Tranche applicable : jour + heure locale ; une tranche de zone l'emporte sur une tranche générale."""
    at = local(when)
    names = {_norm(commune), _norm(city)} - {""}
    candidates = []
    for b in TransportBand.objects.filter(is_active=True).select_related("zone"):
        if not _band_valid(b, at.date()) or at.weekday() not in (b.weekdays or []) or not (b.start_time <= at.time().replace(tzinfo=None) < b.end_time):
            continue
        if b.zone_id:
            if not b.zone.is_active or not names & {_norm(c) for c in (b.zone.communes or [])}:
                continue
            candidates.append((0, b.id, b))
        else:
            candidates.append((1, b.id, b))
    return min(candidates, key=lambda t: t[:2])[2] if candidates else None


def _round(amount: Decimal, cfg: TransportConfig) -> int:
    step = Decimal(max(cfg.rounding_step, 1))
    mode = {"up": ROUND_CEILING, "down": ROUND_FLOOR}.get(cfg.rounding_method, ROUND_HALF_UP)
    return int((amount / step).to_integral_value(rounding=mode) * step)


def _config_active(cfg: TransportConfig, day: date) -> bool:
    return cfg.enabled and (cfg.effective_from is None or cfg.effective_from <= day)


def compute(cfg: TransportConfig, *, distance_km: Optional[float], when: datetime, commune: str = "", city: str = "", needs_travel: bool = True) -> Dict:
    """Détail complet d'un calcul. `amount` est en unités de la devise (XOF : entier)."""
    at = local(when)
    base = {"version": cfg.version, "mode": cfg.mode, "currency": cfg.currency, "threshold_km": float(cfg.threshold_km), "slot": at.isoformat(),
            "distance_km": distance_km, "distance_source": "road" if distance_km is not None else "unavailable", "distance_unavailable": distance_km is None,
            "band": None, "multiplier": None, "billable_km": None, "raw_amount": None, "fallback": False, "fallback_reason": None,
            "applicable": True, "reason": None, "amount": 0}
    if not needs_travel:
        return {**base, "applicable": False, "reason": "no_travel"}
    if not _config_active(cfg, at.date()):
        return {**base, "applicable": False, "reason": "disabled"}
    if distance_km is not None and Decimal(str(distance_km)) <= cfg.threshold_km:
        return {**base, "reason": "within_threshold"}
    band = find_band(when, commune, city) if distance_km is not None else None
    if distance_km is None or band is None:
        # Forfait de secours : ne s'applique qu'aux missions avec déplacement ; la raison est toujours indiquée.
        return {**base, "fallback": True, "fallback_reason": "distance_unavailable" if distance_km is None else "no_applicable_rate",
                "reason": "fallback_flat", "amount": int(cfg.fallback_flat_amount)}
    multiplier = Decimal(2) if cfg.mode == TransportConfig.ROUND_TRIP_BILLED else Decimal(1)   # le retour est compté UNE seule fois
    billable = Decimal(str(distance_km)) * multiplier
    raw = billable * band.rate_per_km
    return {**base, "band": {"id": band.pk, "name": band.name, "rate_per_km": float(band.rate_per_km), "start": band.start_time.strftime("%H:%M"),
                             "end": band.end_time.strftime("%H:%M")},
            "multiplier": int(multiplier), "billable_km": float(billable), "raw_amount": float(raw), "amount": _round(raw, cfg), "reason": "rate"}


def provider_origin(handyman) -> Optional[Point]:
    """Point de départ AUTORISÉ du prestataire : son point de service s'il l'a défini, sinon les coordonnées de son adresse principale."""
    profile = getattr(handyman, "handyman_profile", None)
    loc = getattr(profile, "location", None)
    if loc is not None:
        return (loc.y, loc.x)
    from handy.models import UserAddress

    a = UserAddress.objects.filter(user=handyman, is_primary=True, latitude__isnull=False, longitude__isnull=False).first()
    return (float(a.latitude), float(a.longitude)) if a else None


def _distance(handyman, destination: Optional[Point]) -> Optional[float]:
    if destination is None:
        return None
    origin = provider_origin(handyman)
    return road_distance_km(origin, destination) if origin else None


def quote(*, handyman, destination: Optional[Point], when: datetime, commune: str = "", city: str = "", needs_travel: bool = True) -> Dict:
    cfg = TransportConfig.current()
    km = _distance(handyman, destination) if needs_travel and _config_active(cfg, local(when).date()) else None
    return compute(cfg, distance_km=km, when=when, commune=commune, city=city, needs_travel=needs_travel)


def _next_start(b: TransportBand, now: datetime) -> Optional[datetime]:
    """Prochain début de tranche (heure d'Abidjan) dans les 14 jours."""
    base = local(now)
    for i in range(0, 15):
        day = (base + timedelta(days=i)).date()
        if not _band_valid(b, day) or day.weekday() not in (b.weekdays or []):
            continue
        start = datetime.combine(day, b.start_time, tzinfo=TZ)
        if start > base:
            return start
    return None


def suggestions(*, handyman, destination: Optional[Point], now: datetime, commune: str = "", city: str = "", needs_travel: bool = True) -> List[Dict]:
    """Créneaux proposés au client avec le transport RÉELLEMENT calculé (immédiat, demain matin, heures creuses, heures de pointe).
    Un créneau n'apparaît que s'il existe réellement dans la configuration ; aucun montant fictif."""
    cfg = TransportConfig.current()
    if not needs_travel or not _config_active(cfg, local(now).date()):
        return []
    km = _distance(handyman, destination)
    out: List[Dict] = []

    def add(key: str, label: str, when: datetime):
        q = compute(cfg, distance_km=km, when=when, commune=commune, city=city, needs_travel=True)
        out.append({"key": key, "label": label, "starts_at": local(when).isoformat(), "amount": q["amount"], "fallback": q["fallback"],
                    "distance_unavailable": q["distance_unavailable"], "band": q["band"]["name"] if q["band"] else None})

    add("now", "Maintenant", now)
    bands = list(TransportBand.objects.filter(is_active=True).select_related("zone"))
    tomorrow = local(now).date() + timedelta(days=1)
    morning = sorted((b for b in bands if b.start_time.hour < 12 and _band_valid(b, tomorrow) and tomorrow.weekday() in (b.weekdays or [])), key=lambda b: b.start_time)
    if morning:
        add("tomorrow_morning", "Demain matin", datetime.combine(tomorrow, morning[0].start_time, tzinfo=TZ))
    if km is not None and bands:
        priced = [(b, _next_start(b, now)) for b in bands]
        priced = [(b, s) for b, s in priced if s is not None]
        if priced:
            cheapest, dearest = min(priced, key=lambda t: t[0].rate_per_km), max(priced, key=lambda t: t[0].rate_per_km)
            add("off_peak", "Heures creuses", cheapest[1])
            if dearest[0].rate_per_km != cheapest[0].rate_per_km:
                add("peak", "Heures de pointe", dearest[1])
    return out
