"""Recommandations de services : moteur DÉTERMINISTE (aucun fournisseur d'IA requis), explicable critère par critère.

Jamais de prestataire non éligible : seuls les services actifs de profils publiables (KYC approuvé, profil complet, compte actif) sont
candidats. Aucune donnée inventée : un critère sans donnée vaut « inconnu » (score neutre) et est signalé comme tel."""
import math
import unicodedata
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from django.db.models import Q
from django.utils import timezone

from handy import eligibility
from handy.models import AvailabilitySlot, Booking, Service, TimeOff
from handy.reviews import review_stats
from transport import pricing

WEIGHTS = {"relevance": 35, "distance": 20, "reputation": 20, "availability": 10, "history": 10, "price": 5}
RADIUS_KM = 25.0
MIN_REVIEWS = 3
Point = Tuple[float, float]


def _norm(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (text or "").lower()) if unicodedata.category(c) != "Mn")


def _haversine_km(a: Point, b: Point) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dphi, dl = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _tokens(text: str) -> set:
    return {t for t in _norm(text).replace("'", " ").split() if len(t) > 2}


def _available(profile, when: Optional[datetime]) -> Tuple[Optional[bool], str]:
    """Disponibilité RÉELLE : créneaux hebdomadaires déclarés et absences ; sans `when`, l'état « en ligne » ; sinon inconnu."""
    if when is None:
        return (True, "En ligne maintenant") if profile.online else (None, "Disponibilité à confirmer")
    at = pricing.local(when)
    if TimeOff.objects.filter(handyman=profile, start__lte=when, end__gte=when).exists():
        return False, "Absent à ce moment"
    slots = AvailabilitySlot.objects.filter(handyman=profile)
    if not slots.exists():
        return None, "Horaires non renseignés"
    ok = slots.filter(weekday=at.weekday(), start_time__lte=at.time().replace(tzinfo=None), end_time__gte=at.time().replace(tzinfo=None)).exists()
    return (True, "Disponible sur ce créneau") if ok else (False, "Hors de ses horaires déclarés")


def recommend(user, *, category=None, query: str = "", location: Optional[Point] = None, when: Optional[datetime] = None, limit: int = 6, with_transport: bool = True) -> Dict:
    wanted = _tokens(query)
    qs = (Service.objects.filter(is_active=True, handyman__in=eligibility.publishable().values("user_id"))
          .exclude(handyman=user).select_related("handyman", "handyman__handyman_profile", "category"))
    if category is not None:
        qs = qs.filter(category=category)
    candidates = list(qs[:200])
    if not candidates:
        return {"results": [], "nearby": [], "criteria": WEIGHTS, "total_candidates": 0}

    past = Booking.objects.filter(client=user, status="completed").values_list("handyman_id", "service__category_id")
    done_with, done_cat = {h for h, _ in past}, {c for _, c in past}
    prices = sorted(float(s.price) for s in candidates if s.price is not None)
    median = prices[len(prices) // 2] if prices else None

    rows = []
    for s in candidates:
        profile, reasons, parts = s.handyman.handyman_profile, [], {}
        text = _tokens(f"{s.title} {s.description} {s.category.name if s.category_id else ''}")
        if category is not None:
            rel = 1.0
            reasons.append("Catégorie demandée")
        elif wanted:
            rel = len(wanted & text) / len(wanted)
            if rel:
                reasons.append("Correspond à votre besoin")
        else:
            rel = 0.4
        parts["relevance"] = rel

        origin = pricing.provider_origin(s.handyman)
        km = round(_haversine_km(origin, location), 1) if origin and location else None
        parts["distance"] = max(0.0, 1 - km / RADIUS_KM) if km is not None else 0.0
        if km is not None:
            reasons.append(f"À environ {km} km (à vol d'oiseau)")
        else:
            reasons.append("Distance inconnue")

        stats = review_stats(s.handyman_id)
        if stats["count"] >= MIN_REVIEWS and stats["average"]:
            parts["reputation"] = stats["average"] / 5
            reasons.append(f"Note {stats['average']}/5 sur {stats['count']} avis")
        else:
            parts["reputation"] = 0.5
            reasons.append("Peu d'avis : note non retenue")

        ok, why = _available(profile, when)
        parts["availability"] = 1.0 if ok else 0.5 if ok is None else 0.0
        reasons.append(why)

        parts["history"] = 1.0 if s.handyman_id in done_with else 0.5 if (s.category_id in done_cat) else 0.0
        if s.handyman_id in done_with:
            reasons.append("Déjà réservé avec succès")
        parts["price"] = 0.5 if (s.price is None or not median) else max(0.0, min(1.0, 1.5 - float(s.price) / median)) if median else 0.5

        score = round(sum(WEIGHTS[k] * parts[k] for k in WEIGHTS), 1)
        rows.append({"service_id": s.pk, "title": s.title, "category": s.category.name if s.category_id else None, "handyman_id": s.handyman_id,
                     "provider_name": (s.handyman.first_name or "Prestataire").strip(), "price": float(s.price) if s.price is not None else None, "price_type": s.price_type,
                     "score": score, "distance_km": km, "available": ok, "reasons": reasons, "rating": stats["average"] if stats["count"] >= MIN_REVIEWS else None,
                     "reviews": stats["count"], "_user": s.handyman, "_service": s})
    rows.sort(key=lambda r: (-r["score"], r["distance_km"] if r["distance_km"] is not None else 1e9, r["service_id"]))
    top = rows[:limit]
    if with_transport:
        for r in top:                                         # le transport n'est calculé (distance routière) que pour les meilleurs résultats
            q = pricing.quote(handyman=r["_user"], destination=location, when=when or timezone.now(), needs_travel=r["_service"].requires_travel) if location else None
            r["transport"] = {"amount": q["amount"], "applicable": q["applicable"], "fallback": q["fallback"], "distance_unavailable": q["distance_unavailable"]} if q else None
    nearby = sorted((r for r in rows if r["distance_km"] is not None), key=lambda r: r["distance_km"])[:limit]
    for r in rows:
        r.pop("_user", None), r.pop("_service", None)
    for r in top:
        r.setdefault("transport", None)
    return {"results": top, "nearby": [{k: r[k] for k in ("service_id", "title", "provider_name", "distance_km", "available", "price")} for r in nearby],
            "criteria": WEIGHTS, "total_candidates": len(candidates)}
