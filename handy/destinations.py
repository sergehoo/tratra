"""Registre CENTRAL des destinations de l'application (liens profonds `tratra://<clé>[/<id>]`).

Une seule source de vérité pour :
 - les annonces (liste proposée dans le Back-Office, validation à l'enregistrement et à la publication) ;
 - les notifications push (lien ouvert quand on touche la notification, application ouverte ou fermée) ;
 - le site (chemin web équivalent, pour le même bouton dans le flux des annonces).

Chaque destination déclare les rôles qui peuvent l'ouvrir : une annonce ne peut viser un écran que si TOUS ses destinataires y ont
accès (ex. « Ma réputation » : artisans seulement). L'application revérifie le rôle à l'ouverture et n'affiche jamais une page
non autorisée. Les objets privés d'un seul compte (une réservation, une conversation…) ne sont jamais proposés dans une annonce :
ils seraient refusés à tous les autres destinataires — ils restent réservés aux notifications individuelles.

Toute nouvelle clé doit exister aussi dans l'application (lib/core/deep_links.dart) ; tests : handy/test_destinations.py et
test/deep_links_test.dart (même liste)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.core.exceptions import ValidationError

CLIENTS, ARTISANS, COMPANIES = "clients", "artisans", "companies"
EVERYONE = frozenset({CLIENTS, ARTISANS, COMPANIES})
ROLE_LABELS = {CLIENTS: "clients", ARTISANS: "artisans", COMPANIES: "entreprises"}


@dataclass(frozen=True)
class Destination:
    key: str
    label: str
    group: str
    roles: frozenset = EVERYONE
    param: str = ""              # "" | "category" | "service" | "announcement" | "object" (objet privé, notifications seulement)
    param_required: bool = False
    announce: bool = True        # proposable dans une annonce
    web: str = ""                # chemin du site (« {id} » remplacé) ; vide = calculé (catégorie, prestation) ou aucun

    def accepts(self, roles) -> bool:
        return set(roles) <= set(self.roles)


DISCOVER, ORDER, ACTIVITY, ACCOUNT, PRO, BUSINESS = (
    "Découvrir", "Commander", "Mon activité", "Mon compte", "Espace professionnel", "Entreprises")

REGISTRY = (
    # Découvrir — tout compte
    Destination("home", "Accueil de l'application", DISCOVER, web="/dashboard"),
    Destination("explore", "Explorer les services", DISCOVER, web="/search"),
    Destination("categories", "Tous les métiers", DISCOVER, web="/metiers"),
    Destination("category", "Un métier ou une prestation du catalogue", DISCOVER, param="category", param_required=True),
    Destination("services", "Toutes les offres", DISCOVER, web="/search"),
    Destination("service", "Une offre précise", DISCOVER, param="service", param_required=True),
    Destination("search", "Recherche", DISCOVER, web="/search"),
    Destination("urgent", "Dépannages urgents", DISCOVER, web="/search"),
    # Commander (Tratra Flash / Hybrid Matching)
    Destination("flash_order", "Trouvez-moi un professionnel (nouvelle demande)", ORDER, web="/dashboard/commander"),
    Destination("favorites", "Mes professionnels favoris", ORDER, web="/dashboard/favoris"),
    # Mon activité
    Destination("bookings", "Mes réservations", ACTIVITY, web="/dashboard/bookings"),
    Destination("messages", "Messages", ACTIVITY, web="/dashboard/messages"),
    Destination("notifications", "Notifications", ACTIVITY, web="/dashboard/notifications"),
    Destination("announcement", "Annonces", ACTIVITY, param="announcement", web="/dashboard/announcements"),
    Destination("reviews", "Mes avis", ACTIVITY, web="/dashboard/reviews"),
    Destination("engagements", "Engagements longue durée", ACTIVITY, web="/dashboard/engagements"),
    # Mon compte
    Destination("profile", "Mon compte", ACCOUNT, web="/dashboard/profile"),
    Destination("addresses", "Mes adresses", ACCOUNT, web="/dashboard/profile"),
    Destination("kyc", "Vérification d'identité", ACCOUNT, web="/dashboard/profile/kyc"),
    Destination("pro", "Espace professionnel (ou devenir professionnel)", ACCOUNT, web="/dashboard/provide"),
    # Espace professionnel — artisans
    Destination("reputation", "Ma réputation (Tratra Trust)", PRO, roles=frozenset({ARTISANS}), web="/dashboard/reputation"),
    Destination("badge", "Mon badge Tratra ID", PRO, roles=frozenset({ARTISANS}), web="/dashboard/badge"),
    Destination("availability", "Tratra Flash : disponibilité et propositions", PRO, roles=frozenset({ARTISANS})),
    Destination("replacements", "Remplacements à pourvoir", PRO, roles=frozenset({ARTISANS}), web="/dashboard/engagements/replacements"),
    # Entreprises
    Destination("business", "Espace Business", BUSINESS, roles=frozenset({COMPANIES}), web="/dashboard/business"),
    # Objets privés d'un seul compte : notifications individuelles uniquement
    Destination("booking", "Une réservation", ACTIVITY, param="object", param_required=True, announce=False, web="/dashboard/bookings/{id}"),
    Destination("mission", "Une mission", PRO, roles=frozenset({ARTISANS}), param="object", param_required=True, announce=False,
                web="/dashboard/provider/missions/{id}"),
    Destination("conversation", "Une conversation", ACTIVITY, param="object", param_required=True, announce=False,
                web="/dashboard/messages?c={id}"),
    Destination("contract", "Un contrat", ACTIVITY, param="object", param_required=True, announce=False,
                web="/dashboard/engagements/contracts/{id}"),
    Destination("posting", "Une offre d'engagement", ACTIVITY, param="object", param_required=True, announce=False,
                web="/dashboard/engagements/postings/{id}"),
    Destination("business_request", "Une demande d'entreprise", BUSINESS, roles=frozenset({COMPANIES}), param="object", announce=False,
                web="/dashboard/business/requests"),
    Destination("flash_offer", "Une proposition de mission", PRO, roles=frozenset({ARTISANS}), param="object", param_required=True,
                announce=False, web="/dashboard/flash/offres/{id}"),
    Destination("flash_request", "Une demande Tratra Flash", ORDER, param="object", param_required=True, announce=False,
                web="/dashboard/demandes/{id}"),
    Destination("trust_penalty", "Décision Tratra Trust", PRO, roles=frozenset({ARTISANS}), announce=False, web="/dashboard/reputation"),
)
BY_KEY = {d.key: d for d in REGISTRY}


def parse(value: str) -> tuple:
    """« clé » ou « clé/123 » → (Destination|None, id|None, erreur|None)."""
    key, sep, ident = (value or "").strip().partition("/")
    dest = BY_KEY.get(key)
    if dest is None:
        return None, None, "Écran de l'application inconnu."
    if sep and not ident.isdigit():
        return dest, None, "Identifiant invalide."
    obj_id = int(ident) if ident else None
    if obj_id is not None and not dest.param:
        return dest, None, f"« {dest.label} » ne prend pas d'identifiant."
    if obj_id is None and dest.param_required:
        return dest, None, f"Choisissez {_param_noun(dest)} pour « {dest.label} »."
    return dest, obj_id, None


def _param_noun(dest: Destination) -> str:
    return {"category": "le métier ou la prestation", "service": "l'offre", "announcement": "l'annonce"}.get(dest.param, "l'élément")


def _target(dest: Destination, obj_id: Optional[int]):
    """Objet public désigné (catégorie active, offre publiée, annonce), ou None s'il n'existe pas / n'est pas public."""
    if obj_id is None:
        return None
    if dest.param == "category":
        from handy.models import ServiceCategory

        return ServiceCategory.objects.filter(pk=obj_id, is_active=True).first()
    if dest.param == "service":
        from handy.eligibility import restrict_public_services
        from handy.models import Service

        return restrict_public_services(Service.objects.select_related("category")).filter(pk=obj_id).first()
    if dest.param == "announcement":
        from announcements.models import Announcement

        return Announcement.objects.filter(pk=obj_id).first()
    return None


