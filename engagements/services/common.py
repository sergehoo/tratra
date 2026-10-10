"""Briques communes des services d'engagements : erreurs typées, rôles des parties, historique, notifications."""
import logging
from typing import List, Optional

from django.contrib.auth import get_user_model
from django.db.models import Q

from business import rbac as business_rbac
from business.models import Membership, Role
from engagements.models import ContractEvent, EngagementContract
from handy.eligibility import is_user_publishable
from handy.notifications import notify

logger = logging.getLogger(__name__)
User = get_user_model()


class EngagementError(Exception):
    """Refus métier : `code` stable pour les clients, `message` en français, statut HTTP associé."""

    def __init__(self, code: str, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra


def conflict(code: str, message: str, **extra) -> EngagementError:
    return EngagementError(code, message, 409, **extra)


def moment(today=None):
    """Horodatage d'un événement de calendrier (début, fin) : maintenant, ou midi du jour simulé quand une tâche rattrape une date
    passée ou qu'un test avance dans le temps — les durées de contrat restent ainsi cohérentes avec la date de référence."""
    from django.utils import timezone
    if today is None or today == timezone.localdate():
        return timezone.now()
    from datetime import datetime, time
    return timezone.make_aware(datetime.combine(today, time(12, 0)))


# ── Parties ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def principal_side(contract: EngagementContract, user) -> bool:
    """Le donneur d'ordre, ou — pour un contrat d'organisation — un membre autorisé à engager l'organisation."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if contract.organization_id:
        # Contrat d'organisation : seule l'adhésion ACTIVE et habilitée compte — le créateur qui a quitté l'organisation perd l'accès.
        membership = business_rbac.membership_for(user, contract.organization_id)
        return bool(membership and business_rbac.can(membership, "engagements.manage"))
    return contract.principal_id == user.id


def party_of(contract: EngagementContract, user) -> Optional[str]:
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    if contract.worker_id == user.id:
        return "worker"
    return "principal" if principal_side(contract, user) else None


def managed_org_ids(user) -> List[int]:
    """Organisations que `user` peut engager (adhésion active + capacité `engagements.manage`)."""
    return [m.organization_id for m in Membership.objects.filter(user=user, is_active=True, organization__is_active=True).select_related("organization")
            if business_rbac.can(m, "engagements.manage")]


def contracts_for(user):
    """Contrats visibles de `user` : ceux où il est donneur d'ordre ou prestataire, et ceux de ses organisations s'il peut les engager.
    Un brouillon n'est visible que du côté donneur d'ordre (le prestataire ne le voit qu'une fois proposé)."""
    return EngagementContract.objects.filter((Q(principal=user) & Q(organization__isnull=True)) | Q(organization_id__in=managed_org_ids(user)) | (Q(worker=user) & ~Q(status="draft")))


def counterpart(role: str) -> str:
    return "worker" if role == "principal" else "principal"


def party_users(contract: EngagementContract, role: str) -> List:
    """Destinataires d'une notification pour un rôle : le prestataire, ou le donneur d'ordre (+ responsables de l'organisation)."""
    if role == "worker":
        return [contract.worker]
    users = {} if contract.organization_id else {contract.principal_id: contract.principal}
    if contract.organization_id:
        members = (Membership.objects.filter(organization_id=contract.organization_id, is_active=True, role__in=[Role.OWNER, Role.ADMIN])
                   .select_related("user")[:10])
        for m in members:
            users.setdefault(m.user_id, m.user)
    return list(users.values())


def organization_actor(user, organization_id) -> bool:
    """`user` peut-il agir au nom de l'organisation (publier un besoin, proposer un contrat) ?"""
    membership = business_rbac.membership_for(user, organization_id)
    return bool(membership and business_rbac.can(membership, "engagements.manage"))


def require_eligible_worker(user, message: str = "Ce prestataire n'est pas (ou plus) vérifié par Tratra.") -> None:
    if not is_user_publishable(user):
        raise conflict("worker_not_verified", message)


# ── Historique et notifications ─────────────────────────────────────────────────────────────────────────────────────

def record(contract: EngagementContract, actor, type_: str, **data) -> ContractEvent:
    """Historique en ajout seulement. Les données ne contiennent jamais de secret ni de coordonnées."""
    return ContractEvent.objects.create(contract=contract, actor=actor if getattr(actor, "pk", None) else None, type=type_,
                                        data={k: (v.isoformat() if hasattr(v, "isoformat") else (str(v) if hasattr(v, "quantize") else v)) for k, v in data.items()})


def notify_role(contract: EngagementContract, role: str, ntype: str, message: str, *, title: str = "", key: str, exclude_user=None) -> None:
    """Notifie un rôle du contrat (déduplication par `key`) ; lien profond vers le contrat."""
    for u in party_users(contract, role):
        if exclude_user is not None and u.pk == getattr(exclude_user, "pk", None):
            continue
        notify(u, ntype, message, title=title, data={"kind": "contract", "id": contract.pk}, dedupe_key=f"eng:{contract.pk}:{key}:{u.pk}")


def public_name(user) -> str:
    from handy.api.dashboard import public_name as _name

    return _name(user)
