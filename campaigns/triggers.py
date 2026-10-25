"""Déclencheurs des campagnes : chacun lit des ÉVÉNEMENTS RÉELS en base et définit l'OBJECTIF qui arrête la campagne.

  candidates(campaign, now)  comptes concernés (et référence de l'objet déclencheur), événement survenu entre
                             « maintenant − délai − fenêtre » et « maintenant − délai » (jamais tout l'historique d'un coup) ;
  goal_met(user, ref)        objectif atteint → plus aucun message (vérifié à la programmation ET juste avant l'envoi).

Seuls les comptes actifs, non staff, au téléphone VÉRIFIÉ sont concernés ; rôle (client / artisan / entreprise) et communes déclarées
filtrés en SQL ; progression et conditions fines (profil, KYC) vérifiées en Python sur des lots bornés."""
from datetime import timedelta
from typing import Iterator, Optional, Tuple

from django.contrib.auth import get_user_model
from django.db.models import Exists, Max, OuterRef, Q

from announcements.services import in_cities, role_q

User = get_user_model()
ACTIVE_FLASH = ("searching", "quoting", "awaiting")


def base_users(campaign):
    users = User.objects.filter(is_active=True, is_staff=False, is_verified=True).filter(role_q(campaign.audience))
    return in_cities(users, campaign.communes).distinct()


def window(campaign, now):
    """(début, fin) de l'événement déclencheur : délai écoulé, sans remonter au-delà de la fenêtre."""
    end = now - timedelta(hours=campaign.delay_hours)
    return end - timedelta(days=campaign.max_age_days), end


# ── Conditions métier (une seule définition, utilisée partout) ────────────────────────────────────────────────────────────────

def artisan_profile_complete(user) -> bool:
    from handy.eligibility import PROFILE_KEYS, profile_checklist

    profile = getattr(user, "handyman_profile", None)
    return profile is not None and all(i["done"] for i in profile_checklist(profile) if i["key"] in PROFILE_KEYS)


def client_profile_complete(user) -> bool:
    return bool((user.first_name or "").strip() and (user.last_name or "").strip()) and user.addresses.exists()


def kyc_state(user) -> str:
    from handy.kyc_flow import kyc_status

    profile = getattr(user, "handyman_profile", None)
    return kyc_status(profile)["status"] if profile is not None else "none"


def has_service(user) -> bool:
    return user.services.exists()


def has_order(user) -> bool:
    from flash.models import MissionRequest

    return user.client_bookings.exists() or MissionRequest.objects.filter(client=user).exists()


def has_business_request(user) -> bool:
    from business.models import InterventionRequest

    return InterventionRequest.objects.filter(requested_by=user).exists()


def progress_of(user) -> str:
    """Étape la plus avancée du compte (ciblage « par progression »)."""
    from handy.eligibility import is_user_publishable

    if getattr(user, "handyman_profile", None) is not None:
        if is_user_publishable(user):
            return "active" if user.services.filter(is_active=True).exists() else "publishable"
        if kyc_state(user) == "approved":
            return "kyc_approved"
        return "profile_complete" if artisan_profile_complete(user) else "verified"
    if has_order(user) or has_business_request(user):
        return "active"
    return "profile_complete" if client_profile_complete(user) else "verified"


# ── Déclencheurs ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

class Trigger:
    key = ""
    audiences = ("clients", "artisans", "companies")
    goal_label = ""

    def candidates(self, campaign, now) -> Iterator[Tuple[int, str]]:
        start, end = window(campaign, now)
        for uid in base_users(campaign).filter(date_joined__gt=start, date_joined__lte=end).order_by("pk").values_list("pk", flat=True):
            yield uid, ""

    def start_ok(self, user, ref: str) -> bool:
        """Condition encore vraie au moment de programmer (sinon rien n'est programmé)."""
        return not self.goal_met(user, ref)

    def goal_met(self, user, ref: str) -> bool:
        return False


class Welcome(Trigger):
    key, goal_label = "welcome", "Message de bienvenue reçu"


class ProfileIncomplete(Trigger):
    key, audiences, goal_label = "profile_incomplete", ("clients", "artisans"), "Profil complété"

    def goal_met(self, user, ref):
        if getattr(user, "handyman_profile", None) is not None:
            return artisan_profile_complete(user)
        return client_profile_complete(user)


class KycPending(Trigger):
    key, audiences, goal_label = "kyc_pending", ("artisans",), "Pièce d'identité transmise"

    def goal_met(self, user, ref):
        return kyc_state(user) in ("pending", "approved")


class KycRejected(Trigger):
    key, audiences, goal_label = "kyc_rejected", ("artisans",), "Nouvelle pièce transmise"

    def candidates(self, campaign, now):
        from handy.models import HandymanDocument

        start, end = window(campaign, now)
        docs = (HandymanDocument.objects.filter(document_type="id_card", status="rejected", reviewed_at__gt=start, reviewed_at__lte=end,
                                                handyman__user__in=base_users(campaign)).order_by("pk").values_list("handyman__user_id", "pk"))
        for uid, doc_id in docs:
            yield uid, f"doc:{doc_id}"

    def start_ok(self, user, ref):
        return kyc_state(user) == "rejected"

    def goal_met(self, user, ref):
        return kyc_state(user) in ("pending", "approved")


