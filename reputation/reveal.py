"""Anti-représailles : la note qu'une partie reçoit est masquée tant qu'elle n'a pas évalué à son tour, ou jusqu'à l'expiration du délai
(`EVALUATION_REVEAL_DAYS`). Les statistiques publiques et le score ne comptent que les notes révélées."""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from handy.models import Booking, Review
from reputation.models import ClientReview


def blind_days() -> int:
    return int(getattr(settings, "EVALUATION_REVEAL_DAYS", 7))


def _refresh(handyman_ids):
    from handy.signal import refresh_handyman_rating

    for hid in set(handyman_ids):
        refresh_handyman_rating(hid)


def reveal_pair(booking: Booking) -> int:
    """Les deux parties ont évalué : les deux notes sont révélées. Renvoie le nombre de notes révélées."""
    review = Review.objects.filter(booking=booking).first()
    client_review = ClientReview.objects.filter(booking=booking).first()
    if review is None or client_review is None:
        return 0
    now, n = timezone.now(), 0
    if review.revealed_at is None:
        Review.objects.filter(pk=review.pk, revealed_at__isnull=True).update(revealed_at=now)
        n += 1
        _refresh([booking.handyman_id])
    if client_review.revealed_at is None:
        ClientReview.objects.filter(pk=client_review.pk, revealed_at__isnull=True).update(revealed_at=now)
        n += 1
    return n


def reveal_due(now=None) -> int:
    """Révèle les notes dont le délai est écoulé sans réponse de l'autre partie (tâche horaire, rejouable)."""
    now = now or timezone.now()
    cutoff = now - timedelta(days=max(blind_days(), 0))
    due_reviews = list(Review.objects.filter(revealed_at__isnull=True, created_at__lte=cutoff).values_list("pk", "booking__handyman_id"))
    if due_reviews:
        Review.objects.filter(pk__in=[p for p, _ in due_reviews]).update(revealed_at=now)
        _refresh([h for _, h in due_reviews])
    due_client = ClientReview.objects.filter(revealed_at__isnull=True, created_at__lte=cutoff).update(revealed_at=now)
    return len(due_reviews) + due_client
