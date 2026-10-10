"""Rôles et capacités (RBAC) de Tratra Business : décidés côté serveur, jamais par l'interface.

Un compte agit dans une organisation uniquement via une adhésion ACTIVE ; sans adhésion, l'organisation n'existe pas
pour lui (404). Les rôles « site » sont en plus bornés à leurs sites (Membership.sites)."""
from typing import Optional, Set

from business.models import Membership, Organization, Role

ALL = {
    "org.manage", "org.delete", "members.manage", "sites.manage", "equipment.manage", "requests.create",
    "requests.view_all", "requests.approve", "requests.dispatch", "contracts.manage", "preventive.manage",
    "budgets.manage", "invoices.manage", "reports.view", "audit.view", "approval_rules.manage", "view.structure",
}

ROLE_CAPS = {
    Role.OWNER: ALL,
    Role.ADMIN: ALL - {"org.delete"},
    Role.SITE_MANAGER: {"view.structure", "equipment.manage", "requests.create", "requests.view_all", "requests.approve",
                        "requests.dispatch", "preventive.manage", "reports.view"},
    Role.APPROVER: {"view.structure", "requests.view_all", "requests.approve", "reports.view"},
    Role.REQUESTER: {"view.structure", "requests.create"},
    Role.FINANCE: {"view.structure", "requests.view_all", "requests.approve", "budgets.manage", "invoices.manage", "reports.view",
                   "audit.view"},
    Role.VIEWER: {"view.structure", "requests.view_all", "reports.view"},
}

UNSCOPED_ROLES = {Role.OWNER, Role.ADMIN}


def membership_for(user, org_id) -> Optional[Membership]:
    """Adhésion active de `user` dans l'organisation active `org_id`, sinon None (l'organisation n'existe pas pour lui)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return (Membership.objects.select_related("organization")
            .filter(user=user, organization_id=org_id, is_active=True, organization__is_active=True).first())


def capabilities(membership: Membership) -> Set[str]:
    return set(ROLE_CAPS.get(membership.role, set()))


def can(membership: Membership, capability: str) -> bool:
    return capability in ROLE_CAPS.get(membership.role, set())


def scoped_site_ids(membership: Membership) -> Optional[Set[int]]:
    """None = tous les sites ; sinon l'ensemble des sites autorisés."""
    if membership.role in UNSCOPED_ROLES:
        return None
    ids = set(membership.sites.values_list("id", flat=True))
    return ids or None


def site_allowed(membership: Membership, site_id: int) -> bool:
    scope = scoped_site_ids(membership)
    return scope is None or site_id in scope
