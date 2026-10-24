"""Éligibilité d’un artisan : publication publique ET missions (source unique).

Un artisan n'est publié (catalogue, recherche de proximité, alternatives, chiffres publics)
et n'est éligible aux missions (réservation, matching) que si TOUT ceci est vrai :

1. compte actif ;
2. profil complet — ce que l'artisan peut réellement renseigner : présentation, au moins une
   spécialité, expérience DÉCLARÉE (un nombre d'années, ou une tranche telle que « Moins d’un an »
   choisie dans l'inscription accompagnée), zone d'intervention (commune), photo ;
2 bis. expérience minimale des métiers exercés (spécialités et offres actives) : réglée par métier
   dans l'administration (`ServiceCategory.min_experience_years`, 0 = débutants acceptés). La
   déclaration de l'artisan n'est jamais modifiée pour passer ce seuil ;
3. KYC approuvé : chaque pièce de `HandymanProfile.REQUIRED_KYC_DOCS` (pièce d'identité) a un
   document au statut « approved » ;
4. profil approuvé par l'équipe Tratra (`HandymanProfile.is_approved`, décision humaine).

(Les numéros CNI/licence/assurance ne sont plus exigés : ils sont en lecture seule dans l'API,
la pièce d'identité validée fait foi.) La même liste alimente la progression affichée dans le
tableau de bord (`profile_checklist`) : une seule source de vérité. Les versions SQL
(`publishable`, `publishable_user_ids`) et Python (`is_publishable`) décrivent la même règle ;
`test_eligibility.py` vérifie qu'elles concordent. Pour assouplir ou durcir la règle, ne modifier
que ce module.
"""
from django.db.models import Exists, OuterRef, Q

from handy.models import HandymanDocument, HandymanProfile, Service, ServiceCategory, TimeOff

# (clé, libellé, aide) — l’ordre est celui de la liste de contrôle affichée à l’utilisateur.
CHECKLIST = [
    ("bio", "Présentation", "Décrivez votre activité et votre expérience en quelques lignes."),
    ("skills", "Spécialités", "Choisissez au moins un métier que vous exercez."),
    ("experience", "Expérience", "Indiquez votre expérience (débutant accepté)."),
    ("zone", "Zone d’intervention", "Renseignez votre commune."),
    ("photo", "Photo de profil", "Ajoutez une photo : les clients choisissent des visages."),
    ("kyc", "Pièce d’identité vérifiée", "Déposez votre pièce d’identité ; l’équipe Tratra la vérifie."),
    ("approval", "Validation par l’équipe Tratra", "Dernière étape, après vérification de votre dossier."),
]


def _filled(field: str) -> Q:
    """Champ texte/fichier renseigné (ni NULL ni chaîne vide, ni espaces seuls)."""
    return Q(**{f"{field}__isnull": False}) & ~Q(**{field: ""})


def experience_declared(profile) -> bool:
    """Expérience renseignée : un nombre d'années (> 0) ou une tranche déclarée (« Moins d’un an »)."""
    return (profile.experience_years or 0) > 0 or bool((profile.experience_label or "").strip())


def _above(prefix: str, years) -> Q:
    """Le métier (catégorie, son parent ou son grand-parent) exige plus d'expérience que `years`."""
    return (Q(**{f"{prefix}min_experience_years__gt": years}) | Q(**{f"{prefix}parent__min_experience_years__gt": years})
            | Q(**{f"{prefix}parent__parent__min_experience_years__gt": years}))


def _profile_conditions() -> tuple:
    """(Q, *Exists) à passer à `.filter(...)` sur un queryset de HandymanProfile."""
    q = Q(is_approved=True, user__is_active=True) & (Q(experience_years__gt=0) | ~Q(experience_label=""))
    for field in ("bio", "commune", "photo"):
        q &= _filled(field)

    has_skill = HandymanProfile.skills.through.objects.filter(handymanprofile_id=OuterRef("pk"))
    kyc = [
        Exists(HandymanDocument.objects.filter(
            handyman_id=OuterRef("pk"), document_type=doc_type, status="approved"))
        for doc_type in sorted(HandymanProfile.REQUIRED_KYC_DOCS)
    ]
    years = OuterRef("experience_years")
    skill_above = HandymanProfile.skills.through.objects.filter(handymanprofile_id=OuterRef("pk")).filter(_above("servicecategory__", years))
    offer_above = Service.objects.filter(handyman_id=OuterRef("user_id"), is_active=True).filter(_above("category__", years))
    return (q, Exists(has_skill), *kyc, ~Exists(skill_above), ~Exists(offer_above))


