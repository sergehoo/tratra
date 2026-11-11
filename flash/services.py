"""Smart Dispatch : filtrage, classement expliqué, vagues, réponses et attribution atomique.

Filtrage (tout doit être vrai) : professionnel éligible (règle unique handy/eligibility.py : compte actif, KYC et profil validés), métier
(offre active ou compétence dans le métier ou ses prestations, expérience minimale du métier), zone (rayon autour du lieu, sinon même commune),
disponibilité (« Disponible » pour une mission immédiate, horaires déclarés, absences, réservations confirmées et planning des engagements),
pas de proposition déjà en attente ailleurs, jamais le client lui-même, jamais deux fois la même demande.

Classement : moyenne pondérée de critères entre 0 et 1 (`DispatchConfig`). Un critère sans historique suffisant prend la VALEUR NEUTRE (un
nouveau professionnel n'est jamais classé derrière à cause de son ancienneté) ; la répartition équitable favorise ceux qui ont eu peu de
missions récemment. Chaque proposition garde le détail du calcul (`score_detail`).

Refuser ou laisser expirer une proposition n'a AUCUNE conséquence sur la réputation. Seule mesure : après N propositions consécutives sans
réponse, le professionnel passe « Indisponible » (il est prévenu et peut revenir d'un geste) pour ne pas faire attendre les clients."""
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Dict, List, Optional

from django.contrib.gis.geos import Point
from django.db import IntegrityError, transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.db.models.functions import Lower, Trim
from django.utils import timezone

from flash.models import DispatchConfig, DispatchEvent, MissionOffer, MissionRequest
from handy import proximity
from handy.eligibility import is_orderable, orderable
from handy.models import AvailabilitySlot, Booking, HandymanProfile, Service, ServiceArea, ServiceCategory, TimeOff

logger = logging.getLogger(__name__)

ACCEPT_GRACE_SECONDS = 3          # latence réseau : une acceptation partie juste avant l'échéance reste valable
COMMUNE_KM = 5.0                  # recherche progressive : un pro sans position (même commune) n'est retenu qu'à partir de ce rayon
BUSY_BOOKING_STATUSES = ("confirmed", "in_progress")


class FlashError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra


def log(req: MissionRequest, kind: str, *, offer: Optional[MissionOffer] = None, actor=None, **data) -> DispatchEvent:
    """Journal (rien n'est effacé) ; chaque évènement visible part aussi en temps réel au client, APRÈS validation de la transaction."""
    event = DispatchEvent.objects.create(request=req, offer=offer, kind=kind, actor=actor, data=data)
    from flash import realtime

    if kind not in realtime.QUIET:
        req.seq = realtime.bump(req.pk)     # verrou de la ligne : les transactions concurrentes d'une même demande sont ordonnées
        rid = req.pk
        transaction.on_commit(lambda: realtime.request_changed(rid))
    return event


# ═══ Métier, zone, disponibilité ═══════════════════════════════════════════════════════════════════════════════════════

def category_family(category: ServiceCategory) -> List[int]:
    """Le métier demandé, ses prestations et (pour une prestation) son métier parent : une offre « Plomberie » couvre « Fuite d'eau »."""
    ids = {category.pk, *ServiceCategory.objects.filter(parent_id=category.pk).values_list("pk", flat=True)}
    if category.parent_id:
        ids.add(category.parent_id)
    return sorted(ids)


def required_experience(category: ServiceCategory) -> int:
    years = category.min_experience_years or 0
    if category.parent_id:
        years = max(years, category.parent.min_experience_years or 0)
    return years


def haversine_km(a: Point, b: Point) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a.x, a.y, b.x, b.y))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def _same_commune(profile: HandymanProfile, commune: str) -> bool:
    c = (commune or "").strip().lower()
    return bool(c) and c in {(profile.commune or "").strip().lower(), (profile.quartier or "").strip().lower()}


def zone_of(profile: HandymanProfile, req: MissionRequest, config: DispatchConfig, radius_km: Optional[float] = None):
    """(dans la zone ?, distance en km ou None). Position du pro, sinon centre de sa zone d'intervention ; à défaut, même commune.
    `radius_km` : palier courant de la recherche progressive (sinon le rayon fixe). La zone d'intervention du pro reste un plafond."""
    area = getattr(profile, "service_area", None)
    origin = profile.location or (area.center if area is not None else None)
    radius = radius_km or config.radius_km
    if area is not None and area.radius_km:
        radius = min(radius, float(area.radius_km))
    if req.location is not None and origin is not None:
        d = haversine_km(origin, req.location)
        return d <= radius, round(d, 2)
    if radius_km is not None and req.location is not None and radius_km < COMMUNE_KM:
        return False, None   # distance inconnue : la commune n'équivaut pas à un rayon de quelques centaines de mètres
    return _same_commune(profile, req.commune), None


def window(req: MissionRequest, config: DispatchConfig):
    start = req.scheduled_for
    return start, start + timedelta(minutes=config.mission_duration_minutes)


@dataclass
class Availability:
    """Disponibilités de PLUSIEURS professionnels sur le créneau d'une demande, lues en cinq requêtes au plus (au lieu de cinq par
    professionnel : à Abidjan, des centaines de professionnels d'un même métier sont dans le rayon)."""
    timeoff: set        # profils absents sur le créneau
    slots: Dict         # profil → horaires déclarés [(jour, début, fin)]
    busy: set           # comptes pris par une réservation confirmée ou en cours qui chevauche
    in_progress: set    # comptes ayant une mission en cours (demandes immédiates)
    engaged: set        # comptes pris par un engagement longue durée sur le créneau


def availability_batch(profiles, req: MissionRequest, config: DispatchConfig) -> Availability:
    start, end = window(req, config)
    pids, uids = [p.pk for p in profiles], [p.user_id for p in profiles]
    if not pids:
        return Availability(set(), {}, set(), set(), set())
    slots: Dict[int, list] = {}
    for pid, wd, s, e in AvailabilitySlot.objects.filter(handyman_id__in=pids).values_list("handyman_id", "weekday", "start_time", "end_time"):
        slots.setdefault(pid, []).append((wd, s, e))
    return Availability(
        timeoff=set(TimeOff.objects.filter(handyman_id__in=pids, start__lt=end, end__gt=start).values_list("handyman_id", flat=True)),
        slots=slots,
        busy=set(Booking.objects.filter(handyman_id__in=uids, status__in=BUSY_BOOKING_STATUSES, booking_date__lt=end,
                                        booking_date__gt=start - timedelta(minutes=config.mission_duration_minutes))
                 .values_list("handyman_id", flat=True)),
        in_progress=(set(Booking.objects.filter(handyman_id__in=uids, status="in_progress").values_list("handyman_id", flat=True))
                     if req.is_immediate else set()),
        engaged=_engaged(uids, timezone.localtime(start), timezone.localtime(end)),
    )


def availability_issue(profile: HandymanProfile, req: MissionRequest, config: DispatchConfig, now=None, *,
                       check_online: bool = True, batch: Optional[Availability] = None) -> Optional[str]:
    """Raison d'indisponibilité (texte) ou None. Règle absolue : aucune proposition immédiate à un professionnel « Indisponible ».
    `check_online=False` à l'acceptation : une proposition reçue reste acceptable même si le pro s'est mis en pause entre-temps.
    `batch` : lecture groupée déjà faite pour plusieurs professionnels (`availability_batch`)."""
    if check_online and req.is_immediate and not profile.online:
        return "Indisponible (bouton de disponibilité)"
    b = batch if batch is not None else availability_batch([profile], req, config)
    if profile.pk in b.timeoff:
        return "Absence déclarée"
    local = timezone.localtime(window(req, config)[0])
    slots = b.slots.get(profile.pk) or []
    if slots and not any(wd == local.weekday() and s <= local.time() < e for wd, s, e in slots):
        return "Hors de ses horaires"
    if profile.user_id in b.busy:
        return "Autre mission au même moment"
    if req.is_immediate and profile.user_id in b.in_progress:
        return "Mission en cours"
    if profile.user_id in b.engaged:
        return "Engagement en cours sur ce créneau"
    return None