class FirstService(Trigger):
    key, audiences, goal_label = "first_service", ("artisans",), "Première offre publiée"

    def goal_met(self, user, ref):
        return has_service(user)


class FirstOrder(Trigger):
    key, audiences, goal_label = "first_order", ("clients", "companies"), "Première demande ou réservation"

    def goal_met(self, user, ref):
        return has_order(user) or has_business_request(user)


class Review(Trigger):
    key, audiences, goal_label = "review", ("clients",), "Avis laissé"

    def candidates(self, campaign, now):
        from handy.models import Booking, Review as ReviewModel

        start, end = window(campaign, now)
        rows = (Booking.objects.filter(status="completed", updated_at__gt=start, updated_at__lte=end, client__in=base_users(campaign))
                .annotate(reviewed=Exists(ReviewModel.objects.filter(booking=OuterRef("pk")))).filter(reviewed=False)
                .order_by("pk").values_list("client_id", "pk"))
        for uid, booking_id in rows:
            yield uid, f"booking:{booking_id}"

    def goal_met(self, user, ref):
        from handy.models import Review as ReviewModel

        booking_id = int(ref.split(":", 1)[1]) if ref.startswith("booking:") else None
        return booking_id is None or ReviewModel.objects.filter(booking_id=booking_id).exists()


class ArtisanReviews(Trigger):
    key, audiences, goal_label = "artisan_reviews", ("artisans",), "Premier avis reçu"

    def candidates(self, campaign, now):
        from handy.models import Booking

        start, end = window(campaign, now)
        rows = (Booking.objects.filter(status="completed", handyman__in=base_users(campaign)).values("handyman_id")
                .annotate(last=Max("updated_at")).filter(last__gt=start, last__lte=end).order_by("handyman_id"))
        for row in rows:
            yield row["handyman_id"], ""

    def goal_met(self, user, ref):
        from handy.models import Review as ReviewModel

        return ReviewModel.objects.filter(booking__handyman=user).exists()


class Inactive(Trigger):
    """Inactivité : aucune connexion depuis `inactive_days` jours. Référence = jour de la dernière connexion : un nouvel épisode
    d'inactivité (après un retour) peut redéclencher la campagne, jamais deux fois le même."""
    key, goal_label = "inactive", "Retour sur Tratra"

    def candidates(self, campaign, now):
        end = now - timedelta(days=campaign.inactive_days)
        start = end - timedelta(days=campaign.max_age_days)
        rows = base_users(campaign).filter(last_login__gt=start, last_login__lte=end).order_by("pk").values_list("pk", "last_login")
        for uid, last in rows:
            yield uid, f"login:{last:%Y%m%d}"

    def goal_met(self, user, ref):
        if not user.last_login or not ref.startswith("login:"):
            return False
        return user.last_login.strftime("%Y%m%d") > ref.split(":", 1)[1]


class News(Trigger):
    """Nouveauté : une fois à toute l'audience, pendant la fenêtre qui suit l'activation (ou la date de début)."""
    key, goal_label = "news", "Nouveauté présentée"

    def candidates(self, campaign, now):
        start = campaign.starts_at or campaign.activated_at
        if start is None or now < start or now > start + timedelta(days=campaign.max_age_days):
            return
        for uid in base_users(campaign).order_by("pk").values_list("pk", flat=True):
            yield uid, ""


REGISTRY = {t.key: t for t in (Welcome(), ProfileIncomplete(), KycPending(), KycRejected(), FirstService(), FirstOrder(), Review(),
                               ArtisanReviews(), Inactive(), News())}


def trigger_for(campaign) -> Optional[Trigger]:
    return REGISTRY.get(campaign.trigger)


def operational_busy(user, now) -> bool:
    """Priorité absolue à Tratra Flash, aux réservations et à la sécurité : pas de message d'engagement pendant une demande Flash
    ouverte, une réservation en cours ou à moins de 24 h, ni dans les 2 h qui suivent une notification opérationnelle."""
    from flash.models import MissionRequest
    from handy.models import Booking, Notification

    if MissionRequest.objects.filter(client=user, status__in=ACTIVE_FLASH).exists():
        return True
    soon = Q(status="in_progress") | Q(status__in=("pending", "confirmed"), booking_date__lte=now + timedelta(hours=24),
                                        booking_date__gte=now - timedelta(hours=6))
    if Booking.objects.filter(Q(client=user) | Q(handyman=user)).filter(soon).exists():
        return True
    return Notification.objects.filter(user=user, category__in=("flash", "booking", "account", "live", "payment"),
                                       created_at__gte=now - timedelta(hours=2)).exists()
