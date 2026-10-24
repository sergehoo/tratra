"""Suppression de compte à la demande de la personne (exigence Google Play et droit à l'effacement).

Principe : le compte est ANONYMISÉ et désactivé de façon irréversible, et toutes les données personnelles qui n'ont pas à être conservées
sont supprimées. Les enregistrements qui doivent survivre (réservations, paiements, retraits, avis, litiges : conservation légale et droits
des autres membres) restent rattachés à un compte « Compte supprimé » qui ne porte plus aucun nom, téléphone, e-mail, photo ni adresse.

Refusé tant qu'une obligation est en cours (mission ou réservation active, litige ouvert, gains à retirer, abonnement actif, contrat en vigueur,
organisation dont on est propriétaire) : la personne doit d'abord la régler, la liste exacte lui est montrée."""
import logging
import uuid
from collections import Counter
from decimal import Decimal
from typing import Dict, List

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)
User = get_user_model()
ACTIVE_BOOKING = ("pending", "confirmed", "in_progress")


class DeletionRefused(Exception):
    def __init__(self, blockers: List[Dict]):
        super().__init__("Suppression impossible tant que des éléments sont en cours.")
        self.blockers = blockers


def blockers(user) -> List[Dict]:
    """Éléments en cours qui empêchent la suppression : [{code, detail}]. Liste vide = suppression possible."""
    from business.models import Organization
    from engagements.models import EngagementContract, EngagementPosting
    from handy.models import Booking, Dispute, Subscription, artisan_available_earnings

    out: List[Dict] = []

    def add(code, detail):
        out.append({"code": code, "detail": detail})

    if user.is_staff or user.is_superuser:
        add("staff", "Un compte d'administration ne peut pas être supprimé depuis l'application.")
    n = Booking.objects.filter(status__in=ACTIVE_BOOKING).filter(client=user).count() + Booking.objects.filter(status__in=ACTIVE_BOOKING, handyman=user).count()
    if n:
        add("active_bookings", f"{n} réservation(s) ou mission(s) en cours : terminez-les ou annulez-les d'abord.")
    if Dispute.objects.filter(reporter=user, status__in=("open", "under_review")).exists():
        add("open_disputes", "Un litige que vous avez ouvert est en cours d'examen.")
    if artisan_available_earnings(user) > Decimal("0"):
        add("earnings", "Des gains sont disponibles : demandez leur retrait avant de supprimer votre compte.")
    if Subscription.objects.filter(user=user, status="active").exists():
        add("subscription", "Un abonnement est actif : résiliez-le d'abord.")
    if EngagementContract.objects.filter(status__in=EngagementContract.LIVE).filter(principal=user).exists() or \
            EngagementContract.objects.filter(status__in=EngagementContract.LIVE, worker=user).exists():
        add("contracts", "Un contrat d'engagement est en vigueur : terminez-le d'abord.")
    if EngagementPosting.objects.filter(publisher=user, status="open").exists():
        add("postings", "Un besoin longue durée est ouvert : clôturez-le d'abord.")
    if Organization.objects.filter(owner=user).exists():
        add("organization", "Vous êtes propriétaire d'une organisation Tratra Business : transférez-la ou clôturez-la d'abord.")
    return out


def _scrub_profiles(user, counts: Counter) -> None:
    from handy.management.commands.purge_accounts import delete_with_protected
    from handy.models import CompanyProfile, HandymanDocument, HandymanProfile, Service, ServiceImage

    profile = HandymanProfile.objects.filter(user=user).first()
    if profile is not None:
        try:
            from biometrics import services as biometrics

            biometrics.withdraw_consent(user)                       # supprime aussitôt les captures du visage et retire le consentement
        except Exception:
            logger.exception("Captures biométriques du compte #%s non supprimées", user.pk)
            raise
        for doc in HandymanDocument.objects.filter(handyman=profile):       # pièces d'identité et justificatifs : fichier ET ligne
            delete_with_protected(doc, counts)
        try:
            from trust.models import ProfessionalId

            ProfessionalId.objects.filter(profile=profile).delete()          # le QR professionnel cesse de vérifier quoi que ce soit
        except Exception:
            logger.exception("Tratra ID du compte #%s non supprimé", user.pk)
            raise
        profile.skills.clear()
        for field, empty in (("bio", None), ("license_number", None), ("cni_number", None), ("insurance_info", None), ("commune", None), ("quartier", None),
                             ("availability", {}), ("is_approved", False), ("online", False), ("trust_score", None), ("trust_badges", []),
                             ("photo", None), ("location", None)):
            setattr(profile, field, empty)
        profile.save()                                                    # enregistrement par le modèle : django-cleanup supprime le fichier de la photo
        for service in Service.objects.filter(handyman=user):
            service.is_active = False
            service.banner = None
            service.save(update_fields=["is_active", "banner"])
        ServiceImage.objects.filter(service__handyman=user).delete()
    company = CompanyProfile.objects.filter(user=user).first()
    if company is not None:
        CompanyProfile.objects.filter(pk=company.pk).update(company_name="Compte supprimé", registration_number=None, industry=None, address=None, city=None,
                                                            contact_person=None, phone=None, website=None, verified=False)


