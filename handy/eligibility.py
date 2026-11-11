"""Éligibilité d’un professionnel : TROIS niveaux distincts (source unique).

1. PUBLICATION (`publishable`, copie `HandymanProfile.published`) — le profil et ses offres actives sont visibles (catalogue,
   recherche, annuaire, chiffres publics) dès que : compte actif, téléphone confirmé par code, profil non suspendu, au moins un
   métier, une commune, et l'expérience minimale des métiers exercés (`ServiceCategory.min_experience_years`, 0 = débutants
   acceptés ; la déclaration n'est jamais modifiée). AUCUNE pièce d'identité n'est exigée : le profil est affiché « Non vérifié »
   et ne peut recevoir AUCUNE commande. Présentation, photo et expérience sont facultatives (complétables plus tard).
2. COMMANDES (`orderable`, copie `orders_enabled`) — réservation, Tratra Flash, missions, contrats, Tratra ID : publication
   + chaque pièce de `HandymanProfile.REQUIRED_KYC_DOCS` approuvée par l'équipe + commandes activées (`is_approved` : activées
   automatiquement à l'approbation de la pièce, ou par l'équipe — recours manuel) + vérification faciale satisfaisante si un
   métier exercé est sensible (`ServiceCategory.face_required`) ou si la politique générale l'exige (`KYC_BIOMETRIC_REQUIRED`).
3. BADGE « Vérifié » (`is_verified`, copie `verification`) — commandes autorisées ET vérification faciale satisfaisante
   (liveness + correspondance avec la pièce, ou procédure alternative approuvée par un humain). Niveau affiché :
   NON_VERIFIE → IDENTITE_VERIFIEE (pièce approuvée) → VERIFIE. Un profil non vérifié n'est jamais présenté comme certifié.

La suspension (`HandymanProfile.suspended`, décision de l'équipe) retire les trois niveaux à l'instant.
Les versions SQL (`*_rule`) et Python (`is_*`) décrivent la même règle ; `test_eligibility.py` vérifie qu'elles concordent.
Pour assouplir ou durcir une règle, ne modifier que ce module.
"""
from django.conf import settings
from django.db.models import Exists, OuterRef, Q

from handy.models import HandymanDocument, HandymanProfile, Service, ServiceCategory, TimeOff

NON_VERIFIE, IDENTITE_VERIFIEE, VERIFIE = "NON_VERIFIE", "IDENTITE_VERIFIEE", "VERIFIE"
VERIFICATION_LABELS = dict(HandymanProfile.VERIFICATION_LEVELS)

