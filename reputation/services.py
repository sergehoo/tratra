"""Évaluation mutuelle d'une mission ponctuelle terminée : règles, scores et contestations (sans jamais inventer une donnée)."""
import re
from collections import Counter
from datetime import timedelta
from typing import Dict, Optional

from django.conf import settings
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.utils import timezone

from engagements.services.evaluations import SUSPICIOUS
from handy.models import Booking, BookingTimeline, Review
from handy.notifications import notify
from reputation import reveal
from reputation.models import ClientReview, EvaluationContest

DAILY_LIMIT = 10
MIN_PUBLIC_COUNT = 3        # sous ce nombre de notes révélées, aucune moyenne n'est publiée (une seule note n'est pas une réputation)


class EvaluationError(Exception):
    def __init__(self, code: str, detail: str, status: int = 409, fields: Optional[dict] = None):
        super().__init__(detail)
        self.code, self.detail, self.status, self.fields = code, detail, status, fields


def role_of(booking: Booking, user) -> Optional[str]:
    if user.pk == booking.client_id:
        return "client"
    if user.pk == booking.handyman_id:
        return "provider"
    return None


def completed_at(booking: Booking):
    row = BookingTimeline.objects.filter(booking=booking, status="completed").order_by("-at").values_list("at", flat=True).first()
    return row or booking.updated_at


def is_recurring_occurrence(booking: Booking) -> bool:
    return getattr(booking, "engagement_event", None) is not None


def criteria_keys(role: str):
    return Review.CRITERIA if role == "client" else ClientReview.CRITERIA


def criteria_labels(role: str) -> Dict[str, str]:
    return Review.CRITERIA_LABELS if role == "client" else ClientReview.CRITERIA_LABELS


def _clean(role: str, data) -> dict:
    errors: Dict[str, str] = {}
    try:
        rating = int(data.get("rating"))
        if not 1 <= rating <= 5:
            raise ValueError
    except (TypeError, ValueError):
        errors["rating"] = "Note : entier de 1 à 5 obligatoire."
        rating = None
    comment = str(data.get("comment") or "").strip()
    if len(comment) > 1000:
        errors["comment"] = "1000 caractères maximum."
    elif comment and SUSPICIOUS.search(comment):
        errors["comment"] = "Pas de lien, d'adresse e-mail ni de numéro de téléphone dans un commentaire."
    criteria = {}
    raw = data.get("criteria") or {}
    if not isinstance(raw, dict):
        errors["criteria"] = "Critères invalides."
        raw = {}
    for key, val in raw.items():
        if key not in criteria_keys(role):
            errors["criteria"] = "Critère inconnu pour cette personne évaluée."
            break
        try:
            score = int(val)
            if not 1 <= score <= 5:
                raise ValueError
        except (TypeError, ValueError):
            errors["criteria"] = "Chaque critère est noté de 1 à 5."
            break
        criteria[key] = score
    if errors:
        raise EvaluationError("invalid", "Évaluation invalide.", 400, errors)
    return {"rating": rating, "comment": comment, "criteria": criteria}


@transaction.atomic
def create(booking: Booking, user, data) -> object:
    booking = Booking.objects.select_for_update(of=("self",)).select_related("client", "handyman", "service").get(pk=booking.pk)
    role = role_of(booking, user)
    if role is None:
        raise EvaluationError("not_found", "Introuvable.", 404)
    if booking.status != "completed":
        raise EvaluationError("not_completed", "Une mission se note après avoir réellement été effectuée.")
    if is_recurring_occurrence(booking):
        raise EvaluationError("use_contract_evaluation", "Les missions d'un contrat se notent depuis le contrat (évaluation périodique ou finale).")
    if timezone.now() > completed_at(booking) + timedelta(days=int(getattr(settings, "EVALUATION_WINDOW_DAYS", 30))):
        raise EvaluationError("window_closed", "Le délai pour évaluer cette mission est écoulé.")
    already = Review.objects.filter(booking=booking).exists() if role == "client" else ClientReview.objects.filter(booking=booking).exists()
    if already:
        raise EvaluationError("already_evaluated", "Vous avez déjà évalué cette mission.")
    day_ago = timezone.now() - timedelta(hours=24)
    written = Review.objects.filter(booking__client=user, created_at__gte=day_ago).count() + ClientReview.objects.filter(author=user, created_at__gte=day_ago).count()
    if written >= DAILY_LIMIT:
        raise EvaluationError("rate_limited", "Trop d'évaluations en 24 heures : réessayez demain.", 429)
    clean = _clean(role, data)
    if role == "client":
        obj = Review.objects.create(booking=booking, rating=clean["rating"], comment=clean["comment"] or None, **clean["criteria"])
        other = booking.handyman
    else:
        obj = ClientReview.objects.create(booking=booking, author=user, subject=booking.client, rating=clean["rating"], comment=clean["comment"], **clean["criteria"])
        other = booking.client
    reveal.reveal_pair(booking)
    obj.refresh_from_db()
    if obj.revealed_at is None:
        notify(other, "evaluation_invite", "Votre interlocuteur vous a évalué. Évaluez-le à votre tour : les deux notes seront alors visibles.",
               title="Évaluation à laisser", data={"kind": "booking" if role == "provider" else "mission", "id": booking.pk}, dedupe_key=f"evaluation:{booking.pk}:{role}")
    return obj