def _engaged(user_ids: List[int], start, end) -> set:
    """Comptes dont le planning d'engagement longue durée (interventions prévues ou validées d'un contrat en vigueur) chevauche le créneau."""
    from engagements.models import EngagementContract, ScheduleEvent

    if not user_ids:
        return set()
    events = ScheduleEvent.objects.filter(contract__worker_id__in=user_ids, contract__status__in=EngagementContract.LIVE,
                                          kind__in=("shift", "overtime"), status__in=("planned", "approved"),
                                          date__lte=end.date()).filter(Q(end_date__isnull=True, date__gte=start.date()) | Q(end_date__gte=start.date()))
    busy = set()
    for worker, day, ev_start_time, ev_end_time in events.values_list("contract__worker_id", "date", "start_time", "end_time"):
        if worker in busy:
            continue
        if ev_start_time is None or ev_end_time is None:
            busy.add(worker)   # journée entière
            continue
        ev_start = timezone.make_aware(datetime.combine(day, ev_start_time))
        ev_end = timezone.make_aware(datetime.combine(day, ev_end_time))
        if ev_start < end and ev_end > start:
            busy.add(worker)
    return busy


# ═══ Classement ═════════════════════════════════════════════════════════════════════════════════════════════════════════

LABELS = {"distance": "Proximité", "trust": "Score Tratra Trust", "rating": "Note des clients",
          "reactivity": "Réactivité aux propositions", "fairness": "Répartition équitable"}


@dataclass
class History:
    """Historique de classement de PLUSIEURS professionnels, lu en trois requêtes (au lieu de quatre par professionnel)."""
    ratings: Dict       # compte → {"count", "average"} (avis retenus : le plus récent de chaque client)
    offers: Dict        # compte → [(statut, secondes de réponse)] des propositions closes sur 30 jours
    assigned: Dict      # compte → missions Tratra Flash obtenues ces 7 derniers jours


def history_batch(user_ids: List[int], now) -> History:
    from django.db.models import Count

    from handy.reviews import rating_counts

    if not user_ids:
        return History({}, {}, {})
    offers: Dict[int, list] = {}
    for uid, status, seconds in (MissionOffer.objects.filter(handyman_id__in=user_ids, sent_at__gte=now - timedelta(days=30))
                                 .exclude(status__in=(MissionOffer.PENDING, MissionOffer.WITHDRAWN))
                                 .values_list("handyman_id", "status", "response_seconds")):
        offers.setdefault(uid, []).append((status, seconds))
    assigned = dict(MissionRequest.objects.filter(assigned_to_id__in=user_ids, assigned_at__gte=now - timedelta(days=7)).order_by()
                    .values("assigned_to_id").annotate(n=Count("id")).values_list("assigned_to_id", "n"))
    return History(rating_counts(user_ids), offers, assigned)


def _reactivity(user_id: int, config: DispatchConfig, now, rows: Optional[list] = None) -> Dict:
    if rows is None:
        rows = list(MissionOffer.objects.filter(handyman_id=user_id, sent_at__gte=now - timedelta(days=30))
                    .exclude(status__in=(MissionOffer.PENDING, MissionOffer.WITHDRAWN)).values_list("status", "response_seconds"))
    answered = [s for st, s in rows if st in MissionOffer.ANSWERED]
    if len(rows) < config.min_sample:
        return {"value": None, "detail": f"Historique insuffisant ({len(rows)}/{config.min_sample})"}
    rate = len(answered) / len(rows)
    times = [s for s in answered if s is not None]
    speed = 1.0
    if times:
        med = median(times)
        speed = 1.0 if med <= 30 else max(0.0, 1.0 - (med - 30) / max(60, config.offer_timeout_seconds * 4))
    # Un refus rapide est une RÉPONSE : il compte comme une acceptation pour la réactivité (refuser n'est jamais pénalisé).
    return {"value": round(0.7 * rate + 0.3 * speed, 3),
            "detail": f"Répond à {round(rate * 100)} % des propositions" + (f", en {int(median(times))} s en médiane" if times else "")}


def _rating(user_id: int, config: DispatchConfig, s: Optional[Dict] = None) -> Dict:
    if s is None:
        from handy.reviews import review_stats

        s = review_stats(user_id)
    if s["count"] < config.min_sample or s["average"] is None:
        return {"value": None, "detail": f"Pas encore assez d'avis ({s['count']}/{config.min_sample})"}
    return {"value": round(s["average"] / 5, 3), "detail": f"{str(s['average']).replace('.', ',')}/5 sur {s['count']} avis"}


def _fairness(user_id: int, now, recent: Optional[int] = None) -> Dict:
    if recent is None:
        recent = MissionRequest.objects.filter(assigned_to_id=user_id, assigned_at__gte=now - timedelta(days=7)).count()
    return {"value": round(1 / (1 + recent), 3), "detail": f"{recent} mission(s) Tratra Flash obtenue(s) ces 7 derniers jours"}


def score(profile: HandymanProfile, distance_km: Optional[float], config: DispatchConfig, now, *, batch: Optional[History] = None) -> Dict:
    """Classement expliqué. `batch` : historique déjà lu pour plusieurs professionnels (`history_batch`)."""
    uid = profile.user_id
    measures = {
        "distance": ({"value": round(max(0.0, 1 - distance_km / config.radius_km), 3), "detail": f"{str(distance_km).replace('.', ',')} km"}
                     if distance_km is not None else {"value": None, "detail": "Même commune (distance inconnue)"}),
        "trust": ({"value": round(profile.trust_score / 100, 3), "detail": f"Score {profile.trust_score}/100"}
                  if profile.trust_score is not None else {"value": None, "detail": "Score pas encore publié"}),
        "rating": _rating(uid, config, batch.ratings.get(uid, {"count": 0, "average": None}) if batch else None),
        "reactivity": _reactivity(uid, config, now, batch.offers.get(uid, []) if batch else None),
        "fairness": _fairness(uid, now, batch.assigned.get(uid, 0) if batch else None),
    }
    weights = config.weights()
    total_w = sum(w for w in weights.values() if w > 0) or 1
    parts, total = [], 0.0
    for key, m in measures.items():
        w = weights[key]
        measured = m["value"] is not None
        value = m["value"] if measured else config.neutral_value
        pts = w * value / total_w
        total += pts
        parts.append({"key": key, "label": LABELS[key], "weight": w, "value": value, "measured": measured,
                      "points": round(100 * pts, 1), "detail": m["detail"] if measured else f"{m['detail']} — valeur neutre"})
    return {"score": round(100 * total, 1), "criteria": parts,
            "note": "Moyenne pondérée ; un critère sans historique prend la valeur neutre (aucune pénalité pour les nouveaux)."}


@dataclass
class Candidate:
    profile: HandymanProfile
    distance_km: Optional[float]
    detail: Dict

    @property
    def score(self) -> float:
        return self.detail["score"]


def _zone_filter(req: MissionRequest, config: DispatchConfig, radius_km: Optional[float] = None) -> Optional[Q]:
    """Préfiltre SQL de la zone, servi par l'index spatial : SUR-ENSEMBLE de `zone_of` (position du pro, sinon centre de sa zone
    d'intervention, sinon même commune) ; la règle exacte reste appliquée à chaque profil. None : personne (ni position ni commune)."""
    commune = (req.commune or "").strip().lower()
    same_commune = (HandymanProfile.objects.annotate(_c=Lower(Trim("commune")), _q=Lower(Trim("quartier")))
                    .filter(Q(_c=commune) | Q(_q=commune))) if commune else None
    if req.location is None:
        return Q(pk__in=same_commune.values("pk")) if same_commune is not None else None
    km = radius_km or config.radius_km
    zone = (Q(pk__in=HandymanProfile.objects.filter(proximity.near("location", req.location, km)).values("pk"))
            | Q(pk__in=ServiceArea.objects.filter(proximity.near("center", req.location, km), handyman__location__isnull=True)
                .values("handyman_id")))
    if same_commune is not None:
        zone |= Q(pk__in=same_commune.filter(Q(service_area__isnull=True) | Q(service_area__center__isnull=True), location__isnull=True)
                  .values("pk"))
    return zone


def _early_reason(user_id: int, years, offered: set, busy_elsewhere: set, min_years: int) -> Optional[str]:
    if user_id in offered:
        return "Déjà sollicité pour cette demande"
    if user_id in busy_elsewhere:
        return "Répond déjà à une autre proposition"
    if (years or 0) < min_years:
        return f"Expérience inférieure au minimum du métier ({min_years} an(s))"
    return None


