"""Relation « contact Tratra » et blocages — dérivées des données métier EXISTANTES, sans nouveau système de relations.

Deux membres sont en contact lorsque, sur Tratra, ils ont :
 - une réservation acceptée (confirmée, en cours ou terminée) l'un avec l'autre ;
 - un contrat d'engagement en vigueur ou terminé, ou une candidature retenue ;
 - échangé des messages dans une même conversation (chacun a écrit au moins une fois).
Un blocage (dans un sens ou l'autre) supprime la relation. Le résultat est mis en cache brièvement par membre."""
from typing import Set

from django.core.cache import cache
from django.db.models import Q

TTL = 120


def _key(user_id: int) -> str:
    return f"contacts:v1:{user_id}"


def blocked_ids(user_id: int) -> Set[int]:
    """Membres bloqués PAR l'utilisateur ou l'ayant bloqué : invisibles et injoignables dans les deux sens."""
    from handy.models import UserBlock

    ids: Set[int] = set()
    for blocker, blocked in UserBlock.objects.filter(Q(blocker_id=user_id) | Q(blocked_id=user_id)).values_list("blocker_id", "blocked_id"):
        ids.add(blocked if blocker == user_id else blocker)
    return ids


def is_blocked(a_id: int, b_id: int) -> bool:
    from handy.models import UserBlock

    return UserBlock.objects.filter(Q(blocker_id=a_id, blocked_id=b_id) | Q(blocker_id=b_id, blocked_id=a_id)).exists()


def _compute(user_id: int) -> Set[int]:
    from django.db.models import Count
    from engagements.models import EngagementApplication, EngagementContract
    from handy.models import Booking, Conversation, Message

    ids: Set[int] = set()
    live = ("confirmed", "in_progress", "completed")
    for client, pro in Booking.objects.filter(Q(client_id=user_id) | Q(handyman_id=user_id), status__in=live).values_list("client_id", "handyman_id"):
        ids.update((client, pro))
    for principal, worker in (EngagementContract.objects.filter(Q(principal_id=user_id) | Q(worker_id=user_id))
                              .exclude(status__in=("draft", "pending_acceptance", "cancelled")).values_list("principal_id", "worker_id")):
        ids.update((principal, worker))
    for publisher, applicant in (EngagementApplication.objects.filter(Q(applicant_id=user_id) | Q(posting__publisher_id=user_id), status="selected")
                                 .values_list("posting__publisher_id", "applicant_id")):
        ids.update((publisher, applicant))
    # Conversations (hors fil « Équipe Tratra ») où l'autre membre ET l'utilisateur ont chacun écrit.
    mine = (Conversation.objects.filter(participants=user_id).exclude(kind=Conversation.SUPPORT)
            .filter(messages__sender_id=user_id).values_list("pk", flat=True).distinct())
    rows = (Message.objects.filter(conversation_id__in=list(mine)).exclude(sender_id=user_id).values_list("sender_id", flat=True).distinct())
    ids.update(rows)
    ids.discard(user_id)
    return ids


def contact_ids(user_id: int) -> Set[int]:
    """Membres en relation avec l'utilisateur, blocages exclus."""
    cached = cache.get(_key(user_id))
    if cached is None:
        cached = sorted(_compute(user_id))
        cache.set(_key(user_id), cached, TTL)
    return set(cached) - blocked_ids(user_id)


def version(user_id: int) -> str:
    """Change à chaque évolution des relations d'un membre (nouveau message, blocage) : sert de clé aux fils mis en cache."""
    return str(cache.get(f"contacts:vv:{user_id}") or 0)


def invalidate(*user_ids: int) -> None:
    import time

    cache.delete_many([_key(u) for u in user_ids])
    for u in user_ids:
        cache.set(f"contacts:vv:{u}", time.time_ns(), None)
