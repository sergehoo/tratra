"""Opérations métier du Back-Office partagées par plusieurs modules. Chacune respecte le workflow existant :
rien n'est inventé (pas de badge ni de validation KYC forcés), la règle d'éligibilité reste la source unique."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from handy.models import Booking, Device, HandymanProfile, User
from handy.notifications import notify


def revoke_all_sessions(user) -> int:
    """Révoque tous les jetons de rafraîchissement de l'utilisateur (déconnexion de tous ses appareils)."""
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

    count = 0
    for token in OutstandingToken.objects.filter(user=user):
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        count += int(created)
    return count


ACTIVE_BOOKING = ("pending", "confirmed", "in_progress")


def active_booking_count(user) -> int:
    return (Booking.objects.filter(client=user, status__in=ACTIVE_BOOKING).count()
            + Booking.objects.filter(handyman=user, status__in=ACTIVE_BOOKING).count())


@transaction.atomic
def suspend_user(user: User, *, by, reason: str) -> dict:
    """Suspend un compte : connexion impossible, sessions révoquées, plus aucun push. Les réservations en cours ne sont
    JAMAIS annulées automatiquement (décision métier humaine) : leur nombre est renvoyé pour que l'opérateur agisse."""
    if user.pk == by.pk:
        raise ValidationError("Vous ne pouvez pas suspendre votre propre compte.", code="self")
    if user.is_staff or user.is_superuser:
        raise ValidationError("Un compte d'administration se gère depuis « Sécurité et audit ».", code="staff")
    if not user.is_active:
        raise ValidationError("Ce compte est déjà suspendu.", code="already")
    user.is_active = False
    user.save(update_fields=["is_active"])          # la réévaluation Trust / Tratra ID suit par signal, dans la transaction
    sessions = revoke_all_sessions(user)
    Device.objects.filter(user=user).delete()
    return {"sessions_revoked": sessions, "active_bookings": active_booking_count(user)}


@transaction.atomic
def reactivate_user(user: User) -> None:
    if user.is_active:
        raise ValidationError("Ce compte est déjà actif.", code="already")
    user.is_active = True
    user.save(update_fields=["is_active"])


@transaction.atomic
def approve_profile(profile: HandymanProfile, *, by) -> None:
    """Approbation humaine du dossier artisan. Refusée tant que les pièces obligatoires ne sont pas approuvées :
    le Back-Office ne contourne jamais le workflow KYC."""
    if not profile.has_required_kyc():
        raise ValidationError("Les pièces obligatoires ne sont pas toutes approuvées.", code="kyc_incomplete")
    if profile.is_approved:
        raise ValidationError("Ce dossier est déjà approuvé.", code="already")
    profile.is_approved = True
    profile.save(update_fields=["is_approved"])
    notify(profile.user_id, "kyc_approved", "Votre profil professionnel a été approuvé : vous pouvez recevoir des missions.",
           title="Profil approuvé", data={"kind": "kyc"}, dedupe_key=f"profile:{profile.pk}:approved:{int(timezone.now().timestamp())}")


@transaction.atomic
def suspend_profile(profile: HandymanProfile, *, by, reason: str) -> None:
    """Retire immédiatement la publication, les missions et la validité du Tratra ID (règle d'éligibilité)."""
    if not profile.is_approved:
        raise ValidationError("Ce dossier n'est pas approuvé.", code="not_approved")
    profile.is_approved = False
    profile.online = False
    profile.save(update_fields=["is_approved", "online"])
    notify(profile.user_id, "kyc_rejected", "Votre profil professionnel est suspendu. Contactez le support Tratra pour en savoir plus.",
           title="Profil suspendu", data={"kind": "kyc"}, dedupe_key=f"profile:{profile.pk}:suspended:{int(timezone.now().timestamp())}")
