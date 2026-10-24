"""Contrats d'engagement : brouillon, proposition, acceptation des deux parties, avenants, suspension, préavis, résiliation,
renouvellement, clôture. Un contrat n'est JAMAIS supprimé : tout changement est un événement horodaté (historique complet).

Acceptation électronique simple (qui, quand, quelle empreinte des conditions) : elle prouve l'accord des parties dans Tratra,
sans prétendre à la valeur d'une signature qualifiée ni remplacer un contrat de travail légal."""
import hashlib
import json
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from engagements.dates import add_months
from engagements.models import (
    ContractAcceptance, ContractAmendment, ContractSuspension, EngagementApplication, EngagementContract, EngagementPosting,
)
from engagements.rules import rules_for
from engagements.services import installments as inst_svc
from engagements.services import planning
from engagements.services.common import (
    EngagementError, conflict, moment, counterpart, notify_role, organization_actor, party_of, principal_side, record, require_eligible_worker,
)
from engagements.services.validation import PERIODS, MISSION_TYPES, RELATIONSHIPS, Validator, check_common_terms, derived_hours
from handy.models import Service, ServiceCategory

logger = logging.getLogger(__name__)
User = get_user_model()

TERM_FIELDS = ("title", "description", "conditions", "benefits", "category_id", "service_id", "mission_type", "work_relationship", "start_date", "end_date", "auto_renew",
               "renewal_term_months", "schedule", "hours_per_week", "location_city", "location_address", "amount", "period", "currency", "payment_day",
               "proration_mode", "overtime_hourly_rate", "notice_period_days", "bookings_mode", "legal_notice_ack")
AMENDABLE = {"amount", "schedule", "hours_per_week", "end_date", "notice_period_days", "conditions", "benefits", "description", "auto_renew", "renewal_term_months", "payment_day",
             "overtime_hourly_rate", "location_address", "location_city", "proration_mode"}
LIVE = EngagementContract.LIVE


# ── Conditions, empreinte ───────────────────────────────────────────────────────────────────────────────────────────

def snapshot(c: EngagementContract) -> dict:
    out = {}
    for f in TERM_FIELDS:
        v = getattr(c, f)
        out[f] = v.isoformat() if hasattr(v, "isoformat") else (str(v.quantize(Decimal("0.01"))) if isinstance(v, Decimal) else v)
    if c.template_id:          # contrat établi sur un modèle : le texte des articles fait partie des conditions acceptées et signées
        out.update(template=f"{c.template.code}@v{c.template.version}", reference=c.reference, articles=c.articles)
    return out