# (clé, libellé, aide, exigé pour publier) — l’ordre est celui de la liste affichée à l’utilisateur.
CHECKLIST = [
    ("skills", "Métier", "Choisissez au moins un métier que vous exercez.", True),
    ("zone", "Zone d’intervention", "Renseignez votre commune.", True),
    ("experience", "Expérience", "Indiquez votre expérience (débutant accepté).", False),
    ("bio", "Présentation", "Décrivez votre activité en quelques lignes : les clients comparent les profils.", False),
    ("photo", "Photo de profil", "Ajoutez une photo : les clients choisissent des visages.", False),
    ("kyc", "Pièce d’identité vérifiée", "Déposez votre pièce d’identité ; l’équipe Tratra la vérifie. Elle active vos commandes.", False),
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


def _flagged(prefix: str) -> Q:
    """Le métier (catégorie, son parent ou son grand-parent) est sensible : vérification faciale exigée avant toute commande."""
    return (Q(**{f"{prefix}face_required": True}) | Q(**{f"{prefix}parent__face_required": True})
            | Q(**{f"{prefix}parent__parent__face_required": True}))


def _skill_links():
    return HandymanProfile.skills.through.objects.filter(handymanprofile_id=OuterRef("pk"))


def _active_offers():
    return Service.objects.filter(handyman_id=OuterRef("user_id"), is_active=True)


def _publication_conditions() -> tuple:
    """(Q, *Exists) de la PUBLICATION, à passer à `.filter(...)` sur un queryset de HandymanProfile."""
    # Téléphone confirmé : contrôle anti-spam de la publication. Les profils déjà activés par l'équipe avant cette règle restent publiés.
    q = Q(user__is_active=True, suspended=False) & (Q(user__is_verified=True) | Q(is_approved=True)) & _filled("commune")
    years = OuterRef("experience_years")
    return (q, Exists(_skill_links()), ~Exists(_skill_links().filter(_above("servicecategory__", years))),
            ~Exists(_active_offers().filter(_above("category__", years))))


def _kyc_conditions() -> list:
    return [Exists(HandymanDocument.objects.filter(handyman_id=OuterRef("pk"), document_type=doc_type, status="approved"))
            for doc_type in sorted(HandymanProfile.REQUIRED_KYC_DOCS)]


def _face_ok():
    from biometrics.models import BiometricVerification

    return Exists(BiometricVerification.objects.filter(profile_id=OuterRef("pk"), status__in=BiometricVerification.SATISFIED))


def face_required_everywhere() -> bool:
    """Politique générale : la vérification faciale est exigée avant toute commande, quel que soit le métier."""
    return bool(getattr(settings, "KYC_BIOMETRIC_REQUIRED", False))


def _orders_conditions() -> tuple:
    """Conditions des COMMANDES : publication + commandes activées + pièce approuvée + vérification faciale selon la politique."""
    if face_required_everywhere():
        face = Q(_face_ok())
    else:
        face = (Q(~Exists(_skill_links().filter(_flagged("servicecategory__")))) & Q(~Exists(_active_offers().filter(_flagged("category__"))))) | Q(_face_ok())
    return (*_publication_conditions(), Q(is_approved=True), *_kyc_conditions(), face)


def _categories(profile):
    """Métiers exercés : spécialités + catégories des offres actives (avec leurs parents)."""
    ids = set(profile.skills.values_list("pk", flat=True))
    ids |= set(Service.objects.filter(handyman_id=profile.user_id, is_active=True).values_list("category_id", flat=True))
    return ServiceCategory.objects.filter(pk__in=ids).select_related("parent__parent")


def _lineage(category):
    node, depth = category, 0
    while node is not None and depth < 3:
        yield node
        node, depth = node.parent, depth + 1


def experience_minimum(profile) -> dict:
    """Expérience exigée par les métiers exercés (spécialités + offres actives) : {"years": n, "trade": nom du métier le plus exigeant}."""
    best = {"years": 0, "trade": ""}
    for category in _categories(profile):
        for node in _lineage(category):
            if node.min_experience_years > best["years"]:
                best = {"years": node.min_experience_years, "trade": node.name}
    return best


def meets_experience_minimum(profile) -> bool:
    return (profile.experience_years or 0) >= experience_minimum(profile)["years"]


def sensitive_trade(profile) -> str:
    """Nom du premier métier sensible exercé (vérification faciale exigée avant toute commande), ou chaîne vide."""
    for category in _categories(profile):
        for node in _lineage(category):
            if node.face_required:
                return node.name
    return ""


def face_required(profile) -> bool:
    """La vérification faciale est-elle exigée AVANT toute commande pour ce professionnel (politique générale ou métier sensible) ?"""
    return face_required_everywhere() or bool(sensitive_trade(profile))


def face_satisfied(profile) -> bool:
    from biometrics.models import BiometricVerification

    return BiometricVerification.objects.filter(profile_id=profile.pk, status__in=BiometricVerification.SATISFIED).exists()


def face_state(profile) -> dict:
    """État de la vérification faciale pour l'affichage : {enabled, required, satisfied, status, state}.
    `state` : done | pending | retry | todo | unavailable (non proposée sur cette plateforme)."""
    from biometrics import services as bio
    from biometrics.models import BiometricVerification as V

    ver = V.objects.filter(profile_id=profile.pk).first()
    status = ver.status if ver else V.NOT_STARTED
    satisfied = bool(ver and ver.satisfied)
    if satisfied:
        state = "done"
    elif status == V.PENDING_REVIEW:
        state = "pending"
    elif not bio.enabled():
        state = "unavailable"
    elif status in (V.NOT_STARTED, V.IN_PROGRESS):
        state = "todo"
    else:
        state = "retry"
    return {"enabled": bio.enabled(), "required": face_required(profile), "satisfied": satisfied, "status": status, "state": state}


def profile_checklist(profile) -> list:
    """Liste de contrôle du dossier : [{key, label, hint, done, required}] — `required` = exigé pour PUBLIER (mêmes règles que le SQL)."""
    done = {
        "bio": bool((profile.bio or "").strip()),
        "skills": profile.skills.exists(),
        "experience": experience_declared(profile),
        "zone": bool((profile.commune or "").strip()),
        "photo": bool(profile.photo),
        "kyc": profile.has_required_kyc(),
    }
    return [{"key": k, "label": label, "hint": hint, "done": done[k], "required": required} for k, label, hint, required in CHECKLIST]


PROFILE_KEYS = ("skills", "zone", "experience", "bio", "photo")
# Action corrective proposée par les clients (web, application) pour chaque blocage : code stable → libellé du bouton.
ACTIONS = {"edit_profile": "Compléter mon profil", "verify_identity": "Activer mes commandes", "verify_face": "Obtenir le badge Vérifié",
           "verify_phone": "Confirmer mon téléphone", "add_service": "Publier un service", "manage_services": "Gérer mes offres",
           "contact_support": "Contacter le support"}
BENEFITS = {
    "publication": "Votre service est visible par les clients, avec la mention « Non vérifié ». Aucune commande tant que votre identité n’est pas vérifiée.",
    "identity": "Active vos commandes : réservations, missions Tratra Flash et contrats.",
    "face": "Attribue le badge « Vérifié », affiché sur votre profil et vos offres.",
}


def _action(code, label=None):
    """Action corrective. La vérification faciale s'ouvre par le parcours d'identité (`verify_identity`, étape `face`) : les
    applications déjà installées connaissent ce code, aucun bouton sans effet."""
    if not code:
        return None
    if code == "verify_face":
        return {"code": "verify_identity", "label": label or ACTIONS[code], "step": "face"}
    return {"code": code, "label": label or ACTIONS[code]}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n > 1 else ''}"


