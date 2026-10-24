"""Modèles de contrat : édition (brouillon), soumission à la revue juridique, validation HUMAINE, retrait, nouvelle version.

Garde-fous :
 - un modèle validé ou retiré n'est jamais modifié (ses contrats en gardent le texte exact) : on crée une nouvelle version ;
 - la validation exige le droit « contracts.legal_review » (Back-Office), une note de revue, et le nom du juriste ou de l'organisme
   qui a revu le texte ; elle est journalisée (audit) ; le libellé reste « Validé par revue juridique », jamais « conforme » ;
 - seul un modèle validé est choisi pour un contrat : le plus récent du métier (ou de son métier parent), sinon le modèle général de
   la même nature de relation (salarié / indépendant)."""
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from engagements import legal
from engagements.models import ContractTemplate
from engagements.services.common import EngagementError, conflict
from handy.models import ServiceCategory


def _clean(data: dict, instance: Optional[ContractTemplate] = None) -> dict:
    title = str(data.get("title", instance.title if instance else "") or "").strip()
    relationship = data.get("relationship", instance.relationship if instance else "")
    articles = data.get("articles", instance.articles if instance else [])
    references = data.get("legal_references", instance.legal_references if instance else [])
    errors = {}
    if not 5 <= len(title) <= 160:
        errors["title"] = "Titre : 5 à 160 caractères."
    if relationship not in ("employment", "independent"):
        errors["relationship"] = "Nature : « employment » (salarié) ou « independent » (prestation)."
    problems = legal.validate_articles(articles)
    if problems:
        errors["articles"] = " ".join(problems)
    if not isinstance(references, list) or any(not isinstance(r, dict) or not str(r.get("label", "")).strip() for r in references):
        errors["legal_references"] = "Références : liste d'objets {label, citation, status}."
    if errors:
        raise EngagementError("invalid", "Modèle incomplet.", 400, fields=errors)
    clean_articles = [{"number": int(a.get("number") or i + 1), "key": str(a.get("key") or f"article_{i + 1}")[:40],
                       "title": str(a["title"]).strip()[:160], "body": str(a["body"]).strip()[:6000],
                       "categories": [str(c)[:60] for c in (a.get("categories") or [])]} for i, a in enumerate(articles)]
    clean_refs = [{"label": str(r["label"])[:160], "citation": str(r.get("citation") or legal.TO_COMPLETE)[:300],
                   "status": str(r.get("status") or "à confirmer par la revue juridique")[:300]} for r in references]
    return {"title": title, "relationship": relationship, "articles": clean_articles, "legal_references": clean_refs}


@transaction.atomic
def create(user, data: dict) -> ContractTemplate:
    import re

    code = str(data.get("code") or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,58}", code):
        raise EngagementError("invalid", "Code : lettres minuscules, chiffres et tirets.", 400, fields={"code": "Code invalide."})
    if ContractTemplate.objects.filter(code=code).exists():
        raise conflict("code_exists", "Ce code existe déjà : créez une nouvelle version du modèle.")
    t = ContractTemplate.objects.create(code=code, created_by=user, **_clean(data))
    _set_categories(t, data.get("categories"))
    return t


def _set_categories(t: ContractTemplate, ids) -> None:
    if ids is not None:
        t.categories.set(ServiceCategory.objects.filter(pk__in=[int(i) for i in ids if str(i).isdigit()]))


@transaction.atomic
def update(t: ContractTemplate, user, data: dict) -> ContractTemplate:
    t = ContractTemplate.objects.select_for_update().get(pk=t.pk)
    if t.status not in (ContractTemplate.DRAFT, ContractTemplate.TO_REVIEW):
        raise conflict("frozen", "Un modèle validé ou retiré ne se modifie plus : créez une nouvelle version.")
    for field, value in _clean(data, t).items():
        setattr(t, field, value)
    t.status = ContractTemplate.DRAFT          # tout changement repart en brouillon : la revue porte sur le texte exact
    t.save()
    _set_categories(t, data.get("categories"))
    return t


@transaction.atomic
def submit(t: ContractTemplate, user) -> ContractTemplate:
    t = ContractTemplate.objects.select_for_update().get(pk=t.pk)
    if t.status != ContractTemplate.DRAFT:
        raise conflict("not_draft", "Seul un brouillon peut être soumis à la revue juridique.")
    t.status = ContractTemplate.TO_REVIEW
    t.save(update_fields=["status", "updated_at"])
    return t


