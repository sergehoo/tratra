"""Accès « personnel » à l'ancienne API : un compte `is_staff` n'est plus un passe-droit global.

 * superutilisateur : tout ;
 * compte du personnel qui détient un rôle Back-Office : uniquement ce que son rôle autorise (droit `module.action`),
   jamais une lecture/écriture générale (pièces KYC, messages privés, positions GPS, paiements d'autrui…) ;
 * compte du personnel HISTORIQUE sans aucun rôle : comportement inchangé tant que `LEGACY_STAFF_BYPASS` est vrai
   (par défaut). Une fois les rôles attribués (`manage.py assign_legacy_staff_roles`), mettre
   `LEGACY_STAFF_BYPASS=False` ferme définitivement ce passe-droit.
Les opérations d'administration passent par `/handy/backoffice/` (droits par rôle, motifs, audit)."""
from typing import Optional

from django.conf import settings

from backoffice import rbac


def _perms(user):
    cached = getattr(user, "_staff_access_cache", None)
    if cached is None:
        cached = (bool(rbac.user_roles(user)), rbac.user_permissions(user))
        user._staff_access_cache = cached
    return cached


def staff_may(user, permission: Optional[str] = None) -> bool:
    if not (user and getattr(user, "is_authenticated", False) and getattr(user, "is_staff", False)):
        return False
    from backoffice import mfa

    if not mfa.satisfied(user):          # double authentification exigée : sans preuve, aucun droit « personnel » (même superutilisateur)
        return False
    if user.is_superuser:
        return True
    has_role, perms = _perms(user)
    if not has_role:
        return bool(getattr(settings, "LEGACY_STAFF_BYPASS", True))      # personnel historique sans rôle
    return permission is not None and permission in perms