def _publication_blockers(profile, items) -> list:
    out = []
    if not profile.user.is_active:
        out.append({"code": "account_inactive", "label": "Compte désactivé", "hint": "Contactez le support Tratra.", "action": _action("contact_support")})
    if profile.suspended:
        out.append({"code": "suspended", "label": "Profil suspendu par l’équipe Tratra",
                    "hint": "Votre profil n’est plus visible et ne reçoit plus de commandes. Contactez le support pour connaître le motif "
                            "et demander un nouvel examen.", "action": _action("contact_support")})
    if not (profile.user.is_verified or profile.is_approved):
        out.append({"code": "phone_unverified", "label": "Numéro de téléphone non confirmé",
                    "hint": "Confirmez votre numéro avec le code reçu par SMS pour publier votre service.", "action": _action("verify_phone")})
    missing = [i for i in items if i["required"] and not i["done"]]
    if missing:
        out.append({"code": "profile_incomplete", "label": "À renseigner pour publier : " + ", ".join(i["label"].lower() for i in missing),
                    "hint": missing[0]["hint"], "action": _action("edit_profile")})
    minimum = experience_minimum(profile)
    if (profile.experience_years or 0) < minimum["years"]:
        n = minimum["years"]
        declared = (profile.experience_label or "").strip() or f"{profile.experience_years or 0} an{'s' if (profile.experience_years or 0) > 1 else ''}"
        out.append({"code": "experience_minimum",
                    "label": f"Expérience minimale non atteinte : {minimum['trade']} demande {n} an{'s' if n > 1 else ''}",
                    "hint": f"Votre déclaration (« {declared} ») est conservée telle quelle. Ce métier pourra être publié quand votre "
                            "expérience atteindra le minimum ; vous pouvez aussi le retirer de vos spécialités et de vos offres.",
                    "action": _action("edit_profile")})
    return out


