"""Outils de l'assistant : fonctions Django en LECTURE SEULE, fixes et déclarées côté serveur.

 - le modèle de langage ne choisit qu'un NOM d'outil et des arguments VALIDÉS ; il n'écrit jamais de SQL, de chemin ni d'URL ;
 - chaque outil exige un droit du Back-Office, vérifié deux fois : à la liste des outils proposés au modèle ET à l'exécution
   (un modèle qui invente un nom d'outil ou appelle un outil non autorisé reçoit un refus, jamais un résultat) ;
 - l'exécution a lieu dans une transaction en lecture seule à durée limitée (`safety.read_only`) ;
 - les résultats sont nettoyés par `safety` : coordonnées masquées, aucune donnée biométrique, aucun document, aucun secret ;
 - aucune action : pas de suspension, de validation, de suppression, d'envoi ni de remboursement."""
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional, Set

from django.db.models import Count, Q
from django.utils import timezone

from backoffice import rbac
from backoffice.assistant import insights, safety
from backoffice.common import mask_phone, public_name


class ToolError(Exception):
    """Erreur d'usage d'un outil (argument invalide, ressource introuvable) : renvoyée au modèle, jamais une trace technique."""


class ToolDenied(Exception):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    label: str                      # affiché pendant l'exécution (« Consultation des réservations… ») et dans les sources
    description: str
    permission: str
    parameters: Dict
    handler: Callable[[Set[str], Dict], Dict]
    loggable: tuple = ()            # arguments textuels autorisés dans l'audit (par défaut : aucun texte libre)

    def schema(self) -> Dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


def _schema(properties: Optional[Dict] = None, required: Optional[List[str]] = None) -> Dict:
    return {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}


def _validate(schema: Dict, raw: Any) -> Dict:
    """Valide strictement les arguments : types, bornes, énumérations. Les clés inconnues sont ignorées, les valeurs invalides refusées."""
    if raw in (None, ""):
        raw = {}
    if not isinstance(raw, dict):
        raise ToolError("Arguments invalides : un objet est attendu.")
    out: Dict[str, Any] = {}
    for key, spec in schema["properties"].items():
        if key not in raw or raw[key] in (None, ""):
            continue
        value, kind = raw[key], spec.get("type")
        if kind == "integer":
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ToolError(f"« {key} » doit être un nombre entier.")
            if not spec.get("minimum", -10**12) <= value <= spec.get("maximum", 10**12):
                raise ToolError(f"« {key} » doit être compris entre {spec.get('minimum')} et {spec.get('maximum')}.")
        elif kind == "boolean":
            if isinstance(value, str):
                value = value.strip().lower() in ("true", "1", "oui")
            value = bool(value)
        else:
            value = str(value).strip().replace("\x00", "")
            if len(value) > spec.get("maxLength", 80):
                raise ToolError(f"« {key} » est trop long.")
            if spec.get("enum") and value not in spec["enum"]:
                raise ToolError(f"« {key} » doit valoir l'une des valeurs : {', '.join(spec['enum'])}.")
        out[key] = value
    for key in schema.get("required", []):
        if key not in out:
            raise ToolError(f"L'argument « {key} » est obligatoire.")
    return out


# ═══ Outils ═════════════════════════════════════════════════════════════════════════════════════════════════════════

def _platform_overview(perms: Set[str], args: Dict) -> Dict:
    from handy.models import Booking, Dispute, HandymanDocument, HandymanProfile, User

    now = timezone.now()
    d7, d30 = now - timedelta(days=7), now - timedelta(days=30)
    out: Dict[str, Any] = {"periode": "valeurs actuelles et 7/30 derniers jours", "sections_omises_faute_de_droit": []}
    if "users.view" in perms or "analytics.view" in perms:
        members = User.objects.filter(is_staff=False, deleted_at__isnull=True)
        out["membres"] = {"total": members.count(), "nouveaux_7j": members.filter(date_joined__gte=d7).count(), "nouveaux_30j": members.filter(date_joined__gte=d30).count(),
                          "artisans": HandymanProfile.objects.count(), "artisans_approuves": HandymanProfile.objects.filter(is_approved=True).count()}
    else:
        out["sections_omises_faute_de_droit"].append("membres")
    if "bookings.view" in perms or "analytics.view" in perms:
        by_status = dict(Booking.objects.values_list("status").annotate(n=Count("id")).values_list("status", "n"))
        out["reservations"] = {"total": sum(by_status.values()), "par_statut": by_status, "creees_7j": Booking.objects.filter(created_at__gte=d7).count(),
                               "terminees_30j": Booking.objects.filter(status="completed", updated_at__gte=d30).count()}
    else:
        out["sections_omises_faute_de_droit"].append("reservations")
    if "kyc.review" in perms:
        out["kyc"] = {"pieces_en_attente": HandymanDocument.objects.filter(status="pending").count()}
    else:
        out["sections_omises_faute_de_droit"].append("kyc")
    if "bookings.manage" in perms or "support.manage" in perms:
        out["litiges_ouverts"] = Dispute.objects.filter(status__in=("open", "under_review")).count()
    return out


