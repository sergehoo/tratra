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
from handy.eligibility import is_publishable, publishable
from handy.models import AvailabilitySlot, Booking, HandymanProfile, Service, ServiceArea, ServiceCategory, TimeOff

logger = logging.getLogger(__name__)

ACCEPT_GRACE_SECONDS = 3          # latence réseau : une acceptation partie juste avant l'échéance reste valable
BUSY_BOOKING_STATUSES = ("confirmed", "in_progress")


class FlashError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra


def log(req: MissionRequest, kind: str, *, offer: Optional[MissionOffer] = None, actor=None, **data) -> DispatchEvent:
    return DispatchEvent.objects.create(request=req, offer=offer, kind=kind, actor=actor, data=data)


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


def zone_of(profile: HandymanProfile, req: MissionRequest, config: DispatchConfig):
    """(dans la zone ?, distance en km ou None). Position du pro, sinon centre de sa zone d'intervention ; à défaut, même commune."""
    area = getattr(profile, "service_area", None)
    origin = profile.location or (area.center if area is not None else None)
    radius = config.radius_km
    if area is not None and area.radius_km:
        radius = min(radius, float(area.radius_km))
    if req.location is not None and origin is not None:
        d = haversine_km(origin, req.location)
        return d <= radius, round(d, 2)
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
    answered = [s for st, s in rows if st in (MissionOffer.ACCEPTED, MissionOffer.QUOTED, MissionOffer.DECLINED)]
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