def candidates(req: MissionRequest, config: DispatchConfig, now=None, *, explain: bool = False, listing: bool = False,
               radius_km: Optional[float] = None, outside: bool = True):
    """Professionnels éligibles et disponibles, classés. Avec `explain=True`, renvoie aussi les écartés et pourquoi (Back-Office).
    `listing=True` : liste montrée au CLIENT pour choisir son professionnel (demande pas encore créée) — une proposition en attente
    ailleurs n'écarte personne (le client choisit ; le pro répondra).

    Coût constant : seuls les profils de la zone (index spatial) sont chargés, et leurs disponibilités et historiques sont lus en
    quelques requêtes groupées, quel que soit leur nombre. Les écartés hors zone (`explain`) viennent d'une seule requête légère ;
    `outside=False` la supprime (vagues de la recherche progressive : jamais de lecture de tous les professionnels du métier).
    `radius_km` : palier courant de la recherche progressive."""
    now = now or timezone.now()
    family = category_family(req.category)
    offered = set(req.offers.values_list("handyman_id", flat=True)) if req.pk else set()
    busy_elsewhere = set() if listing else set(
        MissionOffer.objects.filter(status=MissionOffer.PENDING, expires_at__gt=now).exclude(request=req).values_list("handyman_id", flat=True))
    base = (orderable(HandymanProfile.objects.all())
            .filter(Q(user__services__is_active=True, user__services__category_id__in=family) | Q(skills__id__in=family))
            .exclude(user_id=req.client_id))
    zone = _zone_filter(req, config, radius_km)
    profiles = list(base.filter(zone).select_related("user", "service_area").distinct()) if zone is not None else []
    min_years = required_experience(req.category)
    reasons: Dict[int, str] = {}
    in_zone_ok = []
    for profile in profiles:
        reason = _early_reason(profile.user_id, profile.experience_years, offered, busy_elsewhere, min_years)
        in_zone, distance = zone_of(profile, req, config, radius_km)
        if reason is None and not in_zone:
            reason = "Hors zone"
        if reason is None:
            in_zone_ok.append((profile, distance))
        else:
            reasons[profile.user_id] = reason
    available = []
    batch = availability_batch([p for p, _ in in_zone_ok if not (req.is_immediate and not p.online)], req, config)
    for profile, distance in in_zone_ok:
        reason = availability_issue(profile, req, config, now, batch=batch)
        if reason is None:
            available.append((profile, distance))
        else:
            reasons[profile.user_id] = reason
    history = history_batch([p.user_id for p, _ in available], now)
    kept = [Candidate(profile, distance, score(profile, distance, config, now, batch=history)) for profile, distance in available]
    kept.sort(key=lambda c: (-c.score, c.distance_km if c.distance_km is not None else 1e9, c.profile.user_id))
    if not explain:
        return kept
    rejected = [{"user_id": p.user_id, "reason": reasons[p.user_id]} for p in profiles if p.user_id in reasons]
    if not outside:
        return kept, rejected
    elsewhere = base.exclude(zone) if zone is not None else base
    for user_id, years in elsewhere.values_list("user_id", "experience_years").distinct():
        rejected.append({"user_id": user_id, "reason": _early_reason(user_id, years, offered, busy_elsewhere, min_years) or "Hors zone"})
    return kept, rejected


# ═══ Cycle de vie d'une demande ═════════════════════════════════════════════════════════════════════════════════════════

def is_immediate(when, config: DispatchConfig, now=None) -> bool:
    return when <= (now or timezone.now()) + timedelta(minutes=config.immediate_horizon_minutes)


def create_request(client, *, category: ServiceCategory, address: str, scheduled_for=None, mode: str = MissionRequest.FIRM,
                   amount=None, commune: str = "", city: str = "Abidjan", postal_code: str = "", description: str = "",
                   lat=None, lng=None, matching: str = MissionRequest.AUTO, target_id=None, service_id=None,
                   allow_far: bool = False) -> MissionRequest:
    config = DispatchConfig.get_solo()
    now = timezone.now()
    when = scheduled_for or now
    if when < now - timedelta(minutes=5):
        raise FlashError("past_date", "La date de la mission est déjà passée.")
    if not category.is_active:
        raise FlashError("category_inactive", "Ce métier n'est pas disponible pour le moment.")
    if mode not in dict(MissionRequest.MODES):
        raise FlashError("invalid_mode", "Mode inconnu : « firm » (prix ferme) ou « quote » (sur devis).")
    if mode == MissionRequest.FIRM:
        if amount is None:
            raise FlashError("amount_required", "Indiquez le montant que vous proposez (prix ferme).")
        if Decimal(amount) < config.min_amount:
            raise FlashError("amount_too_low", f"Le montant minimal est de {config.min_amount} FCFA.", min_amount=config.min_amount)
    else:
        amount = None
    if not (address or "").strip():
        raise FlashError("address_required", "Indiquez l'adresse de l'intervention.")
    if lat is None and not (commune or "").strip():
        raise FlashError("zone_required", "Indiquez la commune ou partagez la position de l'intervention.")
    active = MissionRequest.objects.filter(client=client, status__in=MissionRequest.OPEN).count()
    if active >= config.max_active_requests_per_client:
        raise FlashError("too_many_requests", f"Vous avez déjà {active} demandes en cours.", 429)
    if matching not in dict(MissionRequest.MATCHINGS):
        raise FlashError("invalid_matching", "Mode inconnu : « auto » (Trouvez-moi un professionnel) ou « direct » (Choisir mon professionnel).")
    target = service = None
    if matching == MissionRequest.DIRECT:
        from flash import hybrid

        draft = MissionRequest(client=client, category=category, commune=(commune or "").strip(), scheduled_for=when,
                               is_immediate=is_immediate(when, config, now),
                               location=Point(float(lng), float(lat), srid=4326) if lat is not None and lng is not None else None)
        target = hybrid.validate_target(client, target_id, draft, config, now)
        if service_id:
            service = Service.objects.filter(pk=service_id, handyman=target, is_active=True).first()
            if service is None:
                raise FlashError("service_unavailable", "Cette offre n'est plus disponible chez ce professionnel.")
    with transaction.atomic():
        req = MissionRequest.objects.create(
            client=client, category=category, description=(description or "").strip()[:1000], address=address.strip()[:255],
            commune=(commune or "").strip()[:100], city=(city or "Abidjan").strip()[:100], postal_code=(postal_code or "").strip()[:20],
            location=Point(float(lng), float(lat), srid=4326) if lat is not None and lng is not None else None,
            scheduled_for=when, is_immediate=is_immediate(when, config, now), mode=mode, amount=amount,
            matching=matching, target=target, service=service, allow_far=bool(allow_far))
        log(req, "created", actor=client, mode=mode, amount=str(amount) if amount is not None else None, immediate=req.is_immediate,
            matching=matching, target=target.pk if target else None)
    if matching == MissionRequest.DIRECT:
        from flash import hybrid

        hybrid.start_direct(req.pk, target)
    else:
        launch_wave(req.pk)
    req.refresh_from_db()
    return req


def _timeout(req: MissionRequest, config: DispatchConfig) -> int:
    return config.offer_timeout_seconds if req.is_immediate else config.scheduled_offer_timeout_seconds


def progressive(req: MissionRequest, config: DispatchConfig) -> bool:
    """Recherche par rayons croissants : demandes « Trouvez-moi un professionnel » dont le lieu est connu (sinon : la commune)."""
    return bool(config.progressive_search and req.location is not None and req.matching == MissionRequest.AUTO)


def step_seconds(req: MissionRequest, config: DispatchConfig) -> int:
    return config.step_seconds if req.is_immediate else config.scheduled_step_seconds


def limit_km(req: MissionRequest, config: DispatchConfig) -> float:
    """Plus grand rayon permis : `far_radius_km` ; au-delà, il faut l'accord du client ET un métier compatible."""
    if req.allow_far and config.trade_goes_far(req.category):
        return float("inf")
    return config.far_radius_km


