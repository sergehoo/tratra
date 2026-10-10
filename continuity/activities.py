"""Activités en cours d'un utilisateur : ce que le serveur sait, source de vérité pour reprendre après une fermeture
d'application, une déconnexion, une coupure réseau, un plantage ou un changement de téléphone.

Strictement limité aux activités DE l'utilisateur (client, artisan ou demandeur Business). Jamais de coordonnées ni
d'adresse : la ville suffit pour reconnaître l'activité ; le détail se charge à l'ouverture (avec les contrôles habituels)."""
from typing import Dict, List, Optional

from django.db.models import Q

from business.models import InterventionRequest
from handy.api.dashboard import public_name
from handy.models import Booking

ACTIVE_BOOKING = ("pending", "confirmed", "in_progress")
CONTRACT_ACTIVE = ("pending_acceptance", "accepted", "active", "suspended", "notice")
STATUS_LABEL = dict(Booking.STATUS_CHOICES)
# Ordre de pertinence pour « Reprendre ma mission » : ce qui se passe maintenant d'abord.
PRIORITY = {"in_progress": 0, "confirmed": 1, "pending": 2}
LIMIT = 50


def _resume_label(role: str, status: str) -> str:
    if role == "handyman":
        return "Reprendre ma mission" if status in ("confirmed", "in_progress") else "Répondre à la demande"
    return "Suivre ma réservation"


def booking_item(b: Booking, user) -> Dict:
    role = "client" if b.client_id == user.id else "handyman"
    other = b.handyman if role == "client" else b.client
    return {
        "kind": "mission" if role == "handyman" else "booking",
        "id": b.id,
        "role": role,
        "status": b.status,
        "status_label": STATUS_LABEL.get(b.status, b.status),
        "version": b.version,
        "title": (b.service.title if b.service_id else None) or "Intervention",
        "counterpart": public_name(other),
        "booking_date": b.booking_date,
        "city": b.city or None,
        "updated_at": b.updated_at,
        "active": b.status in ACTIVE_BOOKING,
        "deeplink": f"tratra://{'mission' if role == 'handyman' else 'booking'}/{b.id}",
        "resume_label": _resume_label(role, b.status),
    }


def business_item(r: InterventionRequest) -> Dict:
    return {
        "kind": "business_request", "id": r.id, "role": "requester", "status": r.status,
        "status_label": dict(InterventionRequest.STATUSES).get(r.status, r.status), "version": None,
        "title": r.title, "counterpart": r.organization.name, "booking_date": r.desired_date, "city": None,
        "updated_at": r.updated_at, "active": r.status in InterventionRequest.OPEN,
        "deeplink": f"tratra://business_request/{r.id}", "resume_label": "Suivre ma demande",
    }


def contract_item(c, user) -> Dict:
    """Engagement récurrent ou de longue durée : reprise « Mon contrat » (jamais d'adresse ni de montant ici)."""
    from engagements.services.common import party_of

    role = party_of(c, user)
    other = c.worker if role == "principal" else c.principal
    return {
        "kind": "contract", "id": c.id, "role": role, "status": c.status, "status_label": dict(c.STATUSES).get(c.status, c.status), "version": c.version,
        "title": c.title, "counterpart": public_name(other), "booking_date": c.start_date, "city": c.location_city or None, "updated_at": c.updated_at,
        "active": c.status in CONTRACT_ACTIVE, "deeplink": f"tratra://contract/{c.id}",
        "resume_label": "Accepter le contrat" if c.status == "pending_acceptance" else "Voir mon contrat",
    }


def _contracts(user):
    from engagements.services.common import contracts_for

    return contracts_for(user).select_related("principal", "worker", "category")


def _bookings(user):
    return (Booking.objects.filter(Q(client=user) | Q(handyman=user))
            .select_related("client", "handyman", "service"))


def _requests(user):
    return InterventionRequest.objects.filter(requested_by=user).select_related("organization")


def active_for(user) -> List[Dict]:
    items = [booking_item(b, user) for b in _bookings(user).filter(status__in=ACTIVE_BOOKING).order_by("booking_date")[:LIMIT]]
    items += [business_item(r) for r in _requests(user).filter(status__in=InterventionRequest.OPEN).order_by("-updated_at")[:LIMIT]]
    items += [contract_item(c, user) for c in _contracts(user).filter(status__in=CONTRACT_ACTIVE).order_by("-updated_at")[:LIMIT]]
    items.sort(key=lambda i: (PRIORITY.get(i["status"], 3), str(i["booking_date"] or "9999")))
    return items


def changes_since(user, since) -> List[Dict]:
    """Activités modifiées depuis `since` (y compris terminées ou annulées) : un second appareil apprend ce qui a changé."""
    items = [booking_item(b, user) for b in _bookings(user).filter(updated_at__gte=since).order_by("-updated_at")[:LIMIT]]
    items += [business_item(r) for r in _requests(user).filter(updated_at__gte=since).order_by("-updated_at")[:LIMIT]]
    items += [contract_item(c, user) for c in _contracts(user).filter(updated_at__gte=since).order_by("-updated_at")[:LIMIT]]
    items.sort(key=lambda i: str(i["updated_at"]), reverse=True)
    return items[:LIMIT]


def primary(items: List[Dict]) -> Optional[Dict]:
    """Activité à reprendre en priorité : missions/réservations en cours, puis confirmées, puis en attente."""
    pool = [i for i in items if i["kind"] not in ("business_request", "contract")] or items
    return pool[0] if pool else None
