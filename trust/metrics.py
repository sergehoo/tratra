"""Mesures de confiance calculées depuis les données RÉELLES de la plateforme.

Aucune valeur n'est inventée : sans échantillon suffisant, la mesure vaut `None` (et n'entre pas dans le
score — un nouvel artisan n'est donc pas pénalisé par l'absence d'historique). Chaque mesure indique sa
source : « vérifié » (décision de l'équipe : KYC, justificatifs), « plateforme » (activité observée) ou
« déclaré » (saisi par l'artisan, non vérifié).
"""
from datetime import timedelta
from statistics import median
from typing import Dict, Optional

from django.utils import timezone

from handy.eligibility import is_publishable
from handy.models import Booking, BookingTimeline, Dispute, HandymanDocument
from handy.reviews import review_stats


def window_start(config, now=None):
    return (now or timezone.now()) - timedelta(days=config.sure_window_days)


def completed_missions(user_id, since=None):
    qs = Booking.objects.filter(handyman_id=user_id, status="completed")
    if since is not None:
        qs = qs.filter(booking_date__gte=since)
    return qs


def actual_start(booking) -> Optional["timezone.datetime"]:
    """Heure réelle de présence sur les lieux : le plus tôt de (arrivée déclarée par l'artisan — ignorée si elle a
    été déclarée à plus de 500 m du lieu connu —, vérification d'identité par le client, premier passage « en cours »)."""
    candidates = []
    session = getattr(booking, "tracking_session", None)
    if session is not None and session.arrived_at and (session.arrival_distance_m is None
                                                       or session.arrival_distance_m <= 500):
        candidates.append(session.arrived_at)
    check = booking.identity_checks.order_by("verified_at").first() if booking.pk else None
    if check is not None:
        candidates.append(check.verified_at)
    entry = BookingTimeline.objects.filter(booking=booking, status="in_progress").order_by("at").first()
    if entry:
        candidates.append(entry.at)
    return min(candidates) if candidates else None


def punctuality(profile, config, now=None) -> Dict:
    """Part des missions terminées (période d'observation) démarrées au plus tard `tolérance` après l'heure
    prévue. Les missions sans heure de démarrage enregistrée ne sont pas mesurables : elles sont écartées."""
    tolerance = timedelta(minutes=config.punctuality_tolerance_minutes)
    on_time = measured = 0
    for booking in completed_missions(profile.user_id, window_start(config, now)).order_by("-booking_date")[:200]:
        started = actual_start(booking)
        if started is None:
            continue
        measured += 1
        if started <= booking.booking_date + tolerance:
            on_time += 1
    return {"rate": round(on_time / measured, 3) if measured else None, "sample": measured,
            "on_time": on_time, "tolerance_minutes": config.punctuality_tolerance_minutes}


def reactivity(profile, config, now=None) -> Dict:
    """Délai médian (minutes) entre la demande et sa confirmation par l'artisan, sur la période."""
    since = window_start(config, now)
    delays = []
    rows = (BookingTimeline.objects.filter(booking__handyman_id=profile.user_id, status="confirmed",
                                           booking__created_at__gte=since)
            .select_related("booking").order_by("booking_id", "at"))
    seen = set()
    for row in rows:
        if row.booking_id in seen:
            continue
        seen.add(row.booking_id)
        delays.append(max(0.0, (row.at - row.booking.created_at).total_seconds() / 60))
    return {"median_minutes": round(median(delays), 1) if delays else None, "sample": len(delays)}


def disputes(profile, config, now=None) -> Dict:
    """Litiges ouverts contre les missions terminées de l'artisan, rapportés à ces missions."""
    since = window_start(config, now)
    missions = completed_missions(profile.user_id, since).count()
    disputed = (Dispute.objects.filter(booking__handyman_id=profile.user_id, booking__booking_date__gte=since)
                .exclude(status="rejected").values("booking_id").distinct().count())
    return {"count": disputed, "missions": missions, "rate": round(disputed / missions, 3) if missions else None}


def certifications(profile, today=None):
    """Justificatifs professionnels APPROUVÉS par l'équipe et encore valides."""
    today = today or timezone.localdate()
    docs = (HandymanDocument.objects.filter(handyman=profile, document_type="certification", status="approved")
            .select_related("category").order_by("-reviewed_at", "-id"))
    return [d for d in docs if d.expires_on is None or d.expires_on >= today]


def collect(profile, config, now=None) -> Dict:
    """Toutes les mesures d'un artisan (une seule passe de lecture)."""
    now = now or timezone.now()
    since = window_start(config, now)
    reviews = review_stats(profile.user_id)
    return {
        "verified": is_publishable(profile),
        "account_active": bool(profile.user.is_active),
        "reviews": reviews,
        "punctuality": punctuality(profile, config, now),
        "reactivity": reactivity(profile, config, now),
        "disputes": disputes(profile, config, now),
        "completed_total": completed_missions(profile.user_id).count(),
        "completed_window": completed_missions(profile.user_id, since).count(),
        "certifications": certifications(profile),
        "declared_experience_years": profile.experience_years or 0,
    }
