"""Éligibilité d'un artisan : publication publique ET missions (source unique).

Un artisan n'est publié (recherche, cartes, fiches, chiffres publics) et n'est
éligible aux missions (réservation, matching) que si TOUT ceci est vrai :

1. compte actif ;
2. profil approuvé (`HandymanProfile.is_approved`, décision humaine) ;
3. KYC approuvé : chaque pièce de `HandymanProfile.REQUIRED_KYC_DOCS` a un
   document au statut « approved » ;
4. profil complet : mêmes champs que `HandymanProfile.profile_completion()` == 100
   (bio, spécialité, expérience, licence, CNI, assurance, photo, au moins un document).

Les versions SQL (`publishable`, `publishable_user_ids`) et Python (`is_publishable`)
décrivent la même règle ; `test_eligibility.py` vérifie qu'elles concordent.
Pour assouplir ou durcir la règle, ne modifier que ce module.
"""
from django.db.models import Exists, OuterRef, Q

from handy.models import HandymanDocument, HandymanProfile, TimeOff

# Interrupteur de COMPATIBILITÉ réservé aux suites de tests antérieures à la règle (elles
# fabriquent des artisans « approuvés » sans KYC ni profil complet) : le conftest.py racine
# le passe à False hors de test_eligibility.py. Toujours True en exécution réelle.
STRICT = True


def _filled(field: str) -> Q:
    """Champ texte/fichier renseigné (ni NULL ni chaîne vide)."""
    return Q(**{f"{field}__isnull": False}) & ~Q(**{field: ""})


def _profile_conditions() -> tuple:
    """(Q, *Exists) à passer à `.filter(...)` sur un queryset de HandymanProfile."""
    q = Q(is_approved=True, user__is_active=True)
    if not STRICT:
        return (q,)
    q &= Q(experience_years__gt=0)
    for field in ("bio", "license_number", "cni_number", "insurance_info", "photo"):
        q &= _filled(field)

    has_skill = HandymanProfile.skills.through.objects.filter(handymanprofile_id=OuterRef("pk"))
    has_document = HandymanDocument.objects.filter(handyman_id=OuterRef("pk"))
    kyc = [
        Exists(HandymanDocument.objects.filter(
            handyman_id=OuterRef("pk"), document_type=doc_type, status="approved"))
        for doc_type in sorted(HandymanProfile.REQUIRED_KYC_DOCS)
    ]
    return (q, Exists(has_skill), Exists(has_document), *kyc)


def publishable(profiles=None):
    """Profils publiables / éligibles aux missions."""
    qs = HandymanProfile.objects.all() if profiles is None else profiles
    return qs.filter(*_profile_conditions())


def publishable_user_ids():
    """Sous-requête des `user_id` éligibles (pour filtrer Service, Booking…)."""
    return publishable().values("user_id")


def is_publishable(profile) -> bool:
    """Même règle que `publishable()`, pour un objet déjà chargé."""
    if profile is None or not profile.is_approved or not profile.user.is_active:
        return False
    if not STRICT:
        return True
    return bool(profile.has_required_kyc() and profile.is_fully_completed)


def is_user_publishable(user) -> bool:
    profile = getattr(user, "handyman_profile", None) if user is not None else None
    return is_publishable(profile)


def restrict_public_services(qs):
    """Catalogue public : services actifs d'artisans éligibles. (Mode STRICT=False : legacy,
    aucune restriction — suites de tests antérieures uniquement.)"""
    if not STRICT:
        return qs
    return qs.filter(is_active=True, handyman_id__in=publishable_user_ids())


def can_receive_missions(user) -> bool:
    """L'artisan peut-il recevoir une réservation ? (STRICT=False : legacy, toujours oui.)"""
    return True if not STRICT else is_user_publishable(user)


def published_services(qs, user=None):
    """Services visibles par `user` : publiés (actifs, artisan éligible), plus les siens
    pour leur propriétaire ; le staff voit tout."""
    if user is not None and getattr(user, "is_authenticated", False) and user.is_staff:
        return qs
    visible = Q(is_active=True, handyman_id__in=publishable_user_ids())
    if user is not None and getattr(user, "is_authenticated", False):
        visible |= Q(handyman_id=user.pk)
    return qs.filter(visible)


def not_on_timeoff(now):
    """Condition `~Exists` : l'artisan (profil lié via `handyman__handyman_profile`) n'est
    pas en congé/absence à l'instant `now`. À utiliser avec `Service.objects.filter(...)`."""
    return ~Exists(TimeOff.objects.filter(
        handyman_id=OuterRef("handyman__handyman_profile__pk"), start__lte=now, end__gte=now))