def validate_for_announcement(value: str, roles) -> Destination:
    """Destination d'une annonce : connue, proposable, paramètre présent et PUBLIC, accessible à tous les destinataires."""
    dest, obj_id, error = parse(value)
    if error:
        raise ValidationError(error)
    if not dest.announce:
        raise ValidationError(f"« {dest.label} » est propre à un seul compte : choisissez un écran commun à tous les destinataires.")
    if obj_id is not None and dest.param in ("category", "service") and _target(dest, obj_id) is None:
        raise ValidationError("Ce métier n'est pas actif." if dest.param == "category" else "Cette offre n'est pas publiée (inactive ou artisan non vérifié).")
    roles = [r for r in roles if r in EVERYONE]
    refused = [ROLE_LABELS[r] for r in roles if r not in dest.roles]
    if refused:
        allowed = ", ".join(ROLE_LABELS[r] for r in sorted(dest.roles))
        raise ValidationError(f"« {dest.label} » n'est accessible qu'aux {allowed} : retirez les {', '.join(refused)} des destinataires "
                              f"ou choisissez un autre écran.")
    return dest


def describe(value: str) -> dict:
    """Libellé lisible d'une destination (aperçu du Back-Office) : « Une offre précise — Réparation de fuite (Plomberie) »."""
    dest, obj_id, error = parse(value)
    if dest is None:
        return {"key": None, "label": "Écran inconnu", "detail": "", "roles": [], "valid": False}
    target = _target(dest, obj_id) if not error else None
    detail = ""
    if target is not None:
        if dest.param == "service":
            detail = f"{target.title} ({target.category.name})"
        elif dest.param == "category":
            detail = target.name
        elif dest.param == "announcement":
            detail = target.title
    return {"key": dest.key, "label": dest.label, "detail": detail, "roles": sorted(dest.roles), "valid": error is None}


def web_href(value: str) -> Optional[str]:
    """Chemin du site équivalent (bouton du flux des annonces sur le site), ou None s'il n'en existe pas."""
    dest, obj_id, error = parse(value)
    if dest is None or error:
        return None
    if dest.param == "category":
        target = _target(dest, obj_id)
        return f"/search?metier={target.slug}" if target is not None else None
    if dest.param == "service":
        target = _target(dest, obj_id)
        profile = getattr(getattr(target, "handyman", None), "handyman_profile", None) if target is not None else None
        return f"/artisans/{profile.pk}" if profile is not None else None
    if dest.param == "announcement" and obj_id is not None:
        return f"{dest.web}?a={obj_id}"
    if not dest.web:
        return None
    return dest.web.replace("{id}", str(obj_id)) if "{id}" in dest.web else dest.web


def catalog() -> list:
    """Destinations proposées dans le Back-Office (annonces), dans l'ordre d'affichage, avec leurs contraintes."""
    return [{"key": d.key, "label": d.label, "group": d.group, "roles": sorted(d.roles),
             "param": d.param or None, "param_required": d.param_required}
            for d in REGISTRY if d.announce]