def _purge_messaging_and_statuses(user, counts: Counter) -> None:
    from handy.models import Conversation, Message
    from statuses.models import Status, StatusExclusion, StatusPreference, StatusView

    Message.objects.filter(sender=user).delete()                          # ses messages et leurs pièces jointes ; ceux de l'interlocuteur restent les siens
    for conv in Conversation.objects.filter(participants=user):
        conv.participants.remove(user)
        if conv.kind == Conversation.SUPPORT or not conv.participants.exists():
            conv.delete()
    Status.objects.filter(author=user).delete()                           # contenu et médias (django-cleanup supprime les fichiers)
    StatusView.objects.filter(viewer=user).delete()
    StatusExclusion.objects.filter(author=user).delete()
    StatusExclusion.objects.filter(excluded=user).delete()
    StatusPreference.objects.filter(user=user).delete()


@transaction.atomic
def delete_account(user, *, actor=None) -> Dict:
    """Anonymise et désactive le compte (irréversible). Lève DeletionRefused si une obligation est en cours."""
    from allauth.account.models import EmailAddress
    from allauth.socialaccount.models import SocialAccount
    from handy.models import (Device, FavoriteHandyman, MarketingConsent, Notification, NotificationPreference, OTPCode, SearchLog, UserAddress,
                              UserBlock)
    from business.models import Membership
    from trust.models import audit

    user = User.objects.select_for_update().get(pk=user.pk)
    if user.deleted_at is not None:
        return {"deleted": True, "already": True}
    reasons = blockers(user)
    if reasons:
        raise DeletionRefused(reasons)
    counts: Counter = Counter()
    _purge_messaging_and_statuses(user, counts)
    _scrub_profiles(user, counts)
    for model, field in ((Device, "user"), (Notification, "user"), (NotificationPreference, "user"), (MarketingConsent, "user"), (OTPCode, "user"),
                         (UserAddress, "user"), (SearchLog, "user"), (EmailAddress, "user"), (SocialAccount, "user"), (Membership, "user")):
        model.objects.filter(**{field: user}).delete()
    UserBlock.objects.filter(blocker=user).delete()
    UserBlock.objects.filter(blocked=user).delete()
    FavoriteHandyman.objects.filter(client=user).delete()
    FavoriteHandyman.objects.filter(handyman=user).delete()
    try:                                                                  # sessions : tous les jetons de rafraîchissement sont révoqués
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

        for token in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=token)
    except Exception:
        logger.warning("Jetons du compte #%s non révoqués", user.pk, exc_info=True)
    user.profile_picture = None
    user.save(update_fields=["profile_picture"])                          # supprime le fichier de la photo de profil
    User.objects.filter(pk=user.pk).update(
        username=f"supprime-{user.pk}-{uuid.uuid4().hex[:8]}", first_name="", last_name="", email=None, phone=None, address=None, city=None,
        postal_code=None, country=None, latitude=None, longitude=None, last_location=None, last_location_ts=None, is_active=False, is_verified=False,
        deleted_at=timezone.now(), password="!" + uuid.uuid4().hex)       # mot de passe inutilisable : aucune connexion possible
    from handy.eligibility import refresh_published
    from handy.models import HandymanProfile

    refresh_published(HandymanProfile.objects.filter(user_id=user.pk))   # compte désactivé : plus jamais publié
    audit("account.deleted", actor=actor or user, target_type="user", target_id=user.pk)       # aucune donnée personnelle dans la trace
    logger.info("Compte #%s supprimé (anonymisé)", user.pk)
    return {"deleted": True, "already": False}