def _orders_blockers(profile, kyc, face) -> list:
    out = []
    kyc_blockers = {
        "draft": ("Identité non vérifiée", "Faites vérifier votre pièce d’identité pour recevoir des commandes : quelques minutes suffisent.",
                  _action("verify_identity")),
        "pending": ("Pièce d’identité en cours de revue", "L’équipe Tratra examine votre pièce : aucune action n’est nécessaire. "
                                                          "Vos commandes seront activées dès son approbation.", None),
        "rejected": ("Nouvelle pièce d’identité demandée", kyc["reason"] or "Reprenez des photos nettes et complètes de votre pièce.",
                     _action("verify_identity", "Reprendre ma vérification")),
    }
    if kyc["status"] in kyc_blockers:
        label, hint, action = kyc_blockers[kyc["status"]]
        out.append({"code": f"kyc_{kyc['status']}", "label": label, "hint": hint, "action": action})
    elif not profile.is_approved and not profile.suspended:
        out.append({"code": "approval_pending", "label": "Activation des commandes par l’équipe Tratra en attente",
                    "hint": "Votre pièce est approuvée ; l’équipe termine un contrôle avant d’activer vos commandes. Aucune action n’est nécessaire.",
                    "action": None})
    if face["required"] and not face["satisfied"]:
        trade = sensitive_trade(profile)
        why = f"« {trade} » est un métier sensible" if trade else "Tratra demande cette vérification à tous les professionnels"
        if face["state"] == "pending":
            label, hint, action = "Vérification faciale en cours de revue", "L’équipe Tratra examine votre vérification : aucune action n’est nécessaire.", None
        elif face["state"] == "unavailable":
            label, hint, action = ("Vérification faciale demandée", f"{why} : la vérification faciale se fait avec l’équipe Tratra. Contactez le support.",
                                   _action("contact_support"))
        else:
            label, hint, action = ("Vérification faciale demandée", f"{why} : comparez votre visage à votre pièce d’identité pour recevoir des commandes.",
                                   _action("verify_face", "Faire la vérification faciale"))
        out.append({"code": "face_required", "label": label, "hint": hint, "action": action})
    return out


def _stages(profile, kyc, face, published, orders, level, active) -> list:
    """Les trois étapes affichées au professionnel, avec l'état réel et le bénéfice de chacune."""
    if published and active:
        pub = ("done", "Publié")
    elif published:
        pub = ("todo", "Profil visible, aucun service actif")
    else:
        pub = ("todo", "Non publié")
    identity = {"draft": ("todo", "À faire"), "pending": ("pending", "En cours de revue"), "rejected": ("retry", "Nouvelle pièce demandée")}.get(kyc["status"])
    if identity is None:
        identity = ("done", "Identité vérifiée") if profile.is_approved and not profile.suspended else ("pending", "Activation par l’équipe en attente")
    if kyc["status"] == "draft" and face["state"] in ("todo", "retry"):
        face_stage = ("locked", "Après la pièce d’identité")
    else:
        face_stage = {"done": ("done", "Validée"), "pending": ("pending", "En cours de revue"), "retry": ("retry", "À reprendre"),
                      "todo": ("todo", "À faire"), "unavailable": ("unavailable", "Pas encore proposée")}[face["state"]]
    face_benefit = BENEFITS["face"] + (" Obligatoire pour recevoir des commandes dans votre métier." if face["required"] else "")
    if level == VERIFIE:
        pub_benefit = "Votre service est visible par les clients, avec le badge « Vérifié »."
    elif level == IDENTITE_VERIFIEE:
        pub_benefit = "Votre service est visible par les clients, avec la mention « Identité vérifiée »."
    else:
        pub_benefit = BENEFITS["publication"]
    return [
        {"key": "publication", "label": "Service publié", "state": pub[0], "status": pub[1], "benefit": pub_benefit},
        {"key": "identity", "label": "Pièce d’identité", "state": identity[0], "status": identity[1], "benefit": BENEFITS["identity"]},
        {"key": "face", "label": "Vérification faciale", "state": face_stage[0], "status": face_stage[1], "benefit": face_benefit,
         "required": face["required"]},
    ]