def needs_consent(req: MissionRequest, config: DispatchConfig) -> bool:
    """Le palier suivant dépasse `far_radius_km`, le métier le permet et le client n'a pas encore donné son accord."""
    steps = config.steps_km()
    nxt = req.radius_index + 1
    return (progressive(req, config) and not req.allow_far and nxt < len(steps) and steps[nxt] > config.far_radius_km
            and steps[req.radius_index] <= config.far_radius_km and config.trade_goes_far(req.category))


def launch_wave(request_id: int, *, now=None) -> List[MissionOffer]:
    """Lance la vague suivante si la demande est ouverte. Rayon fixe : seulement quand plus personne n'attend de réponse. Recherche
    progressive : aussi quand le palier courant est échu (les propositions en cours restent valables jusqu'à leur échéance) ; le rayon
    s'élargit tant que personne n'est disponible dans le palier. Rejouable sans effet double (verrou de la demande, une proposition par
    professionnel et par demande)."""
    config = DispatchConfig.get_solo()
    now = now or timezone.now()
    with transaction.atomic():
        req = MissionRequest.objects.select_for_update(of=("self",)).select_related("category", "category__parent").get(pk=request_id)
        if req.status != MissionRequest.SEARCHING:
            return []
        pending = req.offers.filter(status=MissionOffer.PENDING).count()
        if req.matching == MissionRequest.DIRECT:
            if pending:
                return []
            # Professionnel choisi par le client : jamais de vague. Sans réponse positive, le CLIENT décide (autre pro, Smart Dispatch, annuler).
            from flash import hybrid

            hybrid.after_targeted_response(req, config, now)
            return []
        prog = progressive(req, config)
        if pending and (not prog or req.next_step_at is None or req.next_step_at > now):
            return []
        quotes = req.offers.filter(status__in=MissionOffer.PROPOSALS).count()
        # Plafond : vagues en rayon fixe ; professionnels sollicités au total en recherche progressive (les paliers vides ne comptent pas).
        capped = req.offers.count() >= config.max_contacts if prog else req.wave >= config.max_waves
        if capped or (req.mode == MissionRequest.QUOTE and quotes >= config.max_quotes):
            if pending:
                _set_step(req, None)     # plus de vague : on attend les réponses en cours
                return []
            _finish_search(req, config, now)
            return []
        if prog:
            return _progressive_wave(req, config, now, pending)
        ranked, rejected = candidates(req, config, now, explain=True, outside=False)
        chosen = _reserve(req, ranked, config.wave_size, now)
        if not chosen:
            if ranked:
                return []      # tous sollicités à l'instant par d'autres demandes : le passage périodique relance
            if req.wave == 0:
                log(req, "no_candidate", excluded=len(rejected), reasons=_reason_counts(rejected))
            _finish_search(req, config, now)
            return []
        req.eligible_count = len(ranked) + req.offers.count()
        return _send_wave(req, config, now, chosen, ranked, rejected)


def _reserve(req: MissionRequest, ranked: List[Candidate], n: int, now) -> List[Candidate]:
    """Les `n` meilleurs candidats RÉSERVÉS à cette vague. Deux demandes lancées au même instant ne sollicitent jamais le même
    professionnel : son profil est verrouillé jusqu'à la fin de la transaction (un profil déjà verrouillé par une autre vague ou une
    acceptation est sauté, sans attente), puis l'absence de proposition en attente ailleurs est revérifiée sous ce verrou."""
    taken: List[Candidate] = []
    i = 0
    while len(taken) < n and i < len(ranked):
        part = ranked[i: i + n - len(taken)]
        i += len(part)
        ids = [c.profile.user_id for c in part]
        free = set(HandymanProfile.objects.select_for_update(of=("self",), skip_locked=True).filter(user_id__in=ids)
                   .values_list("user_id", flat=True))
        if free:
            free -= set(MissionOffer.objects.filter(status=MissionOffer.PENDING, expires_at__gt=now, handyman_id__in=free)
                        .exclude(request=req).values_list("handyman_id", flat=True))
        taken += [c for c in part if c.profile.user_id in free]
    return taken


def _send_wave(req: MissionRequest, config: DispatchConfig, now, chosen, ranked, rejected) -> List[MissionOffer]:
    req.wave += 1
    step = step_seconds(req, config) if progressive(req, config) else None
    req.next_step_at = now + timedelta(seconds=step) if step else None
    req.consent_asked_at = None
    req.save(update_fields=["wave", "next_step_at", "consent_asked_at", "eligible_count", "radius_index", "radius_m", "updated_at"])
    expires = now + timedelta(seconds=_timeout(req, config))
    offers = []
    for rank, cand in enumerate(chosen, start=1):
        offer = MissionOffer.objects.create(request=req, handyman_id=cand.profile.user_id, wave=req.wave, rank=rank,
                                            score=cand.score, score_detail=cand.detail, distance_km=cand.distance_km, expires_at=expires)
        offers.append(offer)
        log(req, "offer_sent", offer=offer, handyman=cand.profile.user_id, rank=rank, score=cand.score, distance_km=cand.distance_km)
    log(req, "wave", wave=req.wave, sent=len(offers), eligible=len(ranked), excluded=len(rejected), radius_m=req.radius_m or None,
        reasons=_reason_counts(rejected), expires_at=expires.isoformat())
    ids, rid, wave, timeout = [o.pk for o in offers], req.pk, req.wave, _timeout(req, config)
    transaction.on_commit(lambda: _after_wave(rid, wave, ids, timeout, step))
    return offers


def _set_step(req: MissionRequest, when) -> None:
    if req.next_step_at != when:
        req.next_step_at = when
        req.save(update_fields=["next_step_at", "updated_at"])


def _progressive_wave(req: MissionRequest, config: DispatchConfig, now, pending: int) -> List[MissionOffer]:
    """Palier courant d'abord (les meilleurs non encore sollicités), puis paliers suivants tant que personne n'y est disponible ; jamais
    au-delà de `far_radius_km` sans l'accord du client (et un métier compatible). Requêtes spatiales indexées, palier par palier."""
    steps = config.steps_km()
    limit = limit_km(req, config)
    idx = min(req.radius_index, len(steps) - 1)
    if req.radius_m and int(round(steps[idx] * 1000)) < req.radius_m:      # paliers modifiés au Back-Office : jamais de recul
        idx = next((i for i, km in enumerate(steps) if int(round(km * 1000)) >= req.radius_m), len(steps) - 1)
    widened = []
    while True:
        ranked, rejected = candidates(req, config, now, explain=True, radius_km=steps[idx], outside=False)
        if ranked or idx + 1 >= len(steps) or steps[idx + 1] > limit:
            break
        idx += 1
        widened.append(steps[idx])
    before = req.radius_m
    req.radius_index, req.radius_m = idx, int(round(steps[idx] * 1000))
    req.eligible_count = len(ranked) + req.offers.count()
    if widened and before:   # premier palier : consigné par la vague elle-même (`radius_m`), sans évènement à part
        log(req, "radius", from_m=before, radius_m=req.radius_m, skipped=len(widened) - 1)
    room = max(0, min(config.max_pending_offers - pending, config.max_contacts - req.offers.count()))
    chosen = _reserve(req, ranked, min(config.wave_size, room), now)
    if chosen:
        return _send_wave(req, config, now, chosen, ranked, rejected)
    if ranked:   # des pros disponibles mais le plafond de propositions en attente est atteint (ou ils viennent d'être sollicités par
        req.next_step_at = now   # une autre demande) : dès qu'une place se libère (refus, expiration) ou au prochain passage périodique
        req.save(update_fields=["next_step_at", "eligible_count", "radius_index", "radius_m", "updated_at"])
        return []
    consent = needs_consent(req, config)
    if consent and req.consent_asked_at is None:
        # On ne demande l'accord du client que si élargir sert à quelque chose : des pros sont disponibles au-delà (requête indexée).
        beyond = len(candidates(req, config, now, radius_km=steps[-1], outside=False))
        if beyond:
            req.consent_asked_at = now
            log(req, "consent_asked", radius_m=req.radius_m, next_m=int(round(steps[idx + 1] * 1000)), available=beyond)
            rid = req.pk
            transaction.on_commit(lambda: _notify_consent(rid))
        else:
            consent = False
    req.next_step_at = None
    req.save(update_fields=["next_step_at", "consent_asked_at", "eligible_count", "radius_index", "radius_m", "updated_at"])
    if pending:
        return []      # personne de plus à solliciter : on attend les réponses en cours
    if consent and now < req.consent_asked_at + timedelta(seconds=config.far_consent_wait_seconds):
        return []      # on attend l'accord du client pour élargir au-delà de `far_radius_km`
    if req.wave == 0:
        log(req, "no_candidate", excluded=len(rejected), reasons=_reason_counts(rejected), radius_m=req.radius_m)
    _finish_search(req, config, now)
    return []