def serialize(obj, role: str, viewer) -> dict:
    """Vue de l'AUTEUR (sa propre évaluation) : toujours visible ; la note reçue de l'autre partie n'est jamais incluse ici."""
    keys = criteria_keys(role)
    return {"id": obj.pk, "booking_id": obj.booking_id, "role": role, "rating": obj.rating, "comment": (obj.comment or ""),
            "criteria": {k: getattr(obj, k) for k in keys if getattr(obj, k) is not None}, "revealed": obj.revealed_at is not None, "created_at": obj.created_at}


def pending_for(user, limit: int = 20):
    """Missions ponctuelles terminées que l'utilisateur n'a pas encore évaluées, dans le délai, avec l'état de visibilité de la note de l'autre."""
    since = timezone.now() - timedelta(days=int(getattr(settings, "EVALUATION_WINDOW_DAYS", 30)))
    out = []
    mine = Booking.objects.filter(Q(client=user) | Q(handyman=user), status="completed", updated_at__gte=since - timedelta(days=1)) \
        .select_related("service", "client", "handyman").order_by("-updated_at")[:60]
    for b in mine:
        role = role_of(b, user)
        if is_recurring_occurrence(b) or completed_at(b) < since:
            continue
        done = Review.objects.filter(booking=b).exists() if role == "client" else ClientReview.objects.filter(booking=b).exists()
        if done:
            continue
        other_done = ClientReview.objects.filter(booking=b).exists() if role == "client" else Review.objects.filter(booking=b).exists()
        out.append({"booking_id": b.pk, "role": role, "evaluated_role": "provider" if role == "client" else "client",
                    "service": b.service.title if b.service_id else f"Réservation #{b.pk}", "completed_at": completed_at(b),
                    "deadline": completed_at(b) + timedelta(days=int(getattr(settings, "EVALUATION_WINDOW_DAYS", 30))),
                    "other_party_evaluated": other_done, "criteria": [{"key": k, "label": l} for k, l in criteria_labels("provider" if role == "client" else "client").items()]})
        if len(out) >= limit:
            break
    return out


def visible_client_reviews(user):
    return ClientReview.objects.filter(subject=user, is_hidden=False, revealed_at__isnull=False, booking__status="completed")


def requester_score(user) -> Dict:
    """Score DEMANDEUR : moyenne des notes reçues de prestataires, révélées et non masquées. Aucune moyenne sous `MIN_PUBLIC_COUNT` notes."""
    rows = list(visible_client_reviews(user).values("rating", *ClientReview.CRITERIA))
    n = len(rows)
    avg = round(sum(r["rating"] for r in rows) / n, 2) if n else None
    return {"count": n, "average": avg if n >= MIN_PUBLIC_COUNT else None, "public": n >= MIN_PUBLIC_COUNT,
            "criteria": {k: (round(sum(r[k] for r in rows if r[k] is not None) / c, 2) if (c := sum(1 for r in rows if r[k] is not None)) else None) for k in ClientReview.CRITERIA},
            "distribution": {str(i): sum(1 for r in rows if r["rating"] == i) for i in range(1, 6)}}


def provider_score(user) -> Dict:
    from handy.reviews import review_stats

    s = review_stats(user.pk)
    public = s["count"] >= MIN_PUBLIC_COUNT
    return {"count": s["count"], "average": s["average"] if public else None, "public": public, "criteria": s["criteria"], "distribution": s["distribution"]}


def history(user, months: int = 12):
    """Évolution mensuelle réelle (notes révélées) : prestataire et demandeur."""
    since = timezone.now() - timedelta(days=31 * months)
    prov = Review.objects.filter(booking__handyman=user, is_hidden=False, revealed_at__isnull=False, created_at__gte=since, booking__status="completed")
    req = visible_client_reviews(user).filter(created_at__gte=since)
    def by_month(qs):
        out = {}
        for d, r in qs.values_list("created_at", "rating"):
            out.setdefault(f"{d:%Y-%m}", []).append(r)
        return [{"month": m, "count": len(v), "average": round(sum(v) / len(v), 2)} for m, v in sorted(out.items())]
    return {"provider": by_month(prov), "requester": by_month(req)}


def missions_evaluated(user) -> int:
    """Nombre de missions réellement évaluées (notes révélées) où l'utilisateur est partie, comme prestataire ou comme demandeur."""
    as_provider = Review.objects.filter(booking__handyman=user, revealed_at__isnull=False, is_hidden=False).count()
    as_requester = visible_client_reviews(user).count()
    return as_provider + as_requester


@transaction.atomic
def contest(client_review: ClientReview, user, reason: str) -> EvaluationContest:
    if client_review.subject_id != user.pk:
        raise EvaluationError("not_found", "Introuvable.", 404)
    if client_review.revealed_at is None:
        raise EvaluationError("not_revealed", "Cette évaluation n'est pas encore visible.")
    reason = (reason or "").strip()[:500]
    if len(reason) < 10:
        raise EvaluationError("invalid", "Expliquez votre contestation (10 caractères minimum).", 400, {"reason": "Motif obligatoire."})
    obj, created = EvaluationContest.objects.get_or_create(client_review=client_review, author=user, defaults={"reason": reason})
    if not created:
        raise EvaluationError("already_contested", "Vous avez déjà contesté cette évaluation.")
    return obj