def eligibility_summary(profile) -> dict:
    """L’état complet de l’espace professionnel : trois niveaux DISTINCTS, leurs blocages réels et l’action corrective de chacun.

    - `publication` : le profil et ses offres actives sont visibles (`is_publishable`) ;
    - `orders` : le professionnel peut recevoir des commandes (`is_orderable`) ;
    - `verification` : niveau affiché (Non vérifié → Identité vérifiée → Vérifié) et état de la vérification faciale ;
    - `profile`, `kyc`, `offers`, `stages`, `next_action` : détail et prochaine action utile.

    `publication.authorized`, `orders.authorized` et `verification.level` sont TOUJOURS égaux aux règles du module (vérifié par les tests).
    Les clés `approval` et `profile.complete` sont conservées pour les anciennes versions de l’application."""
    from handy.kyc_flow import kyc_status

    items = [i for i in profile_checklist(profile) if i["key"] in PROFILE_KEYS]
    kyc = kyc_status(profile)
    face = face_state(profile)
    published, orders, level = is_publishable(profile), is_orderable(profile), verification_level(profile)
    pub_blockers = [] if published else _publication_blockers(profile, items)
    orders_blockers = [] if orders else _orders_blockers(profile, kyc, face)
    if not published and not orders:
        orders_blockers = [{"code": "not_published", "label": "Service non publié", "hint": "Publiez d’abord votre service.",
                            "action": next((b["action"] for b in pub_blockers if b["action"]), None)}] + orders_blockers
    services = Service.objects.filter(handyman=profile.user)
    total, active = services.count(), services.filter(is_active=True).count()
    visible = active if published else 0
    if total == 0:
        offers_label, offers_action = "Aucune offre créée", _action("add_service")
    elif active == 0:
        offers_label, offers_action = "Aucune offre active", _action("manage_services")
    elif not published:
        offers_label, offers_action = f"{_plural(active, 'offre')} en attente de publication", None
    else:
        offers_label = f"{_plural(visible, 'offre')} publiée{'s' if visible > 1 else ''}" + ("" if orders else " — commandes non activées")
        offers_action = None
    if not published:
        next_action = next((b["action"] for b in pub_blockers if b["action"]), None)
    elif total == 0:
        next_action = _action("add_service")
    elif active == 0:
        next_action = _action("manage_services")
    elif not orders:
        next_action = next((b["action"] for b in orders_blockers if b["action"]), None)
    elif level != VERIFIE and face["state"] in ("todo", "retry"):
        next_action = _action("verify_face")
    else:
        next_action = None
    done = sum(1 for i in items if i["done"])
    orders_label = "Commandes activées" if orders else ("Commandes non activées" if not profile.suspended else "Commandes suspendues")
    return {
        "profile": {"complete": done == len(items), "ready": all(i["done"] for i in items if i["required"]), "done": done,
                    "total": len(items), "items": items},
        "kyc": {**kyc, "approved": kyc["status"] == "approved"},
        "approval": {"approved": bool(profile.is_approved), "label": orders_label},
        "suspended": bool(profile.suspended),
        "publication": {"authorized": published, "label": "Profil publié" if published else "Profil non publié", "blockers": pub_blockers},
        "orders": {"authorized": orders, "label": orders_label, "blockers": orders_blockers, "face_required": face["required"]},
        "verification": {"level": level, "label": VERIFICATION_LABELS[level], "badge": level == VERIFIE, "face": face},
        "stages": _stages(profile, kyc, face, published, orders, level, active),
        "offers": {"total": total, "active": active, "published": visible, "inactive": total - active, "label": offers_label,
                   "action": offers_action, "accepting_orders": orders},
        "next_action": next_action,
    }


