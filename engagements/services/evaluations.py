"""Évaluations périodiques et finales d'un engagement, avec prévention des faux avis et des abus :
 - seules les deux parties d'un contrat RÉELLEMENT en cours (ou terminé) évaluent, jamais leur propre compte ;
 - ancienneté minimale du contrat, une évaluation par auteur et par période, intervalle minimal entre deux périodiques ;
 - la finale n'existe qu'après la fin du contrat, dans les 60 jours ; plafond d'évaluations par jour et par auteur ;
 - pas de lien, de numéro de téléphone ni d'adresse e-mail dans un commentaire (démarchage, hameçonnage) ;
 - modification possible quelques jours seulement, réponse unique de la personne évaluée, signalement et masquage motivé."""
import re
from datetime import date, timedelta
from typing import Optional

from django.db import transaction
from django.db.models import Avg, Count
from django.utils import timezone

from engagements.models import EngagementContract, EngagementEvaluation, EvaluationReport
from engagements.rules import rules_for
from engagements.services.common import EngagementError, conflict, counterpart, notify_role, party_of, principal_side, record
from engagements.services.validation import Validator

CRITERIA = ("quality", "punctuality", "communication", "respect")
DAILY_LIMIT = 5
FINAL_WINDOW_DAYS = 60
MIN_PUBLIC_COUNT = 3
SUSPICIOUS = re.compile(r"(https?://|www\.|[\w.+-]+@[\w-]+\.[\w.]+|(?:\+?\d[\d .-]{7,}\d))", re.I)


def _subject(contract: EngagementContract, role: str):
    return contract.principal if role == "worker" else contract.worker


@transaction.atomic
def create(contract: EngagementContract, user, data: dict, today: Optional[date] = None) -> EngagementEvaluation:
    today = today or timezone.localdate()
    contract = EngagementContract.objects.select_for_update(of=("self",)).select_related("worker", "principal").get(pk=contract.pk)
    role = party_of(contract, user)
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    if contract.activated_at is None:
        raise conflict("not_started", "Le contrat n'a jamais commencé : rien à évaluer.")
    rules = rules_for(contract.category_id)
    v = Validator()
    kind = v.choice(data, "kind", label="Type", allowed={"periodic", "final"})
    rating = v.integer(data, "rating", label="Note", lo=1, hi=5)
    comment = v.text(data, "comment", label="Commentaire", max_len=2000)
    if rating is None:
        v.err("rating", "Note : entier de 1 à 5 obligatoire.")
    if comment and SUSPICIOUS.search(comment):
        v.err("comment", "Pas de lien, d'adresse e-mail ni de numéro de téléphone dans un commentaire.")
    raw_criteria = data.get("criteria") or {}
    criteria = {}
    if isinstance(raw_criteria, dict):
        for key, val in raw_criteria.items():
            if key not in CRITERIA:
                v.err("criteria", "Critère inconnu.")
                break
            try:
                score = int(val)
            except (TypeError, ValueError):
                v.err("criteria", "Chaque critère est noté de 1 à 5.")
                break
            if not 1 <= score <= 5:
                v.err("criteria", "Chaque critère est noté de 1 à 5.")
                break
            criteria[key] = score
    v.raise_if()
    if kind == "periodic":
        if contract.status not in ("active", "notice", "suspended"):
            raise conflict("not_live", "Une évaluation périodique se fait pendant le contrat.")
        if (today - contract.activated_at.date()).days < rules.min_days_for_evaluation:
            raise conflict("too_early", f"Le contrat doit durer au moins {rules.min_days_for_evaluation} jours avant une première évaluation.")
        last = contract.evaluations.filter(author=user, kind="periodic").order_by("-created_at").first()
        if last is not None and (today - timezone.localtime(last.created_at).date()).days < rules.evaluation_interval_days:
            raise conflict("too_soon", f"Une évaluation périodique tous les {rules.evaluation_interval_days} jours au plus.")
        period_key = f"{today:%Y-%m}"
    else:
        if contract.status not in ("terminated", "completed") or contract.ended_at is None:
            raise conflict("not_ended", "L'évaluation finale se fait après la fin du contrat.")
        if (today - timezone.localtime(contract.ended_at).date()).days > FINAL_WINDOW_DAYS:
            raise conflict("window_closed", f"L'évaluation finale se fait dans les {FINAL_WINDOW_DAYS} jours suivant la fin du contrat.")
        period_key = "final"
    if EngagementEvaluation.objects.filter(contract=contract, author=user, kind=kind, period_key=period_key).exists():
        raise conflict("already_evaluated", "Vous avez déjà évalué cette période.")
    if EngagementEvaluation.objects.filter(author=user, created_at__gte=timezone.now() - timedelta(hours=24)).count() >= DAILY_LIMIT:
        raise conflict("rate_limited", "Trop d'évaluations en 24 heures : réessayez demain.")
    subject = _subject(contract, role)
    ev = EngagementEvaluation.objects.create(contract=contract, author=user, subject=subject, kind=kind, period_key=period_key, rating=rating, criteria=criteria, comment=comment,
                                             edit_until=timezone.now() + timedelta(days=rules.evaluation_edit_days))
    record(contract, user, "evaluation_created", kind=kind, evaluation=ev.pk)
    notify_role(contract, counterpart(role), "evaluation_received", f"Vous avez reçu une évaluation ({rating}/5) sur « {contract.title} ».", title="Évaluation reçue", key=f"eval-{ev.pk}")
    return ev


