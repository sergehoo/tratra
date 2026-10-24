"""Besoins publiés, candidatures et entretiens.

 - un besoin n'est visible des professionnels qu'une fois publié ; seuls les artisans VÉRIFIÉS (KYC approuvé, compte actif)
   peuvent y candidater (règle d'éligibilité existante, source unique) ;
 - aucune coordonnée personnelle n'est échangée : les entretiens se fixent dans Tratra ;
 - toute décision est notifiée et horodatée."""
from datetime import date, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from engagements.models import EngagementApplication, EngagementInterview, EngagementInvitation, EngagementPosting
from engagements.rules import rules_for
from engagements.services.common import EngagementError, conflict, organization_actor, public_name, require_eligible_worker
from engagements.services.validation import Validator, check_common_terms, derived_hours, PERIODS, MISSION_TYPES, RELATIONSHIPS
from handy.models import ServiceCategory
from handy.notifications import notify

EDITABLE = ("draft", "open")


def posting_side(posting: EngagementPosting, user) -> bool:
    """Publication gérée par son auteur, ou par un membre autorisé de l'organisation."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if posting.organization_id:
        return organization_actor(user, posting.organization_id)        # besoin d'organisation : adhésion active et habilitée uniquement
    return posting.publisher_id == user.id


def _clean(data: dict, *, instance: Optional[EngagementPosting] = None, today: Optional[date] = None) -> dict:
    today = today or timezone.localdate()
    v = Validator()
    merged = {**({f: getattr(instance, f) for f in ("title", "description", "mission_type", "work_relationship", "city", "location_note", "start_date",
                                                      "end_date", "schedule", "hours_per_week", "amount", "period", "conditions", "employment_notice_ack",
                                                      "application_deadline", "benefits", "duration_months")} if instance else {}), **data}
    category = None
    category_id = data.get("category") or (instance.category_id if instance else None)
    if category_id:
        category = ServiceCategory.objects.filter(pk=category_id, is_active=True).first()
    if category is None:
        v.err("category", "Catégorie : choix obligatoire.")
    out = {
        "title": v.text(merged, "title", label="Titre", max_len=160, min_len=5, required=True),
        "description": v.text(merged, "description", label="Description", max_len=4000, min_len=20, required=True),
        "mission_type": v.choice(merged, "mission_type", label="Type de mission", allowed=MISSION_TYPES),
        "work_relationship": v.choice(merged, "work_relationship", label="Nature de la relation", allowed=RELATIONSHIPS, default="independent"),
        "city": v.text(merged, "city", label="Ville", max_len=100, required=True),
        "location_note": v.text(merged, "location_note", label="Zone", max_len=200),
        "start_date": v.date(merged, "start_date", label="Début souhaité"),
        "end_date": v.date(merged, "end_date", label="Fin souhaitée"),
        "schedule": v.schedule(merged),
        "amount": v.amount(merged, "amount", label="Rémunération", required=True),
        "period": v.choice(merged, "period", label="Période de rémunération", allowed=PERIODS, default="monthly"),
        "conditions": v.text(merged, "conditions", label="Conditions", max_len=4000),
        "benefits": v.text(merged, "benefits", label="Avantages", max_len=2000),
        "duration_months": v.integer(merged, "duration_months", label="Durée (mois)", lo=1, hi=240),
        "employment_notice_ack": bool(merged.get("employment_notice_ack")),
        "application_deadline": v.date(merged, "application_deadline", label="Date limite de candidature"),
    }
    out["hours_per_week"] = derived_hours(out["schedule"], merged.get("hours_per_week"))
    if out["start_date"] and out["start_date"] < today:
        v.err("start_date", "Le début souhaité ne peut pas être dans le passé.")
    if out["application_deadline"] and out["application_deadline"] < today:
        v.err("application_deadline", "La date limite ne peut pas être dans le passé.")
    if category is not None:
        check_common_terms(v, rules=rules_for(category), mission_type=out["mission_type"], relationship=out["work_relationship"], start=out["start_date"],
                           end=out["end_date"], ack=out["employment_notice_ack"])
    v.raise_if()
    out["category"] = category
    return out


@transaction.atomic
def create_posting(user, data: dict, *, today: Optional[date] = None) -> EngagementPosting:
    organization_id = data.get("organization") or None
    if organization_id and not organization_actor(user, organization_id):
        raise EngagementError("organization_forbidden", "Vous ne pouvez pas publier au nom de cette organisation.", 403)
    cleaned = _clean(data, today=today)
    return EngagementPosting.objects.create(publisher=user, organization_id=organization_id, **cleaned)


@transaction.atomic
def update_posting(posting: EngagementPosting, user, data: dict, *, expected_version: Optional[int] = None, today: Optional[date] = None) -> EngagementPosting:
    posting = EngagementPosting.objects.select_for_update().get(pk=posting.pk)
    if not posting_side(posting, user):
        raise EngagementError("forbidden", "Ce besoin ne vous appartient pas.", 403)
    if posting.status not in EDITABLE:
        raise conflict("not_editable", "Un besoin clôturé ou pourvu n'est plus modifiable.")
    if expected_version is not None and int(expected_version) != posting.version:
        raise conflict("version_conflict", "Ce besoin a été modifié entre-temps : rechargez-le.", current_version=posting.version)
    cleaned = _clean({k: v for k, v in data.items() if k not in ("organization", "status")}, instance=posting, today=today)
    for field, value in cleaned.items():
        setattr(posting, field, value)
    posting.version += 1
    posting.save()
    return posting


@transaction.atomic
def publish(posting: EngagementPosting, user) -> EngagementPosting:
    posting = EngagementPosting.objects.select_for_update().get(pk=posting.pk)
    if not posting_side(posting, user):
        raise EngagementError("forbidden", "Ce besoin ne vous appartient pas.", 403)
    if posting.status == "open":
        return posting
    if posting.status != "draft":
        raise conflict("not_publishable", "Seul un brouillon peut être publié.")
    _clean({}, instance=posting)  # revalide avec les règles du moment
    posting.status, posting.published_at = "open", timezone.now()
    posting.version += 1
    posting.save(update_fields=["status", "published_at", "version", "updated_at"])
    return posting


@transaction.atomic
def close_posting(posting: EngagementPosting, user, *, filled: bool = False, cancel: bool = False) -> EngagementPosting:
    posting = EngagementPosting.objects.select_for_update().get(pk=posting.pk)
    if not posting_side(posting, user):
        raise EngagementError("forbidden", "Ce besoin ne vous appartient pas.", 403)
    if posting.status in ("closed", "filled", "cancelled", "expired"):
        return posting
    posting.status = "cancelled" if cancel else ("filled" if filled else "closed")
    posting.closed_at = timezone.now()
    posting.version += 1
    posting.save(update_fields=["status", "closed_at", "version", "updated_at"])
    return posting


def expire_due(today: Optional[date] = None) -> int:
    today = today or timezone.localdate()
    now = timezone.now()
    return EngagementPosting.objects.filter(status="open", application_deadline__lt=today).update(status="expired", closed_at=now)


# ── Candidatures ────────────────────────────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def apply(posting: EngagementPosting, user, data: dict) -> EngagementApplication:
    posting = EngagementPosting.objects.select_for_update().get(pk=posting.pk)
    if posting.status != "open":
        raise conflict("posting_closed", "Ce besoin n'accepte plus de candidatures.")
    if posting_side(posting, user):
        raise EngagementError("own_posting", "Vous ne pouvez pas candidater à votre propre besoin.", 403)
    require_eligible_worker(user, "Seuls les artisans vérifiés (identité approuvée) peuvent candidater.")
    v = Validator()
    message = v.text(data, "message", label="Message", max_len=2000)
    proposed = v.amount(data, "proposed_amount", label="Montant proposé")
    available = v.date(data, "available_from", label="Disponibilité")
    v.raise_if()
    existing = EngagementApplication.objects.filter(posting=posting, applicant=user).first()
    if existing is not None:
        if existing.status == "withdrawn":
            raise conflict("already_applied", "Vous avez retiré votre candidature : elle ne peut pas être renvoyée.")
        raise conflict("already_applied", "Vous avez déjà candidaté à ce besoin.", application_id=existing.pk)
    app = EngagementApplication.objects.create(posting=posting, applicant=user, message=message, proposed_amount=proposed, available_from=available)
    notify(posting.publisher, "engagement_application", f"{public_name(user)} candidate à « {posting.title} ».", title="Nouvelle candidature",
           data={"kind": "posting", "id": posting.pk}, dedupe_key=f"eng-app:{app.pk}")
    return app


def _publisher_guard(app: EngagementApplication, user) -> EngagementPosting:
    if not posting_side(app.posting, user):
        raise EngagementError("forbidden", "Cette candidature ne concerne pas vos besoins.", 403)
    return app.posting


@transaction.atomic
def decide(app: EngagementApplication, user, decision: str, note: str = "") -> EngagementApplication:
    """Présélectionner, refuser ou retenir (publication) — le candidat est notifié."""
    app = EngagementApplication.objects.select_for_update(of=("self",)).select_related("posting", "applicant").get(pk=app.pk)
    posting = _publisher_guard(app, user)
    if decision not in ("shortlist", "reject", "select"):
        raise EngagementError("invalid_decision", "Décision inconnue.")
    if app.status in ("withdrawn", "rejected") or (app.status == "selected" and decision != "reject"):
        raise conflict("not_open", "Cette candidature est déjà close.")
    target = {"shortlist": "shortlisted", "reject": "rejected", "select": "selected"}[decision]
    if decision == "select" and posting.status not in ("open", "closed"):
        raise conflict("posting_closed", "Ce besoin n'est plus en cours.")
    app.status, app.decision_note, app.decided_at = target, (note or "")[:500], timezone.now()
    app.save(update_fields=["status", "decision_note", "decided_at", "updated_at"])
    text = {"shortlisted": "présélectionnée", "rejected": "refusée", "selected": "retenue"}[target]
    ntype = "engagement_selected" if target == "selected" else "engagement_application"
    notify(app.applicant, ntype, f"Votre candidature à « {posting.title} » est {text}.", title=f"Candidature {text}",
           data={"kind": "posting", "id": posting.pk}, dedupe_key=f"eng-app:{app.pk}:{target}")
    return app


@transaction.atomic
def withdraw(app: EngagementApplication, user) -> EngagementApplication:
    app = EngagementApplication.objects.select_for_update().get(pk=app.pk)
    if app.applicant_id != user.id:
        raise EngagementError("forbidden", "Cette candidature n'est pas la vôtre.", 403)
    if app.status not in EngagementApplication.OPEN:
        raise conflict("not_open", "Cette candidature ne peut plus être retirée.")
    app.status, app.decided_at = "withdrawn", timezone.now()
    app.save(update_fields=["status", "decided_at", "updated_at"])
    return app


# ── Entretiens ──────────────────────────────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def propose_interview(app: EngagementApplication, user, data: dict) -> EngagementInterview:
    app = EngagementApplication.objects.select_for_update(of=("self",)).select_related("posting", "applicant").get(pk=app.pk)
    publisher = posting_side(app.posting, user)
    if not publisher and app.applicant_id != user.id:
        raise EngagementError("forbidden", "Cette candidature ne vous concerne pas.", 403)
    if app.status not in EngagementApplication.OPEN:
        raise conflict("not_open", "Cette candidature est close.")
    v = Validator()
    when = data.get("scheduled_at")
    from django.utils.dateparse import parse_datetime
    moment = parse_datetime(str(when)) if when else None
    if moment is None:
        v.err("scheduled_at", "Date et heure de l'entretien : valeur invalide.")
    else:
        if timezone.is_naive(moment):
            moment = timezone.make_aware(moment)
        if moment <= timezone.now():
            v.err("scheduled_at", "L'entretien doit être dans le futur.")
        if moment > timezone.now() + timedelta(days=120):
            v.err("scheduled_at", "L'entretien ne peut pas être fixé au-delà de 120 jours.")
    duration = v.integer(data, "duration_minutes", label="Durée", lo=5, hi=480, default=30)
    mode = v.choice(data, "mode", label="Mode", allowed={k for k, _ in EngagementInterview.MODES}, default="phone")
    place = v.text(data, "place_note", label="Lieu ou lien", max_len=200)
    note = v.text(data, "note", label="Note", max_len=500)
    v.raise_if()
    interview = EngagementInterview.objects.create(application=app, proposed_by=user, scheduled_at=moment, duration_minutes=duration, mode=mode,
                                                   place_note=place, note=note)
    if app.status in ("submitted", "shortlisted"):
        app.status = "interview"
        app.save(update_fields=["status", "updated_at"])
    other = app.applicant if publisher else app.posting.publisher
    notify(other, "engagement_interview", f"Entretien proposé le {moment:%d/%m/%Y à %Hh%M} pour « {app.posting.title} ».", title="Entretien proposé",
           data={"kind": "posting", "id": app.posting_id}, dedupe_key=f"eng-int:{interview.pk}:proposed")
    return interview


@transaction.atomic
def respond_interview(interview: EngagementInterview, user, op: str) -> EngagementInterview:
    interview = EngagementInterview.objects.select_for_update(of=("self",)).select_related("application", "application__posting", "application__applicant").get(pk=interview.pk)
    app = interview.application
    publisher = posting_side(app.posting, user)
    if not publisher and app.applicant_id != user.id:
        raise EngagementError("forbidden", "Cet entretien ne vous concerne pas.", 403)
    proposer_is_publisher = posting_side(app.posting, interview.proposed_by)
    if op in ("confirm", "decline"):
        responder_ok = (app.applicant_id == user.id) if proposer_is_publisher else publisher
        if not responder_ok:
            raise EngagementError("forbidden", "C'est à l'autre partie de répondre à cette proposition.", 403)
        if interview.status != "proposed":
            raise conflict("not_open", "Cette proposition a déjà reçu une réponse.")
        interview.status = "confirmed" if op == "confirm" else "declined"
    elif op == "cancel":
        if interview.status not in ("proposed", "confirmed"):
            raise conflict("not_open", "Cet entretien ne peut plus être annulé.")
        interview.status = "cancelled"
    elif op == "done":
        if not publisher:
            raise EngagementError("forbidden", "Seul le publicateur marque un entretien comme effectué.", 403)
        if interview.status != "confirmed":
            raise conflict("not_open", "Seul un entretien confirmé peut être marqué comme effectué.")
        interview.status = "done"
    else:
        raise EngagementError("invalid_action", "Opération inconnue.", 404)
    interview.save(update_fields=["status"])
    other = app.applicant if publisher else app.posting.publisher
    label = {"confirm": "confirmé", "decline": "refusé", "cancel": "annulé", "done": "effectué"}[op]
    if op != "done":
        notify(other, "engagement_interview", f"Entretien {label} pour « {app.posting.title} ».", title=f"Entretien {label}",
               data={"kind": "posting", "id": app.posting_id}, dedupe_key=f"eng-int:{interview.pk}:{op}")
    return interview


# ── Invitations : le donneur d'ordre invite un professionnel vérifié à candidater ─────────────────────────────────────

@transaction.atomic
def invite(posting: EngagementPosting, user, invitee_id, message: str = "") -> EngagementInvitation:
    from django.contrib.auth import get_user_model

    posting = EngagementPosting.objects.select_for_update().get(pk=posting.pk)
    if not posting_side(posting, user):
        raise EngagementError("not_found", "Besoin introuvable.", 404)
    if posting.status != "open":
        raise conflict("posting_closed", "Publiez le besoin avant d'inviter des professionnels.")
    invitee = get_user_model().objects.filter(pk=invitee_id, is_active=True).select_related("handyman_profile").first()
    if invitee is None or invitee.pk == user.pk:
        raise EngagementError("invalid", "Professionnel introuvable.", 400, fields={"invitee": "Choisissez un professionnel vérifié."})
    require_eligible_worker(invitee, "Seuls les professionnels vérifiés peuvent être invités.")
    v = Validator()
    message = v.text({"message": message}, "message", label="Message", max_len=500)
    v.raise_if()
    if EngagementApplication.objects.filter(posting=posting, applicant=invitee).exists():
        raise conflict("already_applied", "Ce professionnel a déjà candidaté à ce besoin.")
    invitation, created = EngagementInvitation.objects.get_or_create(posting=posting, invitee=invitee,
                                                                     defaults={"invited_by": user, "message": message})
    if not created:
        raise conflict("already_invited", "Ce professionnel est déjà invité.", invitation_id=invitation.pk)
    notify(invitee, "engagement_application", f"{public_name(user)} vous invite à candidater : « {posting.title} ».", title="Invitation à candidater",
           data={"kind": "posting", "id": posting.pk}, dedupe_key=f"eng-invite:{invitation.pk}")
    return invitation


@transaction.atomic
def respond_invitation(invitation: EngagementInvitation, user, accept_it: bool, data: Optional[dict] = None) -> EngagementInvitation:
    invitation = EngagementInvitation.objects.select_for_update().select_related("posting").get(pk=invitation.pk)
    if invitation.invitee_id != user.id:
        raise EngagementError("not_found", "Invitation introuvable.", 404)
    if invitation.status != "sent":
        raise conflict("not_open", "Cette invitation a déjà reçu une réponse.")
    if accept_it:
        invitation.application = apply(invitation.posting, user, data or {})      # mêmes contrôles qu'une candidature spontanée
    invitation.status, invitation.responded_at = ("accepted" if accept_it else "declined"), timezone.now()
    invitation.save(update_fields=["status", "responded_at", "application"])
    if not accept_it:
        notify(invitation.invited_by, "engagement_application", f"{public_name(user)} décline votre invitation pour « {invitation.posting.title} ».",
               title="Invitation déclinée", data={"kind": "posting", "id": invitation.posting_id}, dedupe_key=f"eng-invite-no:{invitation.pk}")
    return invitation


@transaction.atomic
def cancel_invitation(invitation: EngagementInvitation, user) -> EngagementInvitation:
    invitation = EngagementInvitation.objects.select_for_update().select_related("posting").get(pk=invitation.pk)
    if not posting_side(invitation.posting, user):
        raise EngagementError("not_found", "Invitation introuvable.", 404)
    if invitation.status == "sent":
        invitation.status, invitation.responded_at = "cancelled", timezone.now()
        invitation.save(update_fields=["status", "responded_at"])
    return invitation