# ═══ Règles SQL complètes et copies calculées ═════════════════════════════════════════════════════════════════════════════

def _all(profiles):
    return HandymanProfile.objects.all() if profiles is None else profiles


def publishable_rule(profiles=None):
    """La RÈGLE de publication en SQL (source de vérité, coûteuse : spécialités, seuils d'expérience des métiers). Sert à calculer
    `HandymanProfile.published` (`refresh_published`) et aux contrôles ; les lectures courantes passent par `publishable()`."""
    return _all(profiles).filter(*_publication_conditions())


def orderable_rule(profiles=None):
    """La RÈGLE des commandes en SQL (source de vérité) : sert à calculer `HandymanProfile.orders_enabled`."""
    return _all(profiles).filter(*_orders_conditions())


def verified_rule(profiles=None):
    """Badge « Vérifié » : commandes autorisées ET vérification faciale satisfaisante."""
    return orderable_rule(profiles).filter(_face_ok())


def identity_rule(profiles=None):
    """Niveau « Identité vérifiée » : pièces exigées approuvées, compte actif, profil non suspendu."""
    return _all(profiles).filter(Q(user__is_active=True, suspended=False), *_kyc_conditions())


def publishable(profiles=None):
    """Profils PUBLIÉS (visibles) — lecture RAPIDE et indexée : copie calculée de la règle (`published`), plus les deux conditions
    qui doivent retirer un professionnel À L'INSTANT, même si un recalcul avait été manqué (compte désactivé, suspension).
    Ne dit RIEN du droit de recevoir des commandes : voir `orderable()`."""
    return _all(profiles).filter(published=True, suspended=False, user__is_active=True)


def orderable(profiles=None):
    """Profils qui peuvent recevoir des COMMANDES — lecture rapide (copie `orders_enabled`) plus les conditions à effet immédiat.
    Une réservation, une attribution ou une acceptation revérifie toujours la règle complète (`is_orderable`)."""
    return _all(profiles).filter(orders_enabled=True, published=True, is_approved=True, suspended=False, user__is_active=True)


def _scope(profiles):
    if profiles is None:
        return HandymanProfile.objects.all()
    if hasattr(profiles, "values"):
        return HandymanProfile.objects.filter(pk__in=profiles.values("pk"))
    ids = [pk for pk in profiles if pk]
    return HandymanProfile.objects.filter(pk__in=ids) if ids else None


def refresh_published(profiles=None) -> int:
    """Recalcule les TROIS copies (`published`, `orders_enabled`, `verification`) à partir des règles pour les profils donnés
    (queryset, liste d'identifiants, ou tous) ; uniquement des UPDATE, sans signal. Renvoie le nombre de modifications."""
    scope = _scope(profiles)
    if scope is None:
        return 0
    changed = 0
    for field, rule in (("published", publishable_rule), ("orders_enabled", orderable_rule)):
        eligible = rule(scope).values("pk")
        changed += scope.filter(**{field: False}, pk__in=eligible).update(**{field: True})
        changed += scope.filter(**{field: True}).exclude(pk__in=eligible).update(**{field: False})
    for level, rows in _levels(scope):
        changed += rows.exclude(verification=level).update(verification=level)
    return changed


def _levels(scope):
    verified, identity = verified_rule(scope).values("pk"), identity_rule(scope).values("pk")
    return ((VERIFIE, scope.filter(pk__in=verified)),
            (IDENTITE_VERIFIEE, scope.filter(pk__in=identity).exclude(pk__in=verified)),
            (NON_VERIFIE, scope.exclude(pk__in=identity).exclude(pk__in=verified)))