def _notify_consent(request_id: int) -> None:
    from flash import notify

    notify.consent_needed(request_id)


def allow_far(request_id: int, client, *, now=None) -> MissionRequest:
    """Accord du client pour élargir au-delà de `far_radius_km` : la recherche reprend aussitôt au palier suivant."""
    now = now or timezone.now()
    config = DispatchConfig.get_solo()
    with transaction.atomic():
        req = MissionRequest.objects.select_for_update(of=("self",)).select_related("category", "category__parent") \
            .filter(pk=request_id, client=client).first()
        if req is None:
            raise FlashError("not_found", "Demande introuvable.", 404)
        if req.allow_far:
            return req
        if req.status != MissionRequest.SEARCHING:
            raise FlashError("request_closed", "Cette demande n'est plus en recherche.", 409)
        if not config.trade_goes_far(req.category):
            raise FlashError("far_not_allowed", f"Ce métier n'est pas proposé au-delà de {_km(config.far_radius_km)}.", 409)
        req.allow_far, req.consent_asked_at = True, None
        req.next_step_at = now          # extension immédiate
        req.save(update_fields=["allow_far", "consent_asked_at", "next_step_at", "updated_at"])
        log(req, "far_consent", actor=client, beyond_km=config.far_radius_km)
        rid = req.pk
        transaction.on_commit(lambda: launch_wave(rid))
    req.refresh_from_db()
    return req


def _km(km: float) -> str:
    return f"{int(km)} km" if km >= 1 else f"{int(km * 1000)} m"


