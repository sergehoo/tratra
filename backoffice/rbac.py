"""Droits du Back-Office : rôles métier → permissions par module. Appliqués CÔTÉ SERVEUR par chaque endpoint.

Un membre du personnel (`is_staff`) reçoit un ou plusieurs rôles via les groupes Django `bo_<rôle>` ; un
super-utilisateur détient tous les droits. Aucun droit n'est déduit de l'interface : un bouton masqué ne protège rien,
la vue refuse. Les opérations sensibles sont journalisées (trust.AuditEvent)."""
from typing import Iterable, Set

# Permissions : <module>.<action>. « view » = lecture, « manage » = écriture métier, actions nommées = opérations sensibles.
PERMISSIONS = {
    "dashboard.view": "Tableau de bord et indicateurs",
    "users.view": "Consulter les comptes", "users.manage": "Suspendre / réactiver un compte",
    "kyc.review": "Valider, rejeter ou suspendre un dossier KYC (et consulter les pièces)",
    "trust.manage": "Badges, réputation, certifications",
    "tratra_id.manage": "QR professionnels et révocations",
    "services.moderate": "Catégories, métiers, tarifs et modération des services",
    "bookings.view": "Consulter les réservations et missions", "bookings.manage": "Annulations, litiges, médiation",
    "live.view": "Suivi des interventions (positions limitées) et incidents",
    "reviews.moderate": "Modérer commentaires, photos et réponses",
    "business.manage": "Organisations, sites, équipements, contrats, budgets, facturation",
    "finance.view": "Consulter paiements, commissions, remboursements",
    "finance.manage": "Rembourser, valider un retrait",
    "announcements.manage": "Créer, programmer et publier des annonces",
    "notifications.view": "Historique et état des envois (push, SMS, e-mail)",
    "continuity.view": "Activités en cours et erreurs de synchronisation",
    "support.manage": "Tickets, réclamations et médiation",
    "analytics.view": "Statistiques, filtres et exports",
    "settings.manage": "Règles métier et intégrations",
    "security.manage": "Rôles du personnel, sessions et journal d'audit",
}

ROLES = {
    "super_admin": set(PERMISSIONS),
    "ops": {"dashboard.view", "users.view", "kyc.review", "trust.manage", "tratra_id.manage", "services.moderate", "bookings.view",
            "bookings.manage", "live.view", "reviews.moderate", "business.manage", "continuity.view", "analytics.view",
            "notifications.view"},
    "support": {"dashboard.view", "users.view", "bookings.view", "bookings.manage", "reviews.moderate", "support.manage",
                "notifications.view", "continuity.view"},
    "finance": {"dashboard.view", "bookings.view", "finance.view", "finance.manage", "analytics.view", "business.manage"},
    "marketing": {"dashboard.view", "announcements.manage", "notifications.view", "analytics.view"},
    "analyst": {"dashboard.view", "analytics.view"},
}
GROUP_PREFIX = "bo_"


def role_group_name(role: str) -> str:
    return f"{GROUP_PREFIX}{role}"


def user_roles(user) -> Set[str]:
    if not (user and user.is_authenticated and user.is_active and user.is_staff):
        return set()
    if user.is_superuser:
        return {"super_admin"}
    names = set(user.groups.filter(name__startswith=GROUP_PREFIX).values_list("name", flat=True))
    return {n[len(GROUP_PREFIX):] for n in names if n[len(GROUP_PREFIX):] in ROLES}


def user_permissions(user) -> Set[str]:
    perms: Set[str] = set()
    for role in user_roles(user):
        perms |= ROLES[role]
    return perms


def has_permission(user, code: str) -> bool:
    return code in user_permissions(user)


def has_any(user, codes: Iterable[str]) -> bool:
    perms = user_permissions(user)
    return any(c in perms for c in codes)