def published_drift() -> int:
    """Profils dont une copie (`published`, `orders_enabled`, `verification`) diffère de la règle (0 attendu ; sinon, un chemin de
    modification n'a pas recalculé)."""
    scope, ids = HandymanProfile.objects.all(), set()                           # un profil compte une fois, même si deux copies divergent
    for field, rule in (("published", publishable_rule), ("orders_enabled", orderable_rule)):
        eligible = rule().values("pk")
        ids.update(scope.filter(**{field: False}, pk__in=eligible).values_list("pk", flat=True))
        ids.update(scope.filter(**{field: True}).exclude(pk__in=eligible).values_list("pk", flat=True))
    for level, rows in _levels(scope):
        ids.update(rows.exclude(verification=level).values_list("pk", flat=True))
    return len(ids)


def publishable_user_ids():
    """Sous-requête des `user_id` PUBLIÉS (pour filtrer Service, annuaire…)."""
    return publishable().values("user_id")


def orderable_user_ids():
    """Sous-requête des `user_id` qui peuvent recevoir des commandes (réservations, Flash, missions…)."""
    return orderable().values("user_id")


# ═══ Mêmes règles, pour un objet déjà chargé ══════════════════════════════════════════════════════════════════════════════

def is_publishable(profile) -> bool:
    """Même règle que `publishable_rule()` : le profil est-il visible ?"""
    if profile is None or profile.suspended or not profile.user.is_active:
        return False
    if not (profile.user.is_verified or profile.is_approved):
        return False
    return bool((profile.commune or "").strip()) and profile.skills.exists() and meets_experience_minimum(profile)


def is_orderable(profile) -> bool:
    """Même règle que `orderable_rule()` : le professionnel peut-il recevoir une commande ?"""
    if not is_publishable(profile) or not profile.is_approved or not profile.has_required_kyc():
        return False
    return not face_required(profile) or face_satisfied(profile)


def is_verified(profile) -> bool:
    """Badge « Vérifié » : commandes autorisées ET vérification faciale satisfaisante."""
    return is_orderable(profile) and face_satisfied(profile)


def verification_level(profile) -> str:
    """Niveau affiché : NON_VERIFIE, IDENTITE_VERIFIEE ou VERIFIE (même règle que la copie `verification`)."""
    if profile is None:
        return NON_VERIFIE
    if is_verified(profile):
        return VERIFIE
    if profile.user.is_active and not profile.suspended and profile.has_required_kyc():
        return IDENTITE_VERIFIEE
    return NON_VERIFIE


def verification_payload(level: str) -> dict:
    """Niveau de vérification tel qu'exposé au public : jamais « Vérifié » sans la vérification faciale."""
    level = level if level in VERIFICATION_LABELS else NON_VERIFIE
    return {"level": level, "label": VERIFICATION_LABELS[level], "badge": level == VERIFIE}


def _profile_of(user):
    return getattr(user, "handyman_profile", None) if user is not None else None


def is_user_publishable(user) -> bool:
    return is_publishable(_profile_of(user))


def is_user_orderable(user) -> bool:
    return is_orderable(_profile_of(user))


def can_receive_missions(user) -> bool:
    """Le professionnel peut-il recevoir une réservation, une mission ou un contrat ? (règle des COMMANDES, pas de la publication)"""
    return is_user_orderable(user)


ORDERS_REFUSED = "Ce professionnel n’a pas encore fait vérifier son identité : il ne peut pas recevoir de commande pour le moment."


def restrict_public_services(qs):
    """Catalogue public : services actifs de professionnels PUBLIÉS (vérifiés ou non — le niveau est affiché sur chaque offre)."""
    return qs.filter(is_active=True, handyman_id__in=publishable_user_ids())


def published_services(qs, user=None):
    """Services visibles par `user` : publiés (actifs, professionnel publié), plus les siens
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