def terms_hash(c: EngagementContract) -> str:
    return hashlib.sha256(json.dumps(snapshot(c), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def check_version(c: EngagementContract, expected) -> None:
    if expected is not None and int(expected) != c.version:
        raise conflict("version_conflict", "Ce contrat a été modifié entre-temps : rechargez-le.", current_version=c.version)


def _touch(c: EngagementContract, *fields: str) -> None:
    c.version += 1
    c.save(update_fields=list({*fields, "version", "updated_at"}))


def _clean_terms(data: dict, *, instance: Optional[EngagementContract], worker, today: date, strict_start: bool) -> dict:
    v = Validator()
    base = snapshot(instance) if instance is not None else {}
    merged = {**base, **data}
    category = ServiceCategory.objects.filter(pk=merged.get("category_id") or merged.get("category"), is_active=True).first()
    if category is None:
        v.err("category", "Catégorie : choix obligatoire.")
    mission_type = v.choice(merged, "mission_type", label="Type de mission", allowed=MISSION_TYPES)
    relationship = v.choice(merged, "work_relationship", label="Nature de la relation", allowed=RELATIONSHIPS, default="independent")
    start = v.date(merged, "start_date", label="Début", required=True)
    end = v.date(merged, "end_date", label="Fin")
    schedule = v.schedule(merged)
    out = {
        "title": v.text(merged, "title", label="Titre", max_len=160, min_len=5, required=True),
        "description": v.text(merged, "description", label="Missions confiées", max_len=4000),
        "conditions": v.text(merged, "conditions", label="Conditions", max_len=4000),
        "benefits": v.text(merged, "benefits", label="Avantages", max_len=2000),
        "mission_type": mission_type, "work_relationship": relationship, "start_date": start, "end_date": end, "schedule": schedule,
        "auto_renew": bool(merged.get("auto_renew")),
        "renewal_term_months": v.integer(merged, "renewal_term_months", label="Durée d'un renouvellement (mois)", lo=1, hi=120),
        "location_city": v.text(merged, "location_city", label="Ville", max_len=100),
        "location_address": v.text(merged, "location_address", label="Adresse", max_len=255),
        "amount": v.amount(merged, "amount", label="Rémunération", required=True),
        "period": v.choice(merged, "period", label="Période de rémunération", allowed=PERIODS, default="monthly"),
        "currency": "XOF",
        "payment_day": v.integer(merged, "payment_day", label="Jour de paiement", lo=1, hi=31),
        "proration_mode": v.choice(merged, "proration_mode", label="Prorata", allowed={"none", "calendar_days"}, default="none"),
        "overtime_hourly_rate": v.amount(merged, "overtime_hourly_rate", label="Taux horaire des heures supplémentaires"),
        "notice_period_days": v.integer(merged, "notice_period_days", label="Préavis (jours)", lo=0, hi=365, default=7),
        "bookings_mode": v.choice(merged, "bookings_mode", label="Réservations", allowed={"none", "per_occurrence"}, default="none"),
        "legal_notice_ack": bool(merged.get("legal_notice_ack")),
    }
    out["hours_per_week"] = derived_hours(schedule, merged.get("hours_per_week"))
    if strict_start and start and start < today:
        v.err("start_date", "Le début ne peut pas être dans le passé.")
    if category is not None:
        rules = rules_for(category)
        check_common_terms(v, rules=rules, mission_type=mission_type, relationship=relationship, start=start, end=end, ack=out["legal_notice_ack"],
                           auto_renew=out["auto_renew"], renewal_months=out["renewal_term_months"])
        if out["notice_period_days"] is not None and out["notice_period_days"] < rules.min_notice_days(relationship):
            v.err("notice_period_days", f"Préavis minimal pour cette catégorie : {rules.min_notice_days(relationship)} jours.")
    if out["bookings_mode"] == "per_occurrence":
        if relationship != "independent":
            v.err("bookings_mode", "Les réservations par occurrence ne concernent que les prestations indépendantes.")
        if not schedule:
            v.err("bookings_mode", "Définissez un planning pour générer des réservations.")
    service_id = merged.get("service_id") or merged.get("service")
    service = None
    if service_id:
        service = Service.objects.filter(pk=service_id, handyman=worker).first()
        if service is None:
            v.err("service", "Cette prestation n'appartient pas au prestataire.")
    v.raise_if()
    out["category"], out["service"] = category, service
    return out


# ── Création, édition, proposition ──────────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def create_draft(user, data: dict, *, today: Optional[date] = None) -> EngagementContract:
    today = today or timezone.localdate()
    organization_id = data.get("organization") or None
    application = posting = None
    if data.get("application"):
        application = EngagementApplication.objects.select_for_update(of=("self",)).select_related("posting").filter(pk=data["application"]).first()
        if application is None:
            raise EngagementError("not_found", "Candidature introuvable.", 404)
        from engagements.services.postings import posting_side

        if not posting_side(application.posting, user):
            raise EngagementError("not_found", "Candidature introuvable.", 404)
        if application.status != "selected":
            raise conflict("application_not_selected", "Retenez d'abord cette candidature avant de proposer un contrat.")
        if hasattr(application, "contract"):
            raise conflict("contract_exists", "Un contrat existe déjà pour cette candidature.", contract_id=application.contract.pk)
        posting, worker = application.posting, application.applicant
        organization_id = posting.organization_id
        prefill = {f: getattr(posting, f) for f in ("title", "description", "conditions", "benefits", "mission_type", "work_relationship", "start_date", "end_date",
                                                      "schedule", "hours_per_week", "amount", "period")}
        prefill.update(category_id=posting.category_id, location_city=posting.city, legal_notice_ack=posting.employment_notice_ack)
        if application.proposed_amount:
            prefill["amount"] = application.proposed_amount
        data = {**prefill, **{k: v for k, v in data.items() if k not in ("application", "worker", "organization")}}
    else:
        worker = User.objects.filter(pk=data.get("worker"), is_active=True).first()
        if worker is None:
            raise EngagementError("invalid", "Prestataire introuvable.", 400, fields={"worker": "Choisissez un professionnel vérifié."})
        if organization_id and not organization_actor(user, organization_id):
            raise EngagementError("organization_forbidden", "Vous ne pouvez pas engager l'organisation.", 403)
    if worker.pk == user.pk or (organization_id and worker.owned_organizations.filter(pk=organization_id).exists()):
        raise EngagementError("invalid", "Le prestataire ne peut pas être son propre donneur d'ordre.", 400, fields={"worker": "Prestataire invalide."})
    require_eligible_worker(worker)
    cleaned = _clean_terms(data, instance=None, worker=worker, today=today, strict_start=True)
    template = _template(data.get("template"), cleaned["work_relationship"], cleaned["category"])
    contract = EngagementContract.objects.create(principal=user, organization_id=organization_id, worker=worker, posting=posting, application=application,
                                                 template=template, signature_required=template is not None, **cleaned)
    record(contract, user, "created", source="posting" if application else "direct", template=f"{template.code}@v{template.version}" if template else None)
    return contract


def _template(requested, relationship: str, category):
    """Modèle juridique du contrat : celui demandé (s'il est validé et adapté), sinon le meilleur modèle VALIDÉ ; aucun modèle validé =
    ancien parcours (acceptation simple, sans signature ni document scellé)."""
    from engagements.models import ContractTemplate
    from engagements.services import templates

    if requested in (None, "", "auto"):
        return templates.template_for(relationship, category)
    t = ContractTemplate.objects.filter(pk=requested).first() if str(requested).isdigit() else None
    if t is None:
        raise EngagementError("invalid", "Modèle de contrat introuvable.", 400, fields={"template": "Modèle introuvable."})
    templates.check_usable(t, relationship, category)
    return t


@transaction.atomic
def update_draft(contract: EngagementContract, user, data: dict, *, expected_version=None, today: Optional[date] = None) -> EngagementContract:
    contract = EngagementContract.objects.select_for_update().get(pk=contract.pk)
    if not principal_side(contract, user):
        raise EngagementError("not_found", "Introuvable.", 404)
    if contract.status != "draft":
        raise conflict("not_editable", "Seul un brouillon est modifiable : après proposition, passez par un avenant.")
    check_version(contract, expected_version)
    cleaned = _clean_terms({k: v for k, v in data.items() if k in TERM_FIELDS or k in ("category", "service")}, instance=contract, worker=contract.worker, today=today or timezone.localdate(), strict_start=True)
    for field, value in cleaned.items():
        setattr(contract, field, value)
    if "template" in data or contract.template_id:
        contract.template = _template(data.get("template", contract.template_id), contract.work_relationship, contract.category)
        contract.signature_required = contract.template is not None
    contract.version += 1
    contract.save()
    return contract


def _accept(contract: EngagementContract, user, role: str) -> bool:
    _, created = ContractAcceptance.objects.get_or_create(contract=contract, role=role, terms_version=contract.terms_version,
                                                          defaults=dict(user=user, terms_hash=contract.terms_hash))
    return created


@transaction.atomic
def propose(contract: EngagementContract, user, *, expected_version=None, today: Optional[date] = None) -> EngagementContract:
    today = today or timezone.localdate()
    contract = EngagementContract.objects.select_for_update(of=("self",)).select_related("worker", "principal").get(pk=contract.pk)
    if not principal_side(contract, user):
        raise EngagementError("not_found", "Introuvable.", 404)
    if contract.status != "draft":
        raise conflict("not_draft", "Ce contrat n'est plus un brouillon.")
    check_version(contract, expected_version)
    cleaned = _clean_terms({}, instance=contract, worker=contract.worker, today=today, strict_start=True)  # revalide avec les règles du moment
    if contract.acceptances.filter(terms_version=contract.terms_version).exists():
        contract.terms_version += 1                      # conditions renvoyées après demande de modification : nouvelle version à accepter
    if contract.template_id:
        from engagements.services import templates

        templates.check_usable(contract.template, contract.work_relationship, contract.category)   # modèle retiré entre-temps : refus
        render_articles(contract)
    contract.terms_hash = terms_hash(contract)
    require_eligible_worker(contract.worker)
    contract.status = "pending_acceptance"
    contract.version += 1
    contract.save(update_fields=["status", "terms_hash", "terms_version", "version", "articles", "updated_at"])
    _accept(contract, user, "principal")
    record(contract, user, "proposed", terms_version=contract.terms_version, terms_hash=contract.terms_hash)
    notify_role(contract, "worker", "contract_proposed", f"Un contrat vous est proposé : « {contract.title} ». Lisez les conditions puis acceptez ou demandez des modifications.",
                title="Contrat à accepter", key=f"proposed-v{contract.terms_version}")
    return contract


@transaction.atomic
def send_back(contract: EngagementContract, user, note: str = "") -> EngagementContract:
    """Retour en brouillon : le prestataire demande des modifications, ou le donneur d'ordre retire sa proposition."""
    contract = EngagementContract.objects.select_for_update().get(pk=contract.pk)
    role = party_of(contract, user)
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    if contract.status != "pending_acceptance":
        raise conflict("not_pending", "Ce contrat n'est pas en attente d'acceptation.")
    contract.status = "draft"
    _touch(contract, "status")
    record(contract, user, "changes_requested" if role == "worker" else "proposal_withdrawn", note=(note or "")[:500])
    if role == "worker":
        notify_role(contract, "principal", "contract_proposed", f"Le prestataire demande des modifications sur « {contract.title} ».", title="Modifications demandées", key=f"changes-v{contract.terms_version}")
    return contract


@transaction.atomic
def decline(contract: EngagementContract, user, reason: str = "") -> EngagementContract:
    contract = EngagementContract.objects.select_for_update().get(pk=contract.pk)
    role = party_of(contract, user)
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    if contract.status not in ("draft", "pending_acceptance", "accepted"):
        raise conflict("not_cancellable", "Ce contrat ne peut plus être annulé avant son début.")
    if contract.status == "draft" and role == "worker":
        raise EngagementError("not_found", "Introuvable.", 404)
    was = contract.status
    contract.status, contract.ended_at, contract.end_reason = "cancelled", timezone.now(), (reason or "Annulé avant le début.")[:500]
    _touch(contract, "status", "ended_at", "end_reason")
    record(contract, user, "cancelled", by=role, was=was, reason=reason)
    notify_role(contract, counterpart(role), "contract_ended", f"Le contrat « {contract.title} » est annulé avant son début.", title="Contrat annulé", key="cancelled", exclude_user=user)
    return contract


@transaction.atomic
def accept(contract: EngagementContract, user, terms_hash_value: str, today: Optional[date] = None) -> EngagementContract:
    """Acceptation des conditions EXACTES (empreinte) par une partie ; quand les deux ont accepté, le contrat est confirmé."""
    today = today or timezone.localdate()
    contract = EngagementContract.objects.select_for_update(of=("self",)).select_related("worker", "principal").get(pk=contract.pk)
    role = party_of(contract, user)
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    if contract.status != "pending_acceptance":
        raise conflict("not_pending", "Ce contrat n'est pas en attente d'acceptation.")
    if terms_hash_value != contract.terms_hash:
        raise conflict("terms_changed", "Les conditions ont changé depuis votre lecture : relisez-les avant d'accepter.", current_hash=contract.terms_hash)
    if role == "worker":
        require_eligible_worker(user)
    _accept(contract, user, role)
    record(contract, user, "accepted", by=role, terms_version=contract.terms_version)
    both = set(contract.acceptances.filter(terms_version=contract.terms_version).values_list("role", flat=True)) >= {"principal", "worker"}
    if both:
        _confirm(contract, today)
    else:
        notify_role(contract, counterpart(role), "contract_accepted", f"L'autre partie a accepté « {contract.title} » : à votre tour.", title="Contrat accepté", key=f"accepted-{role}-v{contract.terms_version}", exclude_user=user)
        _touch(contract)
    return contract


def _confirm(contract: EngagementContract, today: date) -> None:
    contract.status = "accepted"
    contract.version += 1
    contract.save(update_fields=["status", "version", "updated_at"])
    if contract.signature_required:
        # Conditions acceptées par les deux parties : le document à signer est émis et scellé ; le contrat n'est conclu qu'une fois signé.
        from engagements import documents

        doc = documents.issue(contract, kind="contract", stage="for_signature")
        record(contract, None, "ready_to_sign", reference=doc.reference, sha256=doc.sha256)
        for role in ("worker", "principal"):
            notify_role(contract, role, "contract_accepted", f"« {contract.title} » est prêt à être signé ({doc.reference}).", title="Contrat à signer",
                        key=f"to-sign-v{contract.terms_version}")
        return
    # Parcours sans modèle validé : acceptation électronique simple des conditions (pas de signature ni de document scellé).
    notify_role(contract, "worker", "contract_accepted", f"Le contrat « {contract.title} » est accepté par les deux parties.", title="Contrat conclu", key="confirmed")
    notify_role(contract, "principal", "contract_accepted", f"Le contrat « {contract.title} » est accepté par les deux parties.", title="Contrat conclu", key="confirmed")
    _fill_posting(contract)
    sync(contract, today)


def _fill_posting(contract: EngagementContract) -> None:
    if contract.posting_id:
        from engagements.services.postings import close_posting

        posting = EngagementPosting.objects.get(pk=contract.posting_id)
        if posting.status == "open":
            posting.status, posting.closed_at = "filled", timezone.now()
            posting.save(update_fields=["status", "closed_at", "updated_at"])
        EngagementApplication.objects.filter(posting_id=contract.posting_id, status__in=EngagementApplication.OPEN).update(status="rejected", decision_note="Poste pourvu.", decided_at=timezone.now())


# ── Modèle juridique et signature ───────────────────────────────────────────────────────────────────────────────────

ROLE_WORDS = {"employment": ("Employeur", "Salarié(e)"), "independent": ("Client", "Prestataire")}
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _values(c: EngagementContract) -> dict:
    """Valeurs des variables des articles (liste blanche de engagements/legal.py)."""
    from engagements.documents import _person

    principal_role, worker_role = ROLE_WORDS.get(c.work_relationship, ROLE_WORDS["independent"])
    slots = [f"{DAYS[int(s.get('weekday', 0)) % 7]} {s.get('start', '')}–{s.get('end', '')}" for s in (c.schedule or []) if isinstance(s, dict)]
    period = dict(EngagementContract.PERIODS).get(c.period, c.period).lower()
    return {"reference": c.reference or "—", "principal_role": principal_role, "worker_role": worker_role, "principal_name": _person(c.principal),
            "worker_name": _person(c.worker), "category": c.category.name, "title": c.title, "missions": c.description or "—",
            "location_city": c.location_city or "—", "start_date": c.start_date.strftime("%d/%m/%Y"),
            "end_date": f"jusqu'au {c.end_date:%d/%m/%Y}" if c.end_date else "indéterminée", "schedule": ", ".join(slots) or "à convenir dans le planning",
            "hours_per_week": str(c.hours_per_week or "—"), "amount": f"{int(c.amount):,} {c.currency}".replace(",", " "), "period": period,
            "payment_day": str(c.payment_day) if c.payment_day else "jour convenu", "benefits": c.benefits or "aucun",
            "conditions": c.conditions or "aucune", "notice_period_days": str(c.notice_period_days)}


def render_articles(c: EngagementContract) -> None:
    """Fige les articles du modèle, adaptés au métier, avec les conditions du contrat (référence attribuée ici si besoin)."""
    from engagements import legal
    from engagements.documents import ensure_reference

    ensure_reference(c)
    slugs = [s for s in (c.category.slug, getattr(c.category.parent, "slug", None)) if s]
    c.articles = legal.render_articles(c.template.articles, _values(c), slugs)


@transaction.atomic
def sign(contract: EngagementContract, user, *, consent: bool, ip: str = "", user_agent: str = "", today: Optional[date] = None) -> EngagementContract:
    """Signature électronique simple d'une partie sur le document à signer ; les deux signatures émettent le document FINAL scellé
    et le contrat passe « Signé » (puis « En cours » à sa date de début)."""
    from engagements import documents

    today = today or timezone.localdate()
    contract = EngagementContract.objects.select_for_update(of=("self",)).select_related("worker", "principal", "template", "category").get(pk=contract.pk)
    role = party_of(contract, user)
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    if not contract.signature_required or contract.status != "accepted":
        raise conflict("not_to_sign", "Ce contrat n'attend pas de signature.")
    if consent is not True:
        raise EngagementError("consent_required", "Cochez la case « J'ai lu le contrat et je le signe » pour signer.", 400, fields={"consent": "Obligatoire."})
    if role == "worker":
        require_eligible_worker(user)
    try:
        doc, _, created = documents.sign_document(contract, user, role=role, ip=ip, user_agent=user_agent)
    except documents.DocumentError as exc:
        raise conflict(exc.code, exc.message)
    if created:
        record(contract, user, "signed", by=role, reference=doc.reference, sha256=doc.sha256)
    roles = set(doc.signatures.values_list("role", flat=True))
    if roles >= {"principal", "worker"}:
        final = documents.issue(contract, kind="contract", stage="final", actor=user)
        contract.status = "signed"
        _touch(contract, "status")
        record(contract, user, "concluded", reference=final.reference, sha256=final.sha256)
        for r in ("worker", "principal"):
            notify_role(contract, r, "contract_accepted", f"« {contract.title} » est signé par les deux parties ({final.reference}).", title="Contrat signé",
                        key=f"signed-v{contract.terms_version}")
        _fill_posting(contract)
        sync(contract, today)
    elif created:
        notify_role(contract, counterpart(role), "contract_accepted", f"L'autre partie a signé « {contract.title} » : à votre tour.", title="Contrat à signer",
                    key=f"signed-{role}-v{contract.terms_version}", exclude_user=user)
        _touch(contract)
    return contract


# ── Cycle de vie : synchronisation avec le calendrier ───────────────────────────────────────────────────────────────

def sync(contract: EngagementContract, today: Optional[date] = None) -> list:
    """Fait avancer le contrat selon les DATES (début, suspension, avenants acceptés, renouvellement, fin) et rattrape les
    échéances, le planning et les réservations. IDEMPOTENT : peut être rejoué sans effet double. Renvoie les changements."""
    today = today or timezone.localdate()
    changes = []
    contract.refresh_from_db()
    if contract.status in EngagementContract.ENDED or contract.status in ("draft", "pending_acceptance"):
        return changes
    if contract.signature_required and contract.status == "accepted":
        return changes                     # conditions acceptées, signatures attendues : rien ne commence avant la signature
    if contract.status in ("accepted", "signed") and contract.start_date <= today:
        contract.status, contract.activated_at = "active", contract.activated_at or moment(today)
        _touch(contract, "status", "activated_at")
        record(contract, None, "activated", date=today)
        notify_role(contract, "worker", "contract_active", f"Le contrat « {contract.title} » commence aujourd'hui.", title="Contrat en cours", key="active")
        notify_role(contract, "principal", "contract_active", f"Le contrat « {contract.title} » commence aujourd'hui.", title="Contrat en cours", key="active")
        changes.append("activated")
    for amendment in contract.amendments.filter(status="accepted", effective_date__lte=today):
        _apply_amendment(contract, amendment, today)
        changes.append(f"amendment:{amendment.pk}")
    if contract.status in ("active", "suspended"):
        suspended_now = any(w.starts_on <= today and (w.ends_on is None or today < w.ends_on) for w in contract.suspensions.all())
        wanted = "suspended" if suspended_now else "active"
        if wanted != contract.status:
            contract.status = wanted
            _touch(contract, "status")
            record(contract, None, "suspended" if wanted == "suspended" else "resumed", date=today)
            notify_role(contract, "worker", "contract_suspended", f"Le contrat « {contract.title} » est {'suspendu' if wanted == 'suspended' else 'repris'}.", title="Contrat " + ("suspendu" if wanted == "suspended" else "repris"), key=f"{wanted}-{today.isoformat()}")
            notify_role(contract, "principal", "contract_suspended", f"Le contrat « {contract.title} » est {'suspendu' if wanted == 'suspended' else 'repris'}.", title="Contrat " + ("suspendu" if wanted == "suspended" else "repris"), key=f"{wanted}-{today.isoformat()}")
            changes.append(wanted)
    end = contract.effective_end
    if end and today > end and contract.status in LIVE:
        if contract.ends_on and contract.ends_on < today:
            _finish(contract, "terminated", contract.end_reason or "Fin du préavis.", today)
            changes.append("terminated")
        elif _auto_renew(contract, today):
            changes.append("renewed")
        else:
            _finish(contract, "completed", "Terme du contrat.", today)
            changes.append("completed")
    if contract.status in LIVE:
        inst_svc.generate_installments(contract, today)
        planning.generate_shifts(contract, today)
        planning.materialize_bookings(contract, today)
    return changes


def _auto_renew(contract: EngagementContract, today: date) -> bool:
    if not (contract.auto_renew and contract.end_date and contract.renewal_term_months and not contract.non_renewal_at and not contract.ends_on):
        return False
    new_end = add_months(contract.end_date, contract.renewal_term_months)
    months = (new_end.year - contract.start_date.year) * 12 + new_end.month - contract.start_date.month
    if months > rules_for(contract.category_id).max_duration_months:
        return False                                          # plafond de durée atteint : le contrat se termine au lieu de se renouveler
    contract.end_date = new_end
    contract.renewal_count += 1
    contract.terms_version += 1
    contract.terms_hash = terms_hash(contract)
    _touch(contract, "end_date", "renewal_count", "terms_version", "terms_hash")
    record(contract, None, "renewed", auto=True, new_end=new_end, renewal=contract.renewal_count)
    for role in ("worker", "principal"):
        notify_role(contract, role, "contract_renewal", f"Le contrat « {contract.title} » est renouvelé jusqu'au {new_end:%d/%m/%Y}.", title="Contrat renouvelé", key=f"renewed-{contract.renewal_count}")
    inst_svc.generate_installments(contract, today)
    return True


def _cancel_future_occurrences(contract: EngagementContract, after: date, actor) -> None:
    for event in contract.schedule_events.filter(kind__in=("shift", "replacement"), date__gt=after, status__in=("planned", "approved", "requested")).select_related("booking"):
        # Annulée (trace conservée) et marquée « saisie » : libère l'unicité des interventions générées si le préavis est retiré.
        event.status, event.source, event.note = "cancelled", "manual", "Contrat terminé."
        event.save(update_fields=["status", "source", "note", "updated_at"])
        planning._booking_cancel(event, actor)


def _finish(contract: EngagementContract, status: str, reason: str, today: date, actor=None) -> None:
    contract.status, contract.ended_at = status, moment(today)
    contract.ends_on = contract.ends_on or (min(today, contract.end_date) if contract.end_date else today)
    contract.end_reason = (contract.end_reason or reason)[:500]
    _touch(contract, "status", "ended_at", "ends_on", "end_reason")
    _cancel_future_occurrences(contract, contract.ends_on, actor)
    inst_svc.reconcile_end(contract, today)
    record(contract, actor, "ended", status=status, reason=reason, ends_on=contract.ends_on)
    for role in ("worker", "principal"):
        notify_role(contract, role, "contract_ended", f"Le contrat « {contract.title} » est {'résilié' if status == 'terminated' else 'terminé'}. Vous pouvez évaluer l'autre partie.", title="Contrat " + ("résilié" if status == "terminated" else "terminé"), key=f"ended-{status}")


# ── Avenants ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _open_amendment(contract: EngagementContract):
    return contract.amendments.filter(status__in=("proposed", "accepted")).first()


@transaction.atomic
def propose_amendment(contract: EngagementContract, user, data: dict, *, expected_version=None, today: Optional[date] = None) -> ContractAmendment:
    today = today or timezone.localdate()
    contract = EngagementContract.objects.select_for_update(of=("self",)).select_related("worker").get(pk=contract.pk)
    role = party_of(contract, user)
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    if contract.status not in ("active", "suspended", "notice", "accepted", "signed") or (contract.signature_required and contract.status == "accepted"):
        raise conflict("contract_not_live", "Un avenant ne concerne qu'un contrat conclu (signé) ou en vigueur.")
    check_version(contract, expected_version)
    if _open_amendment(contract) is not None:
        raise conflict("amendment_pending", "Un avenant est déjà en cours : attendez la réponse de l'autre partie.")
    v = Validator()
    kind = v.choice(data, "kind", label="Nature de l'avenant", allowed={k for k, _ in ContractAmendment.KINDS}, default="change")
    reason = v.text(data, "reason", label="Motif", max_len=500, min_len=5, required=True)
    effective = v.date(data, "effective_date", label="Date d'effet") or today
    v.raise_if()
    if effective < today or effective > today + timedelta(days=366):
        raise EngagementError("invalid", "La date d'effet doit être comprise entre aujourd'hui et un an.", 400, fields={"effective_date": "Date d'effet invalide."})
    changes = data.get("changes") or {}
    if not isinstance(changes, dict):
        raise EngagementError("invalid", "Modifications invalides.", 400, fields={"changes": "Objet attendu."})
    if kind in ("change", "renewal"):
        unknown = set(changes) - AMENDABLE
        if unknown or not changes:
            raise EngagementError("invalid", "Seules certaines conditions sont modifiables par avenant.", 400, fields={"changes": f"Non modifiable : {', '.join(sorted(unknown)) or 'aucune modification'}."})
        _clean_terms({**changes}, instance=contract, worker=contract.worker, today=today, strict_start=False)   # valide le résultat complet
        if kind == "renewal" and (not changes.get("end_date") or (contract.end_date and str(changes["end_date"]) <= contract.end_date.isoformat())):
            raise EngagementError("invalid", "Un renouvellement prolonge la date de fin.", 400, fields={"changes": "Nouvelle date de fin postérieure requise."})
    elif kind == "suspend":
        v2 = Validator()
        s = v2.date(changes, "starts_on", label="Début de suspension") or effective
        e = v2.date(changes, "ends_on", label="Fin de suspension")
        v2.raise_if()
        if e and e <= s:
            raise EngagementError("invalid", "La fin de suspension doit suivre son début.", 400, fields={"changes": "Période invalide."})
        changes = {"starts_on": s.isoformat(), **({"ends_on": e.isoformat()} if e else {})}
        effective = s if s >= today else today
    elif kind == "end":
        v2 = Validator()
        e = v2.date(changes, "end_date", label="Date de fin", required=True)
        v2.raise_if()
        if e < today or e < contract.start_date:
            raise EngagementError("invalid", "La date de fin ne peut pas être dans le passé.", 400, fields={"changes": "Date de fin invalide."})
        changes = {"end_date": e.isoformat()}
    elif kind == "cancel_notice":
        if contract.status != "notice" or contract.notice_given_by_id is None:
            raise conflict("no_notice", "Aucun préavis à annuler.")
        changes = {}
    amendment = ContractAmendment.objects.create(contract=contract, proposed_by=user, kind=kind, changes=json_safe(changes), reason=reason, effective_date=effective)
    record(contract, user, "amendment_proposed", amendment=amendment.pk, kind=kind, effective_date=effective)
    notify_role(contract, counterpart(role), "contract_amendment", f"Avenant proposé sur « {contract.title} » ({amendment.get_kind_display().lower()}) : à accepter ou refuser.", title="Avenant à valider", key=f"amend-{amendment.pk}-proposed")
    _touch(contract)
    return amendment


def json_safe(value):
    return json.loads(json.dumps(value, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o)))


@transaction.atomic
def respond_amendment(amendment: ContractAmendment, user, accept_it: bool, today: Optional[date] = None) -> ContractAmendment:
    today = today or timezone.localdate()
    amendment = ContractAmendment.objects.select_for_update(of=("self",)).select_related("contract", "proposed_by").get(pk=amendment.pk)
    contract = EngagementContract.objects.select_for_update(of=("self",)).select_related("worker").get(pk=amendment.contract_id)
    role = party_of(contract, user)
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    if role == party_of(contract, amendment.proposed_by):
        raise EngagementError("forbidden", "C'est à l'AUTRE partie de répondre à cet avenant.", 403)
    if amendment.status != "proposed":
        raise conflict("not_open", "Cet avenant a déjà reçu une réponse.")
    amendment.status, amendment.responded_by, amendment.responded_at = ("accepted" if accept_it else "rejected"), user, timezone.now()
    amendment.save(update_fields=["status", "responded_by", "responded_at"])
    record(contract, user, "amendment_accepted" if accept_it else "amendment_rejected", amendment=amendment.pk)
    notify_role(contract, counterpart(role), "contract_amendment", f"Votre avenant sur « {contract.title} » est {'accepté' if accept_it else 'refusé'}.", title="Avenant " + ("accepté" if accept_it else "refusé"), key=f"amend-{amendment.pk}-{'ok' if accept_it else 'ko'}")
    if accept_it and amendment.effective_date <= today:
        _apply_amendment(contract, amendment, today)
    else:
        _touch(contract)
    return amendment


@transaction.atomic
def withdraw_amendment(amendment: ContractAmendment, user) -> ContractAmendment:
    amendment = ContractAmendment.objects.select_for_update(of=("self",)).select_related("contract").get(pk=amendment.pk)
    if amendment.proposed_by_id != user.id:
        raise EngagementError("forbidden", "Seul l'auteur peut retirer son avenant.", 403)
    if amendment.status != "proposed":
        raise conflict("not_open", "Cet avenant ne peut plus être retiré.")
    amendment.status = "withdrawn"
    amendment.save(update_fields=["status"])
    record(amendment.contract, user, "amendment_withdrawn", amendment=amendment.pk)
    return amendment


def _apply_amendment(contract: EngagementContract, amendment: ContractAmendment, today: date) -> None:
    """Applique un avenant ACCEPTÉ : nouvelle version des conditions, nouvelle empreinte, acceptations des deux parties à cette
    version, échéances et planning à venir recalculés (jamais les périodes déjà commencées)."""
    changes, kind = amendment.changes or {}, amendment.kind
    if kind in ("change", "renewal"):
        cleaned = _clean_terms(changes, instance=contract, worker=contract.worker, today=today, strict_start=False)
        for field in changes:
            if field in AMENDABLE:
                setattr(contract, field, cleaned[field] if field in cleaned else changes[field])
        if kind == "renewal":
            contract.renewal_count += 1
            contract.non_renewal_at = contract.non_renewal_by = None
    elif kind == "suspend":
        starts = date.fromisoformat(changes["starts_on"])
        ends = date.fromisoformat(changes["ends_on"]) if changes.get("ends_on") else None
        ContractSuspension.objects.create(contract=contract, starts_on=starts, ends_on=ends, reason=amendment.reason, source="agreed", created_by=amendment.proposed_by)
    elif kind == "end":
        end = date.fromisoformat(changes["end_date"])
        contract.ends_on, contract.end_reason, contract.status = end, "Fin d'un commun accord.", ("notice" if end > today else contract.status)
    elif kind == "cancel_notice":
        contract.ends_on = contract.notice_given_by = contract.notice_given_at = None
        contract.end_reason, contract.status = "", "active"
    contract.terms_version += 1
    if contract.template_id:
        render_articles(contract)          # texte consolidé à jour ; le document signé d'origine n'est jamais modifié
    contract.terms_hash = terms_hash(contract)
    amendment.status, amendment.applied_at = "applied", timezone.now()
    amendment.save(update_fields=["status", "applied_at"])
    contract.version += 1
    contract.save()
    if contract.documents.filter(kind="contract", stage="final").exists():
        from engagements import documents

        documents.issue(contract, kind="amendment", stage="final", amendment=amendment, actor=amendment.responded_by)
    for role, user in (("principal", amendment.proposed_by if party_of(contract, amendment.proposed_by) == "principal" else amendment.responded_by),
                       ("worker", amendment.proposed_by if party_of(contract, amendment.proposed_by) == "worker" else amendment.responded_by)):
        if user is not None:
            ContractAcceptance.objects.get_or_create(contract=contract, role=role, terms_version=contract.terms_version, defaults=dict(user=user, terms_hash=contract.terms_hash))
    record(contract, amendment.responded_by, "amendment_applied", amendment=amendment.pk, kind=kind, terms_version=contract.terms_version)
    inst_svc.regenerate_future(contract, amendment.effective_date, today)
    inst_svc.reconcile_end(contract, today)
    planning.regenerate_future_shifts(contract, amendment.effective_date, today)
    if kind == "end" and contract.ends_on and contract.ends_on <= today:
        _finish(contract, "terminated", "Fin d'un commun accord.", today, amendment.responded_by)
    elif kind == "suspend":
        sync(contract, today)


# ── Suspension, reprise, préavis, résiliation, clôture ──────────────────────────────────────────────────────────────

@transaction.atomic
def resume(contract: EngagementContract, user, today: Optional[date] = None) -> EngagementContract:
    """Reprise d'une suspension D'UN COMMUN ACCORD par l'une ou l'autre partie (une suspension décidée par la plateforme ne
    se lève que par la plateforme)."""
    today = today or timezone.localdate()
    contract = EngagementContract.objects.select_for_update().get(pk=contract.pk)
    role = party_of(contract, user)
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    windows = [w for w in contract.suspensions.all() if w.starts_on <= today and (w.ends_on is None or today < w.ends_on) or w.starts_on > today]
    if contract.status != "suspended" and not windows:
        raise conflict("not_suspended", "Ce contrat n'est pas suspendu.")
    if any(w.source == "admin" for w in windows):
        raise EngagementError("forbidden", "Cette suspension a été décidée par la plateforme : seule la plateforme peut la lever.", 403)
    for w in windows:
        w.ends_on = max(today, w.starts_on)
        w.save(update_fields=["ends_on"])
    record(contract, user, "resume_requested", by=role)
    sync(contract, today)
    planning.regenerate_future_shifts(contract, today, today)
    return EngagementContract.objects.get(pk=contract.pk)


@transaction.atomic
def give_notice(contract: EngagementContract, user, data: dict, *, expected_version=None, today: Optional[date] = None) -> EngagementContract:
    today = today or timezone.localdate()
    contract = EngagementContract.objects.select_for_update().get(pk=contract.pk)
    role = party_of(contract, user)
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    if contract.status not in ("active", "suspended"):
        raise conflict("not_noticeable", "Un préavis ne se donne que sur un contrat en cours.")
    check_version(contract, expected_version)
    v = Validator()
    last_day = v.date(data, "last_day", label="Dernier jour", required=True)
    reason = v.text(data, "reason", label="Motif", max_len=500, min_len=5, required=True)
    v.raise_if()
    minimum = today + timedelta(days=contract.notice_period_days)
    if last_day < minimum:
        raise EngagementError("invalid", f"Le préavis prévu au contrat est de {contract.notice_period_days} jours : dernier jour au plus tôt le {minimum:%d/%m/%Y}.", 400, fields={"last_day": "Préavis insuffisant."})
    if contract.end_date and last_day > contract.end_date:
        raise EngagementError("invalid", "Le préavis ne peut pas dépasser le terme du contrat.", 400, fields={"last_day": "Après le terme du contrat."})
    contract.status, contract.notice_given_by, contract.notice_given_at, contract.ends_on, contract.end_reason = "notice", user, timezone.now(), last_day, f"Préavis ({'prestataire' if role == 'worker' else 'donneur d’ordre'}) : {reason}"[:500]
    _touch(contract, "status", "notice_given_by", "notice_given_at", "ends_on", "end_reason")
    inst_svc.reconcile_end(contract, today)
    _cancel_future_occurrences(contract, last_day, user)
    record(contract, user, "notice_given", by=role, last_day=last_day, reason=reason)
    notify_role(contract, counterpart(role), "contract_notice", f"Préavis donné sur « {contract.title} » : fin le {last_day:%d/%m/%Y}.", title="Préavis reçu", key=f"notice-{contract.version}")
    return contract


@transaction.atomic
def declare_non_renewal(contract: EngagementContract, user, today: Optional[date] = None) -> EngagementContract:
    today = today or timezone.localdate()
    contract = EngagementContract.objects.select_for_update().get(pk=contract.pk)
    role = party_of(contract, user)
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    if contract.status not in LIVE or not contract.auto_renew or not contract.end_date:
        raise conflict("no_renewal", "Ce contrat n'a pas de renouvellement automatique à refuser.")
    if contract.non_renewal_at:
        return contract
    deadline = contract.end_date - timedelta(days=contract.notice_period_days)
    if today > deadline:
        raise conflict("too_late", f"Le non-renouvellement devait être signifié avant le {deadline:%d/%m/%Y} (préavis de {contract.notice_period_days} jours).")
    contract.non_renewal_by, contract.non_renewal_at = user, timezone.now()
    _touch(contract, "non_renewal_by", "non_renewal_at")
    record(contract, user, "non_renewal", by=role)
    notify_role(contract, counterpart(role), "contract_renewal", f"Non-renouvellement signifié sur « {contract.title} » : fin le {contract.end_date:%d/%m/%Y}.", title="Non-renouvellement", key="non-renewal")
    return contract


@transaction.atomic
def admin_decision(contract: EngagementContract, admin, action: str, reason: str, today: Optional[date] = None) -> EngagementContract:
    """Décision de la plateforme (litige, fraude) : suspension immédiate ou résiliation. Jamais de modification des montants."""
    today = today or timezone.localdate()
    contract = EngagementContract.objects.select_for_update().get(pk=contract.pk)
    reason = (reason or "").strip()[:500]
    if len(reason) < 5:
        raise EngagementError("invalid", "Un motif d'au moins 5 caractères est obligatoire.", 400, fields={"reason": "Motif obligatoire."})
    if action == "suspend":
        if contract.status not in ("active", "notice"):
            raise conflict("not_suspendable", "Seul un contrat en cours peut être suspendu.")
        ContractSuspension.objects.create(contract=contract, starts_on=today, ends_on=None, reason=reason, source="admin", created_by=admin)
        record(contract, admin, "admin_suspended", reason=reason)
        sync(contract, today)
    elif action == "resume":
        windows = [w for w in contract.suspensions.all() if w.source == "admin" and (w.ends_on is None or today < w.ends_on)]
        if not windows:
            raise conflict("not_suspended", "Aucune suspension de la plateforme à lever.")
        for w in windows:
            w.ends_on = max(today, w.starts_on)
            w.save(update_fields=["ends_on"])
        record(contract, admin, "admin_resumed", reason=reason)
        sync(contract, today)
    elif action == "terminate":
        if contract.status not in LIVE:
            raise conflict("not_terminable", "Ce contrat n'est pas en vigueur.")
        contract.ends_on, contract.end_reason = today, f"Décision de la plateforme : {reason}"[:500]
        _finish(contract, "terminated", reason, today, admin)
    else:
        raise EngagementError("invalid_action", "Décision inconnue.", 404)
    return EngagementContract.objects.get(pk=contract.pk)


@transaction.atomic
def close(contract: EngagementContract, user) -> EngagementContract:
    """Clôture : contrat terminé dont plus aucune échéance n'est due (ou abandonnée / annulée). Fixe la fin de l'historique financier."""
    contract = EngagementContract.objects.select_for_update().get(pk=contract.pk)
    if party_of(contract, user) is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    if contract.status not in ("terminated", "completed"):
        raise conflict("not_ended", "Seul un contrat terminé ou résilié peut être clôturé.")
    if contract.closed_at:
        return contract
    open_inst = [i for i in contract.installments.exclude(status__in=("waived", "cancelled", "paid", "on_hold")) if inst_svc.totals(i)["balance"] > 0]
    if open_inst:
        raise conflict("balance_due", f"{len(open_inst)} échéance(s) ont encore un solde : réglez-les ou faites-les abandonner avant la clôture.", open_installments=[i.sequence + 1 for i in open_inst])
    contract.closed_at = timezone.now()
    _touch(contract, "closed_at")
    record(contract, user, "closed")
    return contract