def _kind_of(u) -> str:
    try:
        if getattr(u, "handyman_profile", None) is not None:
            return "artisan"
    except Exception:  # noqa: BLE001 - relation absente
        pass
    return "client"


def _user_row(u) -> Dict:
    return {"id": u.pk, "nom": public_name(u), "telephone": mask_phone(u.phone), "ville": u.city or None, "type": _kind_of(u), "actif": u.is_active,
            "telephone_verifie": u.is_verified, "inscrit_le": u.date_joined.date().isoformat(), "derniere_connexion": u.last_login.date().isoformat() if u.last_login else None,
            "lien": f"/backoffice/users/{u.pk}"}


def _search_users(perms: Set[str], args: Dict) -> Dict:
    from backoffice.api_people import KYC_STATES, _filter_kyc_state
    from handy.models import HandymanDocument, User
    from django.db.models import Exists, OuterRef

    qs = User.objects.filter(is_staff=False, deleted_at__isnull=True).select_related("handyman_profile")
    q = args.get("query")
    if q:
        cond = Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(username__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q)
        if q.isdigit() and len(q) <= 9:
            cond |= Q(pk=int(q))
        qs = qs.filter(cond)
    kind = args.get("type")
    if kind == "artisan":
        qs = qs.filter(handyman_profile__isnull=False)
    elif kind == "company":
        qs = qs.filter(Q(company_profile__isnull=False) | Q(business_memberships__is_active=True)).distinct()
    elif kind == "client":
        qs = qs.filter(handyman_profile__isnull=True, company_profile__isnull=True)
    if "actif" in args:
        qs = qs.filter(is_active=args["actif"])
    if args.get("kyc"):
        if "kyc.review" not in perms:
            raise ToolError("Le filtre KYC exige le droit de vérification KYC.")
        docs = HandymanDocument.objects.filter(handyman__user=OuterRef("pk"))
        qs = qs.annotate(kyc_pending=Exists(docs.filter(status="pending")), kyc_rejected=Exists(docs.filter(status="rejected")),
                         kyc_id_ok=Exists(docs.filter(document_type="id_card", status="approved")))
        qs = _filter_kyc_state(qs, args["kyc"])
    total = qs.count()
    rows = [_user_row(u) for u in qs.order_by("-date_joined", "-id")[: args.get("limit", 8)]]
    return {"total_correspondants": total, "affiches": len(rows), "membres": rows,
            "note": "Coordonnées masquées : la fiche du compte (lien) affiche les informations complètes aux rôles autorisés."}


