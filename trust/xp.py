"""XP Tratra : l'expérience CUMULÉE d'un professionnel, distincte du score de confiance.

- Gagnés uniquement sur des missions réellement terminées (réservation au statut « terminée ») ; jamais retirés.
- Anti-fraude : au-delà de `xp_pair_cap` missions récompensées avec le MÊME client sur 30 jours, la mission est enregistrée à 0 XP
  (raison affichée) — de fausses missions répétées entre deux comptes ne rapportent rien.
- Idempotent : une ligne par (professionnel, mission, motif), `sync` peut être rejoué sans effet double."""
from datetime import timedelta
from typing import Dict

from django.db import IntegrityError, transaction

from handy.models import Booking
from trust.models import TrustConfig, XpEntry

# Paliers (XP cumulés requis) : un nouveau professionnel commence au niveau 1, sans retard à rattraper.
LEVELS = [(0, "Débutant"), (300, "Initié"), (800, "Confirmé"), (1500, "Aguerri"), (2500, "Expert"), (4000, "Maître"), (6000, "Référence Tratra")]


def level_of(total: int) -> Dict:
    idx = max(i for i, (threshold, _) in enumerate(LEVELS) if total >= threshold)
    current, name = LEVELS[idx]
    nxt = LEVELS[idx + 1] if idx + 1 < len(LEVELS) else None
    return {"level": idx + 1, "name": name, "floor": current, "next": nxt[0] if nxt else None, "next_name": nxt[1] if nxt else None,
            "progress": round((total - current) / (nxt[0] - current), 3) if nxt else 1.0}


def _completed_at(booking: Booking):
    return booking.end_date or booking.updated_at


def award_for(booking: Booking, config: TrustConfig = None) -> int:
    """XP d'une mission terminée (rejouable). Renvoie les points ajoutés par cet appel."""
    if booking.status != "completed":
        return 0
    config = config or TrustConfig.get_solo()
    if XpEntry.objects.filter(user_id=booking.handyman_id, booking=booking, reason=XpEntry.MISSION).exists():
        return 0
    done = _completed_at(booking)
    rewarded_same_client = XpEntry.objects.filter(
        user_id=booking.handyman_id, reason=XpEntry.MISSION, points__gt=0, booking__client_id=booking.client_id,
        booking__end_date__gte=done - timedelta(days=30), booking__end_date__lte=done + timedelta(days=30)).exclude(booking=booking).count()
    capped = rewarded_same_client >= config.xp_pair_cap
    points = 0 if capped else config.xp_per_mission
    detail = (f"Plafond atteint : {config.xp_pair_cap} missions récompensées avec ce client sur 30 jours" if capped
              else f"Mission #{booking.pk} terminée")
    added = 0
    try:
        with transaction.atomic():
            XpEntry.objects.create(user_id=booking.handyman_id, booking=booking, reason=XpEntry.MISSION, points=points, detail=detail)
            added += points
            if points and getattr(booking, "flash_request", None) is not None and config.xp_flash_bonus:
                XpEntry.objects.create(user_id=booking.handyman_id, booking=booking, reason=XpEntry.FLASH_BONUS,
                                       points=config.xp_flash_bonus, detail="Mission obtenue avec Tratra Flash")
                added += config.xp_flash_bonus
    except IntegrityError:
        return 0   # course : un autre appel vient d'enregistrer cette mission
    return added


def sync(user_id: int) -> int:
    """Rattrape les missions terminées sans XP (historique antérieur, signal manqué)."""
    config = TrustConfig.get_solo()
    done = set(XpEntry.objects.filter(user_id=user_id, reason=XpEntry.MISSION).values_list("booking_id", flat=True))
    added = 0
    for booking in (Booking.objects.filter(handyman_id=user_id, status="completed").exclude(pk__in=done)
                    .select_related("flash_request").order_by("end_date", "id")):
        added += award_for(booking, config)
    return added


def summary(user_id: int, *, history: int = 20) -> Dict:
    sync(user_id)
    entries = XpEntry.objects.filter(user_id=user_id)
    total = sum(entries.values_list("points", flat=True))
    return {"total": total, **level_of(total), "missions": entries.filter(reason=XpEntry.MISSION).count(),
            "note": "Les XP récompensent les missions réellement terminées. Ils ne modifient pas le score de confiance.",
            "history": [{"points": e.points, "reason": e.get_reason_display(), "detail": e.detail, "booking": e.booking_id, "at": e.created_at}
                        for e in entries.order_by("-created_at", "-id")[:history]]}