def experience_minimum(profile) -> dict:
    """Expérience exigée par les métiers exercés (spécialités + offres actives) : {"years": n, "trade": nom du métier le plus exigeant}."""
    ids = set(profile.skills.values_list("pk", flat=True))
    ids |= set(Service.objects.filter(handyman_id=profile.user_id, is_active=True).values_list("category_id", flat=True))
    best = {"years": 0, "trade": ""}
    for category in ServiceCategory.objects.filter(pk__in=ids).select_related("parent__parent"):
        node, depth = category, 0
        while node is not None and depth < 3:
            if node.min_experience_years > best["years"]:
                best = {"years": node.min_experience_years, "trade": node.name}
            node, depth = node.parent, depth + 1
    return best


def meets_experience_minimum(profile) -> bool:
    return (profile.experience_years or 0) >= experience_minimum(profile)["years"]


def profile_checklist(profile) -> list:
    """Liste de contrôle du dossier artisan : [{key, label, hint, done}] — mêmes règles que le SQL."""
    done = {
        "bio": bool((profile.bio or "").strip()),
        "skills": profile.skills.exists(),
        "experience": experience_declared(profile),
        "zone": bool((profile.commune or "").strip()),
        "photo": bool(profile.photo),
        "kyc": profile.has_required_kyc(),
        "approval": bool(profile.is_approved),
    }
    return [{"key": k, "label": label, "hint": hint, "done": done[k]} for k, label, hint in CHECKLIST]


PROFILE_KEYS = ("bio", "skills", "experience", "zone", "photo")
# Action corrective proposée par les clients (web, application) pour chaque blocage : code stable → libellé du bouton.
ACTIONS = {"edit_profile": "Compléter mon profil", "verify_identity": "Vérifier mon identité", "add_service": "Ajouter une offre",
           "manage_services": "Gérer mes offres", "contact_support": "Contacter le support"}


def _action(code):
    return {"code": code, "label": ACTIONS[code]} if code else None


def eligibility_summary(profile) -> dict:
    """Les QUATRE notions distinctes de l’espace professionnel, avec les blocages réels et l’action corrective de chacun :

    - profil complet (5 éléments que l'artisan renseigne lui-même) ;
    - identité (KYC : pièce d'identité revue par l'équipe) ;
    - autorisation de publication = `is_publishable` (profil complet + identité vérifiée + validation finale de l'équipe + compte actif) ;
    - offres publiées (services actifs, visibles seulement si la publication est autorisée).

    `publication.authorized` est TOUJOURS égal à `is_publishable(profile)` (vérifié par les tests)."""
    from handy.kyc_flow import kyc_status

    checklist = profile_checklist(profile)
    items = [i for i in checklist if i["key"] in PROFILE_KEYS]
    missing = [i for i in items if not i["done"]]
    kyc = kyc_status(profile)
    authorized = is_publishable(profile)
    blockers = []
    if not profile.user.is_active:
        blockers.append({"code": "account_inactive", "label": "Compte désactivé", "hint": "Contactez le support Tratra.", "action": _action("contact_support")})
    if missing:
        blockers.append({"code": "profile_incomplete", "label": "Profil incomplet : " + ", ".join(i["label"].lower() for i in missing),
                         "hint": missing[0]["hint"], "action": _action("edit_profile")})
    kyc_blockers = {
        "draft": ("Identité non vérifiée", "Faites vérifier votre pièce d’identité : quelques minutes suffisent."),
        "pending": ("Pièce d’identité en cours de revue", "L’équipe Tratra examine votre pièce : aucune action n’est nécessaire."),
        "rejected": ("Nouvelle pièce d’identité demandée", kyc["reason"] or "Reprenez des photos nettes et complètes de votre pièce."),
    }
    if kyc["status"] in kyc_blockers:
        label, hint = kyc_blockers[kyc["status"]]
        blockers.append({"code": f"kyc_{kyc['status']}", "label": label, "hint": hint,
                         "action": None if kyc["status"] == "pending" else _action("verify_identity")})
    minimum = experience_minimum(profile)
    if (profile.experience_years or 0) < minimum["years"]:
        n = minimum["years"]
        declared = (profile.experience_label or "").strip() or f"{profile.experience_years or 0} an{'s' if (profile.experience_years or 0) > 1 else ''}"
        blockers.append({"code": "experience_minimum",
                         "label": f"Expérience minimale non atteinte : {minimum['trade']} demande {n} an{'s' if n > 1 else ''}",
                         "hint": f"Votre déclaration (« {declared} ») est conservée telle quelle. Ce métier pourra être publié quand votre "
                                 "expérience atteindra le minimum ; vous pouvez aussi le retirer de vos spécialités et de vos offres.",
                         "action": _action("edit_profile")})
    if not profile.is_approved and kyc["status"] == "approved":
        blockers.append({"code": "approval_pending", "label": "Validation finale de l’équipe Tratra en attente",
                         "hint": "Dernière étape, faite par l’équipe après la vérification de votre identité. Aucune action n’est nécessaire.",
                         "action": None})
    services = Service.objects.filter(handyman=profile.user)
    total, active = services.count(), services.filter(is_active=True).count()
    published = active if authorized else 0
    if total == 0:
        offers_label, offers_action = "Aucune offre créée", _action("add_service")
    elif active == 0:
        offers_label, offers_action = "Aucune offre active", _action("manage_services")
    elif not authorized:
        offers_label, offers_action = f"{active} offre{'s' if active > 1 else ''} en attente de l’autorisation de publication", None
    else:
        offers_label, offers_action = f"{published} offre{'s' if published > 1 else ''} publiée{'s' if published > 1 else ''}", None
    if authorized and total == 0:
        next_action = _action("add_service")
    elif authorized and active == 0:
        next_action = _action("manage_services")
    else:
        next_action = next((b["action"] for b in blockers if b["action"]), None)
    return {
        "profile": {"complete": not missing, "done": len(items) - len(missing), "total": len(items), "items": items},
        "kyc": {**kyc, "approved": kyc["status"] == "approved"},
        "approval": {"approved": bool(profile.is_approved),
                     "label": "Validé par l’équipe Tratra" if profile.is_approved else "Validation de l’équipe en attente"},
        "publication": {"authorized": authorized,
                        "label": "Publication autorisée" if authorized else "Publication non autorisée",
                        "blockers": [] if authorized else blockers},
        "offers": {"total": total, "active": active, "published": published, "inactive": total - active, "label": offers_label,
                   "action": offers_action},
        "next_action": next_action,
    }


