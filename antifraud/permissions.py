"""Comptes au téléphone NON vérifié : les actions sensibles leur sont refusées (403 `phone_not_verified`).

Actions concernées (appelées explicitement par chaque vue) — celles qui touchent d'autres personnes ou coûtent : réservation,
commande Tratra Flash, envoi de message, avis, paiement, transmission KYC, engagements longue durée (besoin publié, candidature,
contrat). Restent ouverts (parcours existants inchangés) : consulter, compléter son profil et ses adresses, préparer son annonce
de professionnel (jamais publiée avant éligibilité), vérifier son numéro, supprimer son compte. Le personnel n'est jamais concerné.

`UNVERIFIED_RESTRICTIONS=false` désactive la règle ; `UNVERIFIED_RESTRICTIONS_SINCE=AAAA-MM-JJ` exempte les comptes créés avant
cette date (clients historiques du pilote, inscrits avant l'obligation)."""
from __future__ import annotations

from datetime import date, datetime, time

from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import SAFE_METHODS, BasePermission

PHONE_NOT_VERIFIED = "Vérifiez votre numéro de téléphone pour continuer : un code vous est envoyé par SMS."


def _since():
    raw = str(getattr(settings, "UNVERIFIED_RESTRICTIONS_SINCE", "") or "").strip()
    if not raw:
        return None
    try:
        return timezone.make_aware(datetime.combine(date.fromisoformat(raw), time.min))
    except ValueError:
        return None


def is_restricted(user) -> bool:
    if not getattr(settings, "UNVERIFIED_RESTRICTIONS", True):
        return False
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff or user.is_superuser or getattr(user, "is_verified", False):
        return False
    since = _since()
    joined = getattr(user, "date_joined", None)
    if since is not None and joined is not None and joined < since:
        return False
    return True


def ensure_verified(user) -> None:
    """Lève 403 `phone_not_verified` si le compte n'a pas prouvé son numéro."""
    if is_restricted(user):
        from handy.api.errors import CodedAPIException

        raise CodedAPIException("phone_not_verified", PHONE_NOT_VERIFIED, status=403)


class PhoneVerifiedForWrites(BasePermission):
    """Écritures (POST, PUT, PATCH, DELETE) réservées aux comptes vérifiés ; lectures libres."""

    def has_permission(self, request, view):
        if request.method not in SAFE_METHODS:
            ensure_verified(request.user)
        return True