@transaction.atomic
def validate(t: ContractTemplate, reviewer, *, reviewed_by_name: str, note: str) -> ContractTemplate:
    """Validation HUMAINE après revue par un juriste : le texte exact soumis devient utilisable pour les contrats."""
    from trust.models import audit

    t = ContractTemplate.objects.select_for_update().get(pk=t.pk)
    if t.status != ContractTemplate.TO_REVIEW:
        raise conflict("not_to_review", "Seul un modèle « À valider juridiquement » peut être validé.")
    name, note = (reviewed_by_name or "").strip(), (note or "").strip()
    if len(name) < 3 or len(note) < 10:
        raise EngagementError("invalid", "Indiquez le juriste (ou l'organisme) ayant revu le modèle et une note de revue.", 400,
                              fields={"reviewed_by_name": "Obligatoire.", "note": "10 caractères au moins."})
    if legal.TO_COMPLETE in str(t.articles) or legal.TO_COMPLETE in str(t.legal_references):
        raise conflict("incomplete", "Des emplacements « À compléter par la revue juridique » restent dans le modèle : complétez-les d'abord.")
    t.status, t.reviewed_by, t.reviewed_at = ContractTemplate.VALIDATED, reviewer, timezone.now()
    t.review_note = f"Revu par : {name[:200]}. {note[:1700]}"
    t.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"])
    audit("contract_template.validated", actor=reviewer, target_type="contract_template", target_id=t.pk, code=t.code, version=t.version,
          reviewed_by_name=name[:200])
    return t


@transaction.atomic
def retire(t: ContractTemplate, user) -> ContractTemplate:
    from trust.models import audit

    t = ContractTemplate.objects.select_for_update().get(pk=t.pk)
    if t.status != ContractTemplate.RETIRED:
        t.status = ContractTemplate.RETIRED
        t.save(update_fields=["status", "updated_at"])
        audit("contract_template.retired", actor=user, target_type="contract_template", target_id=t.pk, code=t.code, version=t.version)
    return t


@transaction.atomic
def new_version(t: ContractTemplate, user) -> ContractTemplate:
    """Copie de travail (brouillon) d'un modèle, version suivante ; l'ancienne version reste intacte et sert encore à ses contrats."""
    last = ContractTemplate.objects.filter(code=t.code).order_by("-version").first()
    copy = ContractTemplate.objects.create(code=t.code, version=last.version + 1, title=t.title, relationship=t.relationship, articles=t.articles,
                                           legal_references=t.legal_references, previous=t, created_by=user)
    copy.categories.set(t.categories.all())
    return copy


def template_for(relationship: str, category: Optional[ServiceCategory]) -> Optional[ContractTemplate]:
    """Modèle VALIDÉ le plus adapté : celui du métier (ou de son métier parent), sinon le général ; la version la plus récente."""
    qs = ContractTemplate.objects.filter(status=ContractTemplate.VALIDATED, relationship=relationship)
    if category is not None:
        ids = [category.pk] + ([category.parent_id] if category.parent_id else [])
        specific = qs.filter(categories__in=ids).order_by("-reviewed_at", "-version").first()
        if specific is not None:
            return specific
    return qs.filter(categories__isnull=True).order_by("-reviewed_at", "-version").first()


def check_usable(t: ContractTemplate, relationship: str, category: Optional[ServiceCategory]) -> None:
    if t.status != ContractTemplate.VALIDATED:
        raise EngagementError("template_not_validated", "Ce modèle n'est pas validé juridiquement : il ne peut pas servir à un contrat.", 400,
                              fields={"template": "Modèle non validé."})
    if t.relationship != relationship:
        raise EngagementError("template_mismatch", "Ce modèle ne correspond pas à la nature du contrat (salarié / indépendant).", 400,
                              fields={"template": "Nature différente."})
    if category is not None and t.categories.exists() and not t.categories.filter(Q(pk=category.pk) | Q(pk=category.parent_id)).exists():
        raise EngagementError("template_mismatch", "Ce modèle n'est pas prévu pour ce métier.", 400, fields={"template": "Métier différent."})