def _get_user_summary(perms: Set[str], args: Dict) -> Dict:
    from handy.models import Booking, Dispute, HandymanDocument, User

    u = User.objects.filter(pk=args["user_id"], is_staff=False).select_related("handyman_profile").first()
    if u is None:
        raise ToolError("Aucun membre ne correspond à cet identifiant.")
    out: Dict[str, Any] = {**_user_row(u), "sections_omises_faute_de_droit": []}
    profile = getattr(u, "handyman_profile", None)
    if profile is not None:
        out["profil_artisan"] = {"approuve": profile.is_approved, "commune": profile.commune, "note_moyenne": float(profile.rating) if profile.rating else None}
    if "bookings.view" in perms:
        as_client = dict(Booking.objects.filter(client=u).values_list("status").annotate(n=Count("id")).values_list("status", "n"))
        as_artisan = dict(Booking.objects.filter(handyman=u).values_list("status").annotate(n=Count("id")).values_list("status", "n"))
        disputes = dict(Dispute.objects.filter(Q(booking__client=u) | Q(booking__handyman=u)).values_list("status").annotate(n=Count("id")).values_list("status", "n"))
        out["reservations"] = {"comme_client": as_client, "comme_artisan": as_artisan, "litiges_par_statut": disputes}
    else:
        out["sections_omises_faute_de_droit"].append("reservations")
    if "kyc.review" in perms and profile is not None:
        docs = HandymanDocument.objects.filter(handyman=profile)
        out["kyc"] = {"pieces_par_statut": dict(docs.values_list("status").annotate(n=Count("id")).values_list("status", "n")),
                      "types_deposes": sorted(set(docs.values_list("document_type", flat=True))), "lien": f"/backoffice/kyc/{profile.pk}"}
        from intelligence.models import RiskCase

        out["dossiers_de_risque_actifs"] = [{"type": c.get_kind_display(), "priorite": c.priority, "detecte_le": c.detected_at.date().isoformat()}
                                            for c in RiskCase.objects.filter(subject=u, status__in=RiskCase.ACTIVE)[:5]]
    elif profile is not None:
        out["sections_omises_faute_de_droit"].append("kyc")
    return out


def _kyc_overview(perms: Set[str], args: Dict) -> Dict:
    from handy.models import HandymanDocument, HandymanProfile

    now = timezone.now()
    docs = HandymanDocument.objects.all()
    pending = docs.filter(status="pending").select_related("handyman__user").order_by("uploaded_at")
    oldest = pending.first()
    return {"profils_artisans": HandymanProfile.objects.count(), "profils_approuves": HandymanProfile.objects.filter(is_approved=True).count(),
            "pieces_par_statut": dict(docs.values_list("status").annotate(n=Count("id")).values_list("status", "n")),
            "pieces_en_attente": pending.count(), "plus_ancienne_en_attente_jours": (now - oldest.uploaded_at).days if oldest else None,
            "plus_anciennes": [{"profil": d.handyman_id, "membre": public_name(d.handyman.user), "type": d.get_document_type_display(),
                                "attente_jours": (now - d.uploaded_at).days, "lien": f"/backoffice/kyc/{d.handyman_id}"} for d in pending[:8]],
            "note": "Aucune donnée biométrique ni document d'identité n'est accessible à l'assistant ; la décision KYC reste humaine."}


def _risk_cases(perms: Set[str], args: Dict) -> Dict:
    from intelligence.models import RiskCase

    active = RiskCase.objects.filter(status__in=RiskCase.ACTIVE)
    return {"dossiers_actifs": active.count(), "par_type": {RiskCase(kind=k).get_kind_display(): n for k, n in active.values_list("kind").annotate(n=Count("id"))},
            "par_priorite": {str(p): n for p, n in active.values_list("priority").annotate(n=Count("id"))},
            "priorite_haute": [{"id": c.pk, "membre": public_name(c.subject), "type": c.get_kind_display(), "explication": c.explanation,
                                "detecte_le": c.detected_at.date().isoformat(), "lien": f"/backoffice/kyc?tab=risks&case={c.pk}"}
                               for c in active.filter(priority=3).select_related("subject").order_by("-detected_at")[:6]],
            "note": "Dossiers PROPOSÉS par des règles ; seule l'équipe les confirme ou les écarte."}


def _bookings_overview(perms: Set[str], args: Dict) -> Dict:
    from backoffice.api_system import STUCK_RULES
    from handy.models import Booking, Dispute

    days = args.get("days", 30)
    now = timezone.now()
    window = Booking.objects.filter(created_at__gte=now - timedelta(days=days))
    total = window.count()
    by_status = dict(window.values_list("status").annotate(n=Count("id")).values_list("status", "n"))
    rate = lambda n: round(n / total, 4) if total else None    # noqa: E731
    return {"periode_jours": days, "reservations_creees": total, "par_statut": by_status, "taux_annulation": rate(by_status.get("cancelled", 0)),
            "taux_terminees": rate(by_status.get("completed", 0)), "litiges_ouverts": Dispute.objects.filter(status__in=("open", "under_review")).count(),
            "bloquees": {label: Booking.objects.filter(rule(now)).count() for _, (label, rule) in STUCK_RULES.items()},
            "note": "Les taux portent sur les réservations CRÉÉES pendant la période, quel que soit leur statut actuel."}