def _reason_counts(rejected: List[Dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rejected:
        out[r["reason"]] = out.get(r["reason"], 0) + 1
    return out


def _after_wave(request_id: int, wave: int, offer_ids: List[int], timeout: int, step: Optional[int] = None) -> None:
    from flash import notify

    for oid in offer_ids:
        notify.new_offer(oid)
    try:
        from flash.tasks import step_due, wave_timeout

        wave_timeout.apply_async(args=(request_id, wave), countdown=timeout + 2, retry=False)
        if step:   # recherche progressive : palier suivant à l'échéance (le passage périodique reste le filet de sécurité)
            step_due.apply_async(args=(request_id,), countdown=step + 1, retry=False)
    except Exception:   # sans broker : la tâche périodique `flash.tasks.tick` (30 s) prend le relais
        logger.info("Échéance de vague confiée à la tâche périodique (demande #%s).", request_id)


def _finish_search(req: MissionRequest, config: DispatchConfig, now) -> None:
    """Plus de vague possible : sur devis avec au moins un devis → le client choisit ; sinon → aucun professionnel."""
    if req.mode == MissionRequest.QUOTE and req.offers.filter(status__in=MissionOffer.PROPOSALS).exists():
        req.status, req.quote_deadline = MissionRequest.QUOTING, now + timedelta(hours=config.quote_window_hours)
        req.next_step_at = None
        req.version += 1
        req.save(update_fields=["status", "quote_deadline", "next_step_at", "version", "updated_at"])
        log(req, "quoting", proposals=req.offers.filter(status__in=MissionOffer.PROPOSALS).count())
        return
    _close(req, MissionRequest.UNFULFILLED, "Aucun professionnel disponible n'a accepté.", now)
    log(req, "unfulfilled", waves=req.wave)
    transaction.on_commit(lambda: _notify_unfulfilled(req.pk))


def _notify_unfulfilled(request_id: int) -> None:
    from flash import notify

    notify.unfulfilled(request_id)


def _close(req: MissionRequest, status: str, reason: str, now) -> None:
    req.status, req.closed_at, req.close_reason = status, now, reason[:200]
    req.next_step_at = req.consent_asked_at = None
    req.version += 1
    req.save(update_fields=["status", "closed_at", "close_reason", "next_step_at", "consent_asked_at", "version", "updated_at"])
    _withdraw_others(req, keep=None)


def _withdraw_others(req: MissionRequest, keep: Optional[int]) -> List[int]:
    """Retire les propositions encore ouvertes : leur alerte est arrêtée sur les téléphones (après validation)."""
    qs = req.offers.filter(status__in=(MissionOffer.PENDING, *MissionOffer.PROPOSALS))
    if keep is not None:
        qs = qs.exclude(pk=keep)
    ids = list(qs.values_list("pk", flat=True))
    if ids:
        MissionOffer.objects.filter(pk__in=ids).update(status=MissionOffer.WITHDRAWN)
        transaction.on_commit(lambda: _closed(ids))
    return ids


def _closed(offer_ids: List[int]) -> None:
    """Arrêt de l'alerte des propositions closes, HORS de la requête (file « flash ») : l'acceptation répond sans attendre Firebase.
    Sans broker, sur place (filet de sécurité)."""
    from flash.tasks import close_offers

    try:
        close_offers.apply_async(args=(list(offer_ids),), retry=False)
    except Exception:   # broker indisponible
        close_offers(list(offer_ids))


def _request_of(offer_id: int, user) -> MissionRequest:
    """Verrou de la demande d'une proposition. Ordre UNIQUE des verrous, partout : demande, puis proposition, puis profil du
    professionnel — deux actions simultanées sur une même demande (accepter, refuser, expirer, annuler) s'attendent sans s'interbloquer."""
    request_id = MissionOffer.objects.filter(pk=offer_id, handyman=user).values_list("request_id", flat=True).first()
    if request_id is None:
        raise FlashError("not_found", "Proposition introuvable.", 404)
    return MissionRequest.objects.select_for_update(of=("self",)).get(pk=request_id)


def _offer_for(offer_id: int, user, *, lock: bool = True) -> MissionOffer:
    qs = MissionOffer.objects.select_related("request")
    if lock:
        qs = qs.select_for_update(of=("self",))
    offer = qs.filter(pk=offer_id, handyman=user).first()
    if offer is None:
        raise FlashError("not_found", "Proposition introuvable.", 404)
    return offer


def _respond(offer: MissionOffer, status: str, now) -> None:
    offer.status, offer.responded_at = status, now
    offer.response_seconds = max(0, int((now - offer.sent_at).total_seconds()))


def accept(offer_id: int, user, *, now=None) -> MissionRequest:
    """Acceptation FERME : crée la réservation confirmée au montant proposé. Rejouée par le même professionnel → même résultat."""
    now = now or timezone.now()
    with transaction.atomic():
        req = _request_of(offer_id, user)
        offer = _offer_for(offer_id, user)
        if offer.status == MissionOffer.ACCEPTED and req.assigned_to_id == user.pk:
            return req   # rejeu (double appui, réseau) : déjà attribuée à ce professionnel
        if req.mode != MissionRequest.FIRM:
            raise FlashError("quote_mode", "Cette demande est sur devis : envoyez un devis.", 409)
        if req.status != MissionRequest.SEARCHING:
            raise FlashError("already_assigned" if req.status == MissionRequest.ASSIGNED else "request_closed",
                             "Cette mission a déjà été attribuée." if req.status == MissionRequest.ASSIGNED else "Cette demande n'est plus disponible.", 409)
        if offer.status != MissionOffer.PENDING or now > offer.expires_at + timedelta(seconds=ACCEPT_GRACE_SECONDS):
            raise FlashError("offer_expired", "Cette proposition a expiré.", 409)
        profile = HandymanProfile.objects.select_for_update(of=("self",)).select_related("user").get(user=user)   # sérialise les acceptations d'un même pro
        if not is_orderable(profile):
            raise FlashError("not_eligible", "Votre profil n'est plus éligible aux missions.", 403)
        config = DispatchConfig.get_solo()
        busy = availability_issue(profile, req, config, now, check_online=False)
        if busy:
            log(req, "conflict", offer=offer, actor=user, reason=busy)
            raise FlashError("schedule_conflict", f"Acceptation impossible : {busy.lower()}.", 409)
        _respond(offer, MissionOffer.ACCEPTED, now)
        try:
            with transaction.atomic():
                offer.save(update_fields=["status", "responded_at", "response_seconds"])
        except IntegrityError:   # contrainte « une seule proposition acceptée par demande »
            raise FlashError("already_assigned", "Cette mission a déjà été attribuée.", 409)
        booking = _assign(req, offer, user, req.amount, now)
        log(req, "accepted", offer=offer, actor=user, response_seconds=offer.response_seconds)
        log(req, "assigned", offer=offer, actor=user, booking=booking.pk, amount=str(req.amount))
    return req


def _assign(req: MissionRequest, offer: MissionOffer, pro, amount, now) -> Booking:
    chosen = req.service if req.service_id and req.service.handyman_id == pro.pk else None   # offre choisie par le client
    service = chosen or (Service.objects.filter(handyman=pro, is_active=True, category_id__in=category_family(req.category))
               .annotate(exact=Case(When(category_id=req.category_id, then=Value(1)), default=Value(0), output_field=IntegerField()))
               .order_by("-exact", "-id").first())
    booking = Booking(client_id=req.client_id, handyman=pro, service=service, booking_date=req.scheduled_for,
                      address=req.address, city=req.city or "Abidjan", postal_code=req.postal_code or "",
                      description=req.description or f"Mission Tratra Flash — {req.category.name}", proposed_price=amount, total_price=amount,
                      job_location=req.location, booking_type="instant" if req.is_immediate else "scheduled",
                      transport_fee=0, transport_quote={"source": "flash", "included": True, "request": req.pk})
    booking._flash_origin = True        # la demande de réservation n'est pas notifiée : le pro vient de l'accepter
    booking.save()
    booking.transition_to("confirmed", actor=pro)   # le client est prévenu (« … a accepté votre réservation »)
    req.status, req.assigned_to, req.booking, req.assigned_at = MissionRequest.ASSIGNED, pro, booking, now
    req.closed_at, req.close_reason = now, ""
    req.next_step_at = req.consent_asked_at = None
    req.version += 1
    req.save(update_fields=["status", "assigned_to", "booking", "assigned_at", "closed_at", "close_reason", "next_step_at",
                            "consent_asked_at", "version", "updated_at"])
    _withdraw_others(req, keep=offer.pk)
    transaction.on_commit(lambda: _closed([offer.pk]))   # l'alerte du gagnant s'arrête aussi (autres appareils)
    return booking


def decline(offer_id: int, user, reason: str = "", *, now=None) -> MissionOffer:
    """Refus : JAMAIS pénalisé. Si plus personne n'est en attente dans la vague, la suivante part aussitôt."""
    now = now or timezone.now()
    with transaction.atomic():
        req = _request_of(offer_id, user)
        offer = _offer_for(offer_id, user)
        if offer.status == MissionOffer.DECLINED:
            return offer
        if offer.status != MissionOffer.PENDING:
            raise FlashError("offer_closed", "Cette proposition n'attend plus de réponse.", 409)
        _respond(offer, MissionOffer.DECLINED, now)
        offer.decline_reason = reason if reason in dict(MissionOffer.DECLINE_REASONS) else ""
        offer.save(update_fields=["status", "responded_at", "response_seconds", "decline_reason"])
        log(req, "declined", offer=offer, actor=user, reason=offer.decline_reason, response_seconds=offer.response_seconds)
        request_id = req.pk
        transaction.on_commit(lambda: (_closed([offer.pk]), launch_wave(request_id)))
    return offer


def send_quote(offer_id: int, user, amount, message: str = "", *, now=None) -> MissionOffer:
    now = now or timezone.now()
    config = DispatchConfig.get_solo()
    try:
        amount = Decimal(str(amount)).quantize(Decimal("1"))
    except Exception:
        raise FlashError("invalid_amount", "Montant du devis invalide.")
    if amount < config.min_amount:
        raise FlashError("amount_too_low", f"Le devis minimal est de {config.min_amount} FCFA.", min_amount=config.min_amount)
    with transaction.atomic():
        req = _request_of(offer_id, user)
        offer = _offer_for(offer_id, user)
        if offer.status == MissionOffer.QUOTED and offer.quote_amount == amount:
            return offer
        if req.mode != MissionRequest.QUOTE:
            raise FlashError("firm_mode", "Cette demande est à prix ferme : acceptez ou refusez.", 409)
        if not req.is_open:
            raise FlashError("request_closed", "Cette demande n'est plus disponible.", 409)
        if offer.status != MissionOffer.PENDING or now > offer.expires_at + timedelta(seconds=ACCEPT_GRACE_SECONDS):
            raise FlashError("offer_expired", "Cette proposition a expiré.", 409)
        _respond(offer, MissionOffer.QUOTED, now)
        offer.quote_amount, offer.quote_message = amount, (message or "").strip()[:500]
        offer.proposal_expires_at = now + (timedelta(minutes=config.proposal_ttl_minutes) if req.is_immediate
                                           else timedelta(hours=config.quote_window_hours))
        offer.save(update_fields=["status", "responded_at", "response_seconds", "quote_amount", "quote_message", "proposal_expires_at"])
        log(req, "quoted", offer=offer, actor=user, amount=str(amount), response_seconds=offer.response_seconds)
        transaction.on_commit(lambda: (_closed([offer.pk]), _notify_quote(offer.pk), launch_wave(req.pk)))
    return offer


def _notify_quote(offer_id: int) -> None:
    from flash import notify

    notify.quote_received(offer_id)


def choose_quote(request_id: int, client, offer_id: int, *, now=None) -> MissionRequest:
    now = now or timezone.now()
    with transaction.atomic():
        req = MissionRequest.objects.select_for_update().filter(pk=request_id, client=client).first()
        if req is None:
            raise FlashError("not_found", "Demande introuvable.", 404)
        offer = MissionOffer.objects.select_for_update(of=("self",)).select_related("handyman").filter(pk=offer_id, request=req).first()
        if offer is None:
            raise FlashError("not_found", "Devis introuvable.", 404)
        if req.status == MissionRequest.ASSIGNED and req.assigned_to_id == offer.handyman_id:
            return req
        if not req.is_open:
            raise FlashError("request_closed", "Cette demande n'est plus ouverte.", 409)
        if offer.status not in MissionOffer.PROPOSALS:
            raise FlashError("quote_unavailable", "Ce devis n'est plus disponible.", 409)
        if offer.proposal_expires_at and now > offer.proposal_expires_at + timedelta(seconds=ACCEPT_GRACE_SECONDS):
            raise FlashError("proposal_lapsed", "Cette proposition a expiré.", 409)
        profile = HandymanProfile.objects.select_for_update(of=("self",)).select_related("user").get(user_id=offer.handyman_id)
        if not is_orderable(profile):
            raise FlashError("not_eligible", "Ce professionnel n'est plus disponible.", 409)
        config = DispatchConfig.get_solo()
        busy = availability_issue(profile, req, config, now, check_online=False)
        if busy:
            raise FlashError("schedule_conflict", "Ce professionnel n'est plus libre sur ce créneau.", 409)
        offer.status = MissionOffer.ACCEPTED
        try:
            with transaction.atomic():
                offer.save(update_fields=["status"])
        except IntegrityError:
            raise FlashError("already_assigned", "Cette demande est déjà attribuée.", 409)
        booking = _assign(req, offer, offer.handyman, offer.quote_amount, now)
        log(req, "quote_chosen", offer=offer, actor=client, amount=str(offer.quote_amount))
        log(req, "assigned", offer=offer, actor=client, booking=booking.pk, amount=str(offer.quote_amount))
    return req


def cancel_request(request_id: int, client, *, now=None) -> MissionRequest:
    now = now or timezone.now()
    with transaction.atomic():
        req = MissionRequest.objects.select_for_update().filter(pk=request_id, client=client).first()
        if req is None:
            raise FlashError("not_found", "Demande introuvable.", 404)
        if req.status == MissionRequest.CANCELLED:
            return req
        if not req.is_open:
            raise FlashError("request_closed", "Cette demande ne peut plus être annulée ici : gérez la réservation.", 409,
                             booking=req.booking_id)
        _close(req, MissionRequest.CANCELLED, "Annulée par le client.", now)
        log(req, "cancelled", actor=client)
    return req


def mark_seen(offer_id: int, user, *, now=None) -> MissionOffer:
    now = now or timezone.now()
    offer = MissionOffer.objects.select_related("request").filter(pk=offer_id, handyman=user).first()
    if offer is None:
        raise FlashError("not_found", "Proposition introuvable.", 404)
    if offer.seen_at is None:
        MissionOffer.objects.filter(pk=offer.pk, seen_at__isnull=True).update(seen_at=now)
        offer.seen_at = now
        log(offer.request, "seen", offer=offer, actor=user)
    return offer


# ═══ Échéances (tâche périodique + compte à rebours de chaque vague) ════════════════════════════════════════════════════

def expire_due(*, now=None, request_id: Optional[int] = None) -> Dict[str, int]:
    """Expire les propositions échues, enchaîne les vagues, ferme les fenêtres de choix des devis. Idempotent et rejouable (tâche
    relancée, deux passages simultanés) : chaque changement est fait sous le verrou de la demande, sur l'état relu.
    `request_id` : échéances de CETTE demande seulement (compte à rebours de sa vague) ; sans lui, passage général (filet de sécurité)."""
    now = now or timezone.now()
    config = DispatchConfig.get_solo()
    scope = {"request_id": request_id} if request_id else {}
    only = {"pk": request_id} if request_id else {}
    late = now - timedelta(seconds=ACCEPT_GRACE_SECONDS)
    due: Dict[int, List[int]] = {}
    for oid, rid in MissionOffer.objects.filter(status=MissionOffer.PENDING, expires_at__lt=late, **scope).values_list("pk", "request_id"):
        due.setdefault(rid, []).append(oid)
    expired = 0
    for rid, oids in due.items():
        with transaction.atomic():
            req = MissionRequest.objects.select_for_update(of=("self",)).get(pk=rid)      # demande d'abord, toujours
            done = []
            for offer in (MissionOffer.objects.select_for_update(of=("self",)).filter(pk__in=oids, status=MissionOffer.PENDING)
                          .order_by("pk")):
                offer.status = MissionOffer.EXPIRED
                offer.save(update_fields=["status"])
                done.append(offer.pk)
                log(req, "expired", offer=offer, waited_seconds=int((offer.expires_at - offer.sent_at).total_seconds()))
                _maybe_pause(offer.handyman_id, req, config, now)
            if done:
                expired += len(done)
                transaction.on_commit(lambda ids=done: _closed(ids))
        launch_wave(rid, now=now)
    touched = set(due)
    searching = MissionRequest.objects.filter(status=MissionRequest.SEARCHING, **only).exclude(pk__in=touched)
    # Demandes ouvertes sans proposition en attente (vague perdue, redémarrage) : on relance.
    for rid in searching.exclude(offers__status=MissionOffer.PENDING).values_list("pk", flat=True)[:200]:
        launch_wave(rid, now=now)
    # Recherche progressive : paliers échus (le compte à rebours de chaque palier est le chemin rapide, ceci le filet de sécurité).
    for rid in searching.filter(next_step_at__lte=now).values_list("pk", flat=True)[:200]:
        launch_wave(rid, now=now)
    countered = _expire_counters(now, scope)
    lapsed = _lapse_proposals(now, scope)
    closed = 0
    for rid in MissionRequest.objects.filter(status=MissionRequest.QUOTING, quote_deadline__lt=now, **only).values_list("pk", flat=True):
        with transaction.atomic():
            locked = MissionRequest.objects.select_for_update(of=("self",)).get(pk=rid)
            if locked.status != MissionRequest.QUOTING or locked.quote_deadline is None or locked.quote_deadline >= now:
                continue
            _close(locked, MissionRequest.UNFULFILLED, "Aucun devis retenu dans le délai.", now)
            log(locked, "unfulfilled", reason="quote_window_elapsed")
            transaction.on_commit(lambda rid=rid: _notify_unfulfilled(rid))
            closed += 1
    return {"expired": expired, "requests": len(touched), "quote_windows_closed": closed, "counters_expired": countered, "lapsed": lapsed}


def _expire_counters(now, scope: Optional[Dict] = None) -> int:
    """Contre-offre restée sans réponse du professionnel : sa proposition initiale reste valable (le client peut encore la choisir)."""
    n = 0
    late = now - timedelta(seconds=ACCEPT_GRACE_SECONDS)
    for oid, rid in (MissionOffer.objects.filter(status=MissionOffer.COUNTERED, counter_expires_at__lt=late, **(scope or {}))
                     .values_list("pk", "request_id")):
        with transaction.atomic():
            req = MissionRequest.objects.select_for_update(of=("self",)).get(pk=rid)
            # Relue sous verrou : une nouvelle contre-offre (nouvelle échéance) ou une réponse arrivée entre-temps l'emporte.
            offer = (MissionOffer.objects.select_for_update(of=("self",))
                     .filter(pk=oid, status=MissionOffer.COUNTERED, counter_expires_at__lt=late).first())
            if offer is None:
                continue
            offer.status = MissionOffer.QUOTED
            offer.save(update_fields=["status"])
            n += 1
            log(req, "counter_no", offer=offer, reason="expired", amount=str(offer.counter_amount))
            transaction.on_commit(lambda oid=oid: _notify_counter_answer(oid, False))
    return n


def _lapse_proposals(now, scope: Optional[Dict] = None) -> int:
    """Propositions de prix échues : retirées du choix du client ; une demande « à choisir » sans proposition restante est close."""
    n = 0
    late = now - timedelta(seconds=ACCEPT_GRACE_SECONDS)
    due: Dict[int, List[int]] = {}
    for oid, rid in (MissionOffer.objects.filter(status=MissionOffer.QUOTED, proposal_expires_at__lt=late, **(scope or {}))
                     .values_list("pk", "request_id")):
        due.setdefault(rid, []).append(oid)
    for rid, oids in due.items():
        with transaction.atomic():
            req = MissionRequest.objects.select_for_update(of=("self",)).get(pk=rid)
            offers = list(MissionOffer.objects.select_for_update(of=("self",))
                          .filter(pk__in=oids, status=MissionOffer.QUOTED, proposal_expires_at__lt=late).order_by("pk"))
            for offer in offers:
                offer.status = MissionOffer.LAPSED
                offer.save(update_fields=["status"])
                log(req, "lapsed", offer=offer, amount=str(offer.quote_amount))
            n += len(offers)
            if offers and req.status == MissionRequest.QUOTING and not req.offers.filter(status__in=MissionOffer.PROPOSALS).exists():
                _close(req, MissionRequest.UNFULFILLED, "Les propositions ont expiré sans être choisies.", now)
                log(req, "unfulfilled", reason="proposals_lapsed")
                transaction.on_commit(lambda r=rid: _notify_unfulfilled(r))
    return n


def _sweep_later(request_id: int, countdown: int) -> None:
    """Échéance propre à une demande (contre-offre) : passage ciblé à l'heure dite ; le passage périodique reste le filet de sécurité."""
    try:
        from flash.tasks import wave_timeout

        wave_timeout.apply_async(args=(request_id, 0), countdown=countdown, retry=False)
    except Exception:
        logger.info("Échéance confiée à la tâche périodique (demande #%s).", request_id)


# ═══ Contre-offres (mode Propositions) ══════════════════════════════════════════════════════════════════════════════════

def _amount(raw, config: DispatchConfig, what: str) -> Decimal:
    try:
        amount = Decimal(str(raw).replace(" ", "").replace("\u202f", "")).quantize(Decimal("1"))
    except Exception:
        raise FlashError("invalid_amount", f"Montant {what} invalide.")
    if amount < config.min_amount:
        raise FlashError("amount_too_low", f"Le montant minimal est de {config.min_amount} FCFA.", min_amount=config.min_amount)
    return amount


def counter_offer(request_id: int, client, offer_id: int, amount, *, now=None) -> MissionOffer:
    """Le client répond à une proposition de prix par un montant plus bas. Ce n'est NI une sélection NI une confirmation : le
    professionnel accepte (la mission lui est alors attribuée à ce montant) ou non (sa proposition initiale reste valable)."""
    now = now or timezone.now()
    config = DispatchConfig.get_solo()
    amount = _amount(amount, config, "de la contre-offre")
    with transaction.atomic():
        req = MissionRequest.objects.select_for_update().filter(pk=request_id, client=client).first()
        if req is None:
            raise FlashError("not_found", "Demande introuvable.", 404)
        offer = MissionOffer.objects.select_for_update().filter(pk=offer_id, request=req).first()
        if offer is None:
            raise FlashError("not_found", "Proposition introuvable.", 404)
        if offer.status == MissionOffer.COUNTERED and offer.counter_amount == amount:
            return offer   # rejeu
        if req.status not in (MissionRequest.SEARCHING, MissionRequest.QUOTING):
            raise FlashError("request_closed", "Cette demande n'est plus ouverte.", 409)
        if offer.status != MissionOffer.QUOTED:
            raise FlashError("quote_unavailable", "Cette proposition n'attend pas de contre-offre.", 409)
        if offer.proposal_expires_at and now > offer.proposal_expires_at:
            raise FlashError("proposal_lapsed", "Cette proposition a expiré.", 409)
        if offer.counters >= config.max_counter_offers:
            raise FlashError("counter_limit", "Plus de contre-offre possible : choisissez cette proposition ou une autre.", 409)
        if amount >= offer.quote_amount:
            raise FlashError("counter_not_lower", "Votre contre-offre doit être inférieure à la proposition — sinon, choisissez-la.", 400)
        offer.status, offer.counter_amount, offer.counter_at = MissionOffer.COUNTERED, amount, now
        offer.counter_expires_at = now + timedelta(seconds=config.counter_timeout_seconds)
        offer.counters += 1
        offer.save(update_fields=["status", "counter_amount", "counter_at", "counter_expires_at", "counters"])
        log(req, "counter", offer=offer, actor=client, amount=str(amount), proposal=str(offer.quote_amount), round=offer.counters)
        wait = config.counter_timeout_seconds + ACCEPT_GRACE_SECONDS + 1
        transaction.on_commit(lambda: (_notify_counter(offer.pk), _sweep_later(req.pk, wait)))
    return offer


def answer_counter(offer_id: int, user, accept: bool, *, now=None) -> MissionRequest:
    """Réponse du professionnel à une contre-offre. Accepter vaut confirmation : le client a déjà donné son accord sur ce montant."""
    now = now or timezone.now()
    with transaction.atomic():
        req = _request_of(offer_id, user)
        offer = _offer_for(offer_id, user)
        if accept and offer.status == MissionOffer.ACCEPTED and req.assigned_to_id == user.pk:
            return req   # rejeu
        if not accept and offer.status == MissionOffer.QUOTED and offer.counter_amount is not None:
            return req   # rejeu du refus
        if offer.status != MissionOffer.COUNTERED:
            raise FlashError("counter_closed", "Cette contre-offre n'attend plus de réponse.", 409)
        if now > offer.counter_expires_at + timedelta(seconds=ACCEPT_GRACE_SECONDS):
            raise FlashError("counter_expired", "Cette contre-offre a expiré.", 409)
        if req.status not in (MissionRequest.SEARCHING, MissionRequest.QUOTING):
            raise FlashError("already_assigned" if req.status == MissionRequest.ASSIGNED else "request_closed",
                             "Cette demande n'est plus disponible.", 409)
        if not accept:
            offer.status = MissionOffer.QUOTED
            offer.save(update_fields=["status"])
            log(req, "counter_no", offer=offer, actor=user, reason="declined", amount=str(offer.counter_amount))
            transaction.on_commit(lambda: _notify_counter_answer(offer.pk, False))
            return req
        profile = HandymanProfile.objects.select_for_update(of=("self",)).select_related("user").get(user=user)
        if not is_orderable(profile):
            raise FlashError("not_eligible", "Votre profil n'est plus éligible aux missions.", 403)
        config = DispatchConfig.get_solo()
        busy = availability_issue(profile, req, config, now, check_online=False)
        if busy:
            log(req, "conflict", offer=offer, actor=user, reason=busy)
            raise FlashError("schedule_conflict", f"Acceptation impossible : {busy.lower()}.", 409)
        offer.status = MissionOffer.ACCEPTED
        try:
            with transaction.atomic():
                offer.save(update_fields=["status"])
        except IntegrityError:
            raise FlashError("already_assigned", "Cette mission a déjà été attribuée.", 409)
        booking = _assign(req, offer, user, offer.counter_amount, now)
        log(req, "counter_ok", offer=offer, actor=user, amount=str(offer.counter_amount))
        log(req, "assigned", offer=offer, actor=user, booking=booking.pk, amount=str(offer.counter_amount))
    return req


def _notify_counter(offer_id: int) -> None:
    from flash import notify

    notify.counter_received(offer_id)


def _notify_counter_answer(offer_id: int, accepted: bool) -> None:
    from flash import notify

    notify.counter_answered(offer_id, accepted)


# ═══ Désistement du professionnel retenu ════════════════════════════════════════════════════════════════════════════════

REOPEN_IMMEDIATE_HOURS = 6


def reopen_after_withdrawal(booking, actor_id: int, *, now=None) -> Optional[MissionRequest]:
    """Le professionnel retenu se désiste (il annule la réservation) : la MÊME demande reprend aussitôt sa recherche — aucun doublon
    de demande ni de proposition, il n'est plus jamais resollicité, les autres propositions de prix encore valables redeviennent
    choisissables. Créneau déjà passé : rien n'est relancé (le client relance s'il le souhaite)."""
    now = now or timezone.now()
    config = DispatchConfig.get_solo()
    with transaction.atomic():
        req = MissionRequest.objects.select_for_update(of=("self",)).filter(booking_id=booking.pk).first()
        if req is None or req.status != MissionRequest.ASSIGNED or req.assigned_to_id != actor_id:
            return None
        if req.is_immediate:
            if req.assigned_at and now - req.assigned_at > timedelta(hours=REOPEN_IMMEDIATE_HOURS):
                return None
        elif req.scheduled_for + timedelta(minutes=config.mission_duration_minutes) < now:
            return None
        req.offers.filter(status=MissionOffer.ACCEPTED, handyman_id=actor_id).update(status=MissionOffer.RESIGNED)
        restored = list(req.offers.filter(status=MissionOffer.WITHDRAWN, quote_amount__isnull=False, proposal_expires_at__gt=now)
                        .values_list("pk", flat=True)) if req.mode == MissionRequest.QUOTE else []
        if restored:
            MissionOffer.objects.filter(pk__in=restored).update(status=MissionOffer.QUOTED)
        req.status, req.assigned_to, req.booking, req.assigned_at = MissionRequest.SEARCHING, None, None, None
        req.closed_at, req.close_reason, req.next_step_at, req.consent_asked_at = None, "", now, None
        req.version += 1
        req.save(update_fields=["status", "assigned_to", "booking", "assigned_at", "closed_at", "close_reason", "next_step_at",
                                "consent_asked_at", "version", "updated_at"])
        log(req, "reopened", handyman=actor_id, booking=booking.pk, restored=restored)
        rid = req.pk
        transaction.on_commit(lambda: (_notify_reopened(rid, actor_id), launch_wave(rid)))
    return req


def _notify_reopened(request_id: int, pro_id: int) -> None:
    from flash import notify

    notify.reopened(request_id, pro_id)


def missed_streak(user_id: int) -> int:
    """Propositions consécutives (les plus récentes) restées sans réponse."""
    n = 0
    for status in MissionOffer.objects.filter(handyman_id=user_id).exclude(status__in=(MissionOffer.PENDING, MissionOffer.WITHDRAWN)) \
            .order_by("-sent_at", "-id").values_list("status", flat=True)[:50]:
        if status != MissionOffer.EXPIRED:
            break
        n += 1
    return n


def _maybe_pause(user_id: int, req: MissionRequest, config: DispatchConfig, now) -> None:
    """Mesure de disponibilité, PAS une sanction : aucun effet sur la réputation ; le pro est prévenu et peut revenir d'un geste."""
    if not config.auto_pause_after_missed:
        return
    streak = missed_streak(user_id)
    if streak < config.auto_pause_after_missed:
        return
    if HandymanProfile.objects.filter(user_id=user_id, online=True).update(online=False):
        log(req, "auto_paused", handyman=user_id, missed=streak)
        transaction.on_commit(lambda: _notify_paused(user_id, streak))


def _notify_paused(user_id: int, streak: int) -> None:
    from flash import notify

    notify.paused(user_id, streak)