@transaction.atomic
def update(ev: EngagementEvaluation, user, data: dict) -> EngagementEvaluation:
    ev = EngagementEvaluation.objects.select_for_update().get(pk=ev.pk)
    if ev.author_id != user.id:
        raise EngagementError("forbidden", "Seul l'auteur modifie son évaluation.", 403)
    if timezone.now() > ev.edit_until:
        raise conflict("locked", "Le délai de modification est dépassé.")
    if ev.is_hidden:
        raise conflict("hidden", "Cette évaluation a été masquée par la plateforme.")
    v = Validator()
    rating = v.integer(data, "rating", label="Note", lo=1, hi=5, default=ev.rating)
    comment = v.text(data, "comment", label="Commentaire", max_len=2000, default=ev.comment)
    if comment and SUSPICIOUS.search(comment):
        v.err("comment", "Pas de lien, d'adresse e-mail ni de numéro de téléphone dans un commentaire.")
    v.raise_if()
    ev.rating, ev.comment = rating, comment
    ev.save(update_fields=["rating", "comment"])
    return ev


@transaction.atomic
def reply(ev: EngagementEvaluation, user, text: str) -> EngagementEvaluation:
    ev = EngagementEvaluation.objects.select_for_update().get(pk=ev.pk)
    if ev.subject_id != user.id:
        raise EngagementError("forbidden", "Seule la personne évaluée peut répondre.", 403)
    if ev.reply:
        raise conflict("already_replied", "Une réponse existe déjà.")
    v = Validator()
    value = v.text({"reply": text}, "reply", label="Réponse", max_len=1000, min_len=2, required=True)
    if SUSPICIOUS.search(value):
        v.err("reply", "Pas de lien, d'adresse e-mail ni de numéro de téléphone.")
    v.raise_if()
    ev.reply, ev.reply_at = value, timezone.now()
    ev.save(update_fields=["reply", "reply_at"])
    return ev


@transaction.atomic
def report(ev: EngagementEvaluation, user, reason: str) -> EvaluationReport:
    if ev.subject_id != user.id and ev.author_id != user.id and party_of(ev.contract, user) is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    reason = (reason or "").strip()[:500]
    if len(reason) < 5:
        raise EngagementError("invalid", "Indiquez le motif du signalement.", 400, fields={"reason": "Motif obligatoire."})
    obj, _ = EvaluationReport.objects.get_or_create(evaluation=ev, reporter=user, defaults={"reason": reason})
    return obj


def summary_for(user) -> dict:
    """Moyenne et nombre d'évaluations VISIBLES reçues ; la moyenne n'est publiée qu'à partir de 3 évaluations."""
    agg = EngagementEvaluation.objects.filter(subject=user, is_hidden=False).aggregate(n=Count("id"), avg=Avg("rating"))
    return {"count": agg["n"], "average": round(agg["avg"], 2) if agg["n"] >= MIN_PUBLIC_COUNT and agg["avg"] is not None else None, "min_public": MIN_PUBLIC_COUNT}
