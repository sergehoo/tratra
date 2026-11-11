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
    """Activation MANUELLE des commandes (recours de l'équipe) : l'activation est automatique à l'approbation de la pièce d'identité,
    sauf quand un dossier de risque la retient. Refusée tant que les pièces obligatoires ne sont pas approuvées : le Back-Office ne
    contourne jamais le workflow KYC. Lève aussi une suspension. N'attribue jamais le badge « Vérifié » (vérification faciale)."""
    from handy import eligibility

    if not profile.has_required_kyc():
        raise ValidationError("Les pièces obligatoires ne sont pas toutes approuvées.", code="kyc_incomplete")
    if profile.is_approved and not profile.suspended:
        raise ValidationError("Les commandes de ce dossier sont déjà activées.", code="already")
    profile.is_approved, profile.suspended = True, False
    profile.save(update_fields=["is_approved", "suspended"])
    text = ("Vos commandes sont activées : vous pouvez recevoir des réservations et des missions." if eligibility.is_orderable(profile)
            else "Votre identité est vérifiée. Il reste une étape pour recevoir des commandes : consultez votre espace professionnel.")
    notify(profile.user_id, "kyc_approved", text, title="Commandes activées" if eligibility.is_orderable(profile) else "Identité vérifiée",
           data={"kind": "kyc"}, dedupe_key=f"profile:{profile.pk}:approved:{int(timezone.now().timestamp())}")


@transaction.atomic
def suspend_profile(profile: HandymanProfile, *, by, reason: str) -> None:
    """Retire immédiatement la publication, les commandes, le badge et la validité du Tratra ID (règle d'éligibilité), que le profil
    soit vérifié ou seulement publié. Les pièces et la vérification faciale sont conservées : la levée rend les niveaux acquis."""
    if profile.suspended:
        raise ValidationError("Ce profil est déjà suspendu.", code="already")
    profile.suspended, profile.is_approved, profile.online = True, False, False
    profile.save(update_fields=["suspended", "is_approved", "online"])
    notify(profile.user_id, "kyc_rejected", "Votre profil professionnel est suspendu. Contactez le support Tratra pour en savoir plus.",
           title="Profil suspendu", data={"kind": "kyc"}, dedupe_key=f"profile:{profile.pk}:suspended:{int(timezone.now().timestamp())}")


@transaction.atomic
def restore_profile(profile: HandymanProfile, *, by, reason: str) -> dict:
    """Lève une suspension : le profil retrouve la publication, et les commandes si ses pièces obligatoires sont approuvées (décision
    explicite de l'équipe, journalisée par l'appelant). Le badge « Vérifié » dépend toujours de la vérification faciale."""
    from handy import eligibility

    if not profile.suspended:
        raise ValidationError("Ce profil n'est pas suspendu.", code="not_suspended")
    profile.suspended = False
    profile.is_approved = profile.has_required_kyc()
    profile.save(update_fields=["suspended", "is_approved"])
    notify(profile.user_id, "kyc_approved", "La suspension de votre profil professionnel est levée.", title="Profil rétabli",
           data={"kind": "kyc"}, dedupe_key=f"profile:{profile.pk}:restored:{int(timezone.now().timestamp())}")
    return {"published": eligibility.is_publishable(profile), "orders_enabled": eligibility.is_orderable(profile)}