def _zone_filter(req: MissionRequest, config: DispatchConfig) -> Optional[Q]:
    """Préfiltre SQL de la zone, servi par l'index spatial : SUR-ENSEMBLE de `zone_of` (position du pro, sinon centre de sa zone
    d'intervention, sinon même commune) ; la règle exacte reste appliquée à chaque profil. None : personne (ni position ni commune)."""
    commune = (req.commune or "").strip().lower()
    same_commune = (HandymanProfile.objects.annotate(_c=Lower(Trim("commune")), _q=Lower(Trim("quartier")))
                    .filter(Q(_c=commune) | Q(_q=commune))) if commune else None
    if req.location is None:
        return Q(pk__in=same_commune.values("pk")) if same_commune is not None else None
    zone = (Q(pk__in=HandymanProfile.objects.filter(proximity.near("location", req.location, config.radius_km)).values("pk"))
            | Q(pk__in=ServiceArea.objects.filter(proximity.near("center", req.location, config.radius_km), handyman__location__isnull=True)
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


def candidates(req: MissionRequest, config: DispatchConfig, now=None, *, explain: bool = False, listing: bool = False):
    """Professionnels éligibles et disponibles, classés. Avec `explain=True`, renvoie aussi les écartés et pourquoi (Back-Office).
    `listing=True` : liste montrée au CLIENT pour choisir son professionnel (demande pas encore créée) — une proposition en attente
    ailleurs n'écarte personne (le client choisit ; le pro répondra).

    Coût constant : seuls les profils de la zone (index spatial) sont chargés, et leurs disponibilités et historiques sont lus en
    quelques requêtes groupées, quel que soit leur nombre. Les écartés hors zone (`explain`) viennent d'une seule requête légère."""
    now = now or timezone.now()
    family = category_family(req.category)
    offered = set(req.offers.values_list("handyman_id", flat=True)) if req.pk else set()
    busy_elsewhere = set() if listing else set(
        MissionOffer.objects.filter(status=MissionOffer.PENDING, expires_at__gt=now).exclude(request=req).values_list("handyman_id", flat=True))
    base = (publishable(HandymanProfile.objects.all())
            .filter(Q(user__services__is_active=True, user__services__category_id__in=family) | Q(skills__id__in=family))
            .exclude(user_id=req.client_id))
    zone = _zone_filter(req, config)
    profiles = list(base.filter(zone).select_related("user", "service_area").distinct()) if zone is not None else []
    min_years = required_experience(req.category)
    reasons: Dict[int, str] = {}
    in_zone_ok = []
    for profile in profiles:
        reason = _early_reason(profile.user_id, profile.experience_years, offered, busy_elsewhere, min_years)
        in_zone, distance = zone_of(profile, req, config)
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
    outside = base.exclude(zone) if zone is not None else base
    for user_id, years in outside.values_list("user_id", "experience_years").distinct():
        rejected.append({"user_id": user_id, "reason": _early_reason(user_id, years, offered, busy_elsewhere, min_years) or "Hors zone"})
    return kept, rejected


# ═══ Cycle de vie d'une demande ═════════════════════════════════════════════════════════════════════════════════════════

def is_immediate(when, config: DispatchConfig, now=None) -> bool:
    return when <= (now or timezone.now()) + timedelta(minutes=config.immediate_horizon_minutes)


def create_request(client, *, category: ServiceCategory, address: str, scheduled_for=None, mode: str = MissionRequest.FIRM,
                   amount=None, commune: str = "", city: str = "Abidjan", postal_code: str = "", description: str = "",
                   lat=None, lng=None, matching: str = MissionRequest.AUTO, target_id=None, service_id=None) -> MissionRequest:
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
            matching=matching, target=target, service=service)
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


def launch_wave(request_id: int, *, now=None) -> List[MissionOffer]:
    """Lance la vague suivante si la demande est ouverte et qu'aucune proposition n'attend de réponse. Rejouable sans effet double."""
    config = DispatchConfig.get_solo()
    now = now or timezone.now()
    with transaction.atomic():
        req = MissionRequest.objects.select_for_update(of=("self",)).select_related("category", "category__parent").get(pk=request_id)
        if req.status != MissionRequest.SEARCHING:
            return []
        if req.offers.filter(status=MissionOffer.PENDING).exists():
            return []
        if req.matching == MissionRequest.DIRECT:
            # Professionnel choisi par le client : jamais de vague. Sans réponse positive, le CLIENT décide (autre pro, Smart Dispatch, annuler).
            from flash import hybrid

            hybrid.after_targeted_response(req, config, now)
            return []
        quotes = req.offers.filter(status=MissionOffer.QUOTED).count()
        if req.wave >= config.max_waves or (req.mode == MissionRequest.QUOTE and quotes >= config.max_quotes):
            _finish_search(req, config, now)
            return []
        ranked, rejected = candidates(req, config, now, explain=True)
        chosen = ranked[: config.wave_size]
        if not chosen:
            if req.wave == 0:
                log(req, "no_candidate", excluded=len(rejected), reasons=_reason_counts(rejected))
            _finish_search(req, config, now)
            return []
        req.wave += 1
        req.save(update_fields=["wave", "updated_at"])
        expires = now + timedelta(seconds=_timeout(req, config))
        offers = []
        for rank, cand in enumerate(chosen, start=1):
            offer = MissionOffer.objects.create(request=req, handyman_id=cand.profile.user_id, wave=req.wave, rank=rank,
                                                score=cand.score, score_detail=cand.detail, distance_km=cand.distance_km, expires_at=expires)
            offers.append(offer)
            log(req, "offer_sent", offer=offer, handyman=cand.profile.user_id, rank=rank, score=cand.score, distance_km=cand.distance_km)
        log(req, "wave", wave=req.wave, sent=len(offers), eligible=len(ranked), excluded=len(rejected),
            reasons=_reason_counts(rejected), expires_at=expires.isoformat())
        ids = [o.pk for o in offers]
        transaction.on_commit(lambda: _after_wave(req.pk, req.wave, ids, _timeout(req, config)))
    return offers


def _reason_counts(rejected: List[Dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rejected:
        out[r["reason"]] = out.get(r["reason"], 0) + 1
    return out


def _after_wave(request_id: int, wave: int, offer_ids: List[int], timeout: int) -> None:
    from flash import notify

    for oid in offer_ids:
        notify.new_offer(oid)
    try:
        from flash.tasks import wave_timeout

        wave_timeout.apply_async(args=(request_id, wave), countdown=timeout + 2, retry=False)
    except Exception:   # sans broker : la tâche périodique `flash.tasks.tick` (30 s) prend le relais
        logger.info("Échéance de vague confiée à la tâche périodique (demande #%s).", request_id)


def _finish_search(req: MissionRequest, config: DispatchConfig, now) -> None:
    """Plus de vague possible : sur devis avec au moins un devis → le client choisit ; sinon → aucun professionnel."""
    if req.mode == MissionRequest.QUOTE and req.offers.filter(status=MissionOffer.QUOTED).exists():
        req.status, req.quote_deadline = MissionRequest.QUOTING, now + timedelta(hours=config.quote_window_hours)
        req.save(update_fields=["status", "quote_deadline", "updated_at"])
        return
    _close(req, MissionRequest.UNFULFILLED, "Aucun professionnel disponible n'a accepté.", now)
    log(req, "unfulfilled", waves=req.wave)
    transaction.on_commit(lambda: _notify_unfulfilled(req.pk))


def _notify_unfulfilled(request_id: int) -> None:
    from flash import notify

    notify.unfulfilled(request_id)


def _close(req: MissionRequest, status: str, reason: str, now) -> None:
    req.status, req.closed_at, req.close_reason = status, now, reason[:200]
    req.version += 1
    req.save(update_fields=["status", "closed_at", "close_reason", "version", "updated_at"])
    _withdraw_others(req, keep=None)


def _withdraw_others(req: MissionRequest, keep: Optional[int]) -> List[int]:
    """Retire les propositions encore ouvertes : leur alerte est arrêtée sur les téléphones (après validation)."""
    qs = req.offers.filter(status__in=(MissionOffer.PENDING, MissionOffer.QUOTED))
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
        request_id = MissionOffer.objects.filter(pk=offer_id, handyman=user).values_list("request_id", flat=True).first()
        if request_id is None:
            raise FlashError("not_found", "Proposition introuvable.", 404)
        req = MissionRequest.objects.select_for_update().get(pk=request_id)   # verrou : demande d'abord, toujours
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
        if not is_publishable(profile):
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
    req.version += 1
    req.save(update_fields=["status", "assigned_to", "booking", "assigned_at", "closed_at", "close_reason", "version", "updated_at"])
    _withdraw_others(req, keep=offer.pk)
    transaction.on_commit(lambda: _closed([offer.pk]))   # l'alerte du gagnant s'arrête aussi (autres appareils)
    return booking


def decline(offer_id: int, user, reason: str = "", *, now=None) -> MissionOffer:
    """Refus : JAMAIS pénalisé. Si plus personne n'est en attente dans la vague, la suivante part aussitôt."""
    now = now or timezone.now()
    with transaction.atomic():
        offer = _offer_for(offer_id, user)
        if offer.status == MissionOffer.DECLINED:
            return offer
        if offer.status != MissionOffer.PENDING:
            raise FlashError("offer_closed", "Cette proposition n'attend plus de réponse.", 409)
        _respond(offer, MissionOffer.DECLINED, now)
        offer.decline_reason = reason if reason in dict(MissionOffer.DECLINE_REASONS) else ""
        offer.save(update_fields=["status", "responded_at", "response_seconds", "decline_reason"])
        log(offer.request, "declined", offer=offer, actor=user, reason=offer.decline_reason, response_seconds=offer.response_seconds)
        request_id = offer.request_id
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
        request_id = MissionOffer.objects.filter(pk=offer_id, handyman=user).values_list("request_id", flat=True).first()
        if request_id is None:
            raise FlashError("not_found", "Proposition introuvable.", 404)
        req = MissionRequest.objects.select_for_update().get(pk=request_id)
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
        offer.save(update_fields=["status", "responded_at", "response_seconds", "quote_amount", "quote_message"])
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
        offer = MissionOffer.objects.select_for_update().select_related("handyman").filter(pk=offer_id, request=req).first()
        if offer is None:
            raise FlashError("not_found", "Devis introuvable.", 404)
        if req.status == MissionRequest.ASSIGNED and req.assigned_to_id == offer.handyman_id:
            return req
        if not req.is_open:
            raise FlashError("request_closed", "Cette demande n'est plus ouverte.", 409)
        if offer.status != MissionOffer.QUOTED:
            raise FlashError("quote_unavailable", "Ce devis n'est plus disponible.", 409)
        profile = HandymanProfile.objects.select_for_update(of=("self",)).select_related("user").get(user_id=offer.handyman_id)
        if not is_publishable(profile):
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

def expire_due(*, now=None) -> Dict[str, int]:
    """Expire les propositions échues, enchaîne les vagues, ferme les fenêtres de choix des devis. Idempotent."""
    now = now or timezone.now()
    config = DispatchConfig.get_solo()
    expired, touched = 0, set()
    for offer in MissionOffer.objects.filter(status=MissionOffer.PENDING, expires_at__lt=now - timedelta(seconds=ACCEPT_GRACE_SECONDS)).select_related("request"):
        with transaction.atomic():
            updated = MissionOffer.objects.filter(pk=offer.pk, status=MissionOffer.PENDING).update(status=MissionOffer.EXPIRED)
            if not updated:
                continue
            expired += 1
            touched.add(offer.request_id)
            log(offer.request, "expired", offer=offer, waited_seconds=int((offer.expires_at - offer.sent_at).total_seconds()))
            _maybe_pause(offer.handyman_id, offer.request, config, now)
            transaction.on_commit(lambda oid=offer.pk: _closed([oid]))
    for rid in touched:
        launch_wave(rid, now=now)
    # Demandes ouvertes sans proposition en attente (vague perdue, redémarrage) : on relance.
    for rid in (MissionRequest.objects.filter(status=MissionRequest.SEARCHING).exclude(offers__status=MissionOffer.PENDING)
                .exclude(pk__in=touched).values_list("pk", flat=True)[:200]):
        launch_wave(rid, now=now)
    closed = 0
    for req in MissionRequest.objects.filter(status=MissionRequest.QUOTING, quote_deadline__lt=now):
        with transaction.atomic():
            locked = MissionRequest.objects.select_for_update().get(pk=req.pk)
            if locked.status != MissionRequest.QUOTING:
                continue
            _close(locked, MissionRequest.UNFULFILLED, "Aucun devis retenu dans le délai.", now)
            log(locked, "unfulfilled", reason="quote_window_elapsed")
            transaction.on_commit(lambda rid=locked.pk: _notify_unfulfilled(rid))
            closed += 1
    return {"expired": expired, "requests": len(touched), "quote_windows_closed": closed}


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