def _communications_overview(perms: Set[str], args: Dict) -> Dict:
    from backoffice.models import StaffMessageBatch, StaffMessageDelivery
    from handy.models import Conversation, Message, Notification

    now = timezone.now()
    unread = Message.objects.filter(conversation__kind=Conversation.SUPPORT, is_read=False, via_staff=False)
    oldest = unread.order_by("created_at").first()
    batches = StaffMessageBatch.objects.filter(created_at__gte=now - timedelta(days=7))
    out: Dict[str, Any] = {
        "messagerie": {"fils_avec_reponse_non_lue": unread.values("conversation").distinct().count(), "messages_non_lus": unread.count(),
                       "plus_ancien_non_lu_heures": int((now - oldest.created_at).total_seconds() // 3600) if oldest else None, "lien": "/backoffice/messages"},
        "envois_7j": {"lots": batches.count(), "destinataires": sum(batches.values_list("recipient_count", flat=True)),
                      "resultats": dict(StaffMessageDelivery.objects.filter(batch__in=batches).values_list("status").annotate(n=Count("id")).values_list("status", "n"))},
    }
    if "notifications.view" in perms:
        window = Notification.objects.filter(created_at__gte=now - timedelta(hours=24))
        by_push = {(k or "aucun"): n for k, n in window.values_list("push_status").annotate(n=Count("id"))}
        out["notifications_24h"] = {"total": window.count(), "push_par_statut": by_push,
                                    "en_file_depuis_plus_de_15_min": Notification.objects.filter(push_status="queued", created_at__lt=now - timedelta(minutes=15)).count()}
    else:
        out["sections_omises_faute_de_droit"] = ["notifications"]
    return out


def _insight_tool(scope: str):
    def handler(perms: Set[str], args: Dict) -> Dict:
        return insights.HANDLERS[scope](perms)
    return handler


_DAYS = {"type": "integer", "minimum": 1, "maximum": 90, "description": "Nombre de jours de la période (1 à 90, défaut 30)."}

TOOLS: List[Tool] = [
    Tool("platform_overview", "Consultation des indicateurs généraux…", "Indicateurs généraux réels de la plateforme : membres, artisans, réservations par statut, pièces KYC en attente, litiges ouverts. "
         "Les sections dépendent des droits de l'administrateur.", "dashboard.view", _schema(), _platform_overview),
    Tool("search_users", "Recherche de membres…", "Recherche des membres (clients, artisans, entreprises) par nom, numéro ou identifiant, avec filtres. Coordonnées masquées. 8 résultats par défaut, 10 au plus.",
         "users.view", _schema({"query": {"type": "string", "maxLength": 60, "description": "Nom, fragment de numéro ou identifiant numérique."},
                                "type": {"type": "string", "enum": ["client", "artisan", "company"]}, "actif": {"type": "boolean"},
                                "kyc": {"type": "string", "enum": ["pending", "ready", "approved", "rejected", "incomplete"], "description": "État du dossier KYC (artisans)."},
                                "limit": {"type": "integer", "minimum": 1, "maximum": 10}}), _search_users),
    Tool("get_user_summary", "Consultation de la fiche d'un membre…", "Résumé d'UN membre par identifiant : statut, réservations par statut, litiges, résumé KYC et dossiers de risque (selon les droits). "
         "Aucune pièce, aucune donnée biométrique.", "users.view", _schema({"user_id": {"type": "integer", "minimum": 1, "maximum": 2147483647}}, ["user_id"]), _get_user_summary, ("user_id",)),
    Tool("kyc_overview", "Consultation de la file KYC…", "File de vérification KYC : pièces par statut, ancienneté, plus anciennes pièces en attente.", "kyc.review", _schema(), _kyc_overview),
    Tool("risk_cases", "Consultation des dossiers de risque…", "Dossiers de risque ouverts, proposés par des règles (jamais une preuve), par type et priorité, avec ceux de priorité haute.",
         "kyc.review", _schema(), _risk_cases),
    Tool("bookings_overview", "Consultation des réservations…", "Indicateurs de réservations sur une période : créées, par statut, taux d'annulation et de réalisation, litiges ouverts, réservations bloquées.",
         "bookings.view", _schema({"days": _DAYS}), _bookings_overview, ("days",)),
    Tool("booking_anomalies", "Recherche d'anomalies de réservations…", "Anomalies explicables sur les réservations (30 jours) : bloquées, litiges anciens, annulations répétées, couples client/artisan très répétés. "
         "Chaque alerte donne la règle appliquée, des exemples et des actions PROPOSÉES.", "bookings.view", _schema(), _insight_tool("bookings")),
    Tool("account_alerts", "Recherche d'alertes sur les comptes…", "Alertes explicables sur les comptes : pic d'inscriptions, pièces KYC en attente ou expirées, dossiers de risque prioritaires, signalements non traités. "
         "Chaque alerte donne la règle appliquée, des exemples et des actions PROPOSÉES.", "users.view", _schema(), _insight_tool("accounts")),
    Tool("security_events", "Synthèse des événements de sécurité…", "Synthèse sécurité : échecs et blocages de connexion (Axes), sources suspectes (adresses réduites), connexions, verrouillages de double authentification, "
         "consultations sensibles par le personnel, changements de rôles. Alertes explicables et actions PROPOSÉES.", "security.manage", _schema(), _insight_tool("security")),
    Tool("communications_overview", "Consultation des communications…", "Messagerie de l'équipe (réponses non lues, plus ancien en attente), envois des 7 derniers jours et leur résultat, état des notifications (selon les droits).",
         "messages.send", _schema(), _communications_overview),
]
REGISTRY: Dict[str, Tool] = {t.name: t for t in TOOLS}


def allowed(perms: Set[str]) -> List[Tool]:
    """Outils proposés au modèle : uniquement ceux dont l'administrateur détient le droit."""
    return [t for t in TOOLS if t.permission in perms]


def label_of(name: str) -> str:
    tool = REGISTRY.get(name)
    return tool.label if tool else "Consultation…"


def audit_args(tool: Tool, args: Dict) -> Dict:
    """Arguments consignés dans l'audit : nombres, booléens et énumérations ; jamais un texte libre (nom, numéro) saisi par l'administrateur."""
    return {k: v for k, v in args.items() if isinstance(v, (bool, int)) or k in tool.loggable or (isinstance(v, str) and k in ("type", "kyc"))}


@dataclass
class ToolResult:
    name: str
    ok: bool
    content: str             # transmis au modèle (enveloppé : données non fiables)
    denied: bool = False
    args: Optional[Dict] = None


def execute(user, name: str, raw_args: Any, *, invalid: bool = False) -> ToolResult:
    """Exécute un outil pour `user`. Ne lève jamais : toute erreur devient un résultat d'erreur lisible par le modèle."""
    tool = REGISTRY.get(name)
    if tool is None:
        return ToolResult(name, False, safety.wrap_tool_result(name, '{"erreur":"Outil inconnu : utilise uniquement les outils fournis."}'))
    perms = rbac.user_permissions(user)
    if tool.permission not in perms:                     # contrôle à l'exécution, indépendant de la liste proposée au modèle
        return ToolResult(name, False, safety.wrap_tool_result(name, '{"erreur":"Droits insuffisants : cet administrateur ne peut pas consulter ces données."}'), denied=True)
    if invalid:
        return ToolResult(name, False, safety.wrap_tool_result(name, '{"erreur":"Arguments illisibles : reformule l\'appel."}'))
    try:
        args = _validate(tool.parameters, raw_args)
        with safety.read_only():
            data = tool.handler(perms, args)
        return ToolResult(name, True, safety.wrap_tool_result(name, safety.serialize(data)), args=audit_args(tool, args))
    except ToolError as exc:
        return ToolResult(name, False, safety.wrap_tool_result(name, safety.serialize({"erreur": str(exc)})))
    except Exception:  # noqa: BLE001 - jamais de trace technique vers le modèle ni l'interface
        import logging

        logging.getLogger(__name__).exception("Outil d'assistant « %s » en échec", name)
        return ToolResult(name, False, safety.wrap_tool_result(name, '{"erreur":"Cette consultation a échoué ; réessaie plus tard ou indique que la donnée est indisponible."}'))