def publishable_rule(profiles=None):
    """La RÈGLE complète en SQL (source de vérité, coûteuse : KYC, spécialités, seuils d'expérience des métiers). Sert à calculer
    `HandymanProfile.published` (`refresh_published`) et aux contrôles ; les lectures courantes passent par `publishable()`."""
    qs = HandymanProfile.objects.all() if profiles is None else profiles
    return qs.filter(*_profile_conditions())


def publishable(profiles=None):
    """Profils publiables / éligibles aux missions — lecture RAPIDE et indexée : copie calculée de la règle (`published`), plus les
    deux conditions qui doivent retirer un professionnel À L'INSTANT, même si un recalcul avait été manqué (compte désactivé,
    validation de l'équipe retirée). Une réservation ou une acceptation revérifie toujours la règle complète (`is_publishable`)."""
    qs = HandymanProfile.objects.all() if profiles is None else profiles
    return qs.filter(published=True, is_approved=True, user__is_active=True)


def refresh_published(profiles=None) -> int:
    """Recalcule `published` à partir de la règle pour les profils donnés (queryset, liste d'identifiants, ou tous) ; deux requêtes
    UPDATE, sans signal. Renvoie le nombre de profils dont la publication a changé."""
    if profiles is None:
        scope = HandymanProfile.objects.all()
    elif hasattr(profiles, "values"):
        scope = HandymanProfile.objects.filter(pk__in=profiles.values("pk"))
    else:
        ids = [pk for pk in profiles if pk]
        if not ids:
            return 0
        scope = HandymanProfile.objects.filter(pk__in=ids)
    eligible = publishable_rule(scope).values("pk")
    on = scope.filter(published=False, pk__in=eligible).update(published=True)
    off = scope.filter(published=True).exclude(pk__in=eligible).update(published=False)
    return on + off


def published_drift() -> int:
    """Profils dont la copie `published` diffère de la règle (0 attendu ; sinon, un chemin de modification n'a pas recalculé)."""
    eligible = publishable_rule().values("pk")
    return (HandymanProfile.objects.filter(published=False, pk__in=eligible).count()
            + HandymanProfile.objects.filter(published=True).exclude(pk__in=eligible).count())


def publishable_user_ids():
    """Sous-requête des `user_id` éligibles (pour filtrer Service, Booking…)."""
    return publishable().values("user_id")


def is_publishable(profile) -> bool:
    """Même règle que `publishable()`, pour un objet déjà chargé."""
    if profile is None or not profile.is_approved or not profile.user.is_active:
        return False
    return all(item["done"] for item in profile_checklist(profile)) and meets_experience_minimum(profile)


def is_user_publishable(user) -> bool:
    profile = getattr(user, "handyman_profile", None) if user is not None else None
    return is_publishable(profile)


def restrict_public_services(qs):
    """Catalogue public : services actifs d’artisans éligibles."""
    return qs.filter(is_active=True, handyman_id__in=publishable_user_ids())


def can_receive_missions(user) -> bool:
    """L’artisan peut-il recevoir une réservation ?"""
    return is_user_publishable(user)


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
    """Condition `~Exists` : l’artisan (profil lié via `handyman__handyman_profile`) n’est
    pas en congé/absence à l’instant `now`. À utiliser avec `Service.objects.filter(...)`."""
    return ~Exists(TimeOff.objects.filter(
        handyman_id=OuterRef("handyman__handyman_profile__pk"), start__lte=now, end__gte=now))
