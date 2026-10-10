"""Passeport professionnel Tratra Trust : fiche de confiance publique + vue détaillée du propriétaire.

Tout vient de données réelles. Chaque information porte sa provenance :
- « vérifié »    : décision de l'équipe Tratra (KYC, justificatifs approuvés) ;
- « plateforme » : activité observée sur Tratra (missions, avis, ponctualité, réactivité) ;
- « déclaré »    : saisi par l'artisan, non vérifié (spécialités, années d'expérience).
La version publique n'expose ni document, ni email, ni téléphone, ni position, ni motif de retrait.
"""
from typing import Dict

from django.utils import timezone

from handy.api.serializers import absolute_media_url, public_display_name
from handy.eligibility import profile_checklist
from handy.models import HandymanDocument
from trust import engine, metrics
from trust.models import BadgeAward, TrustConfig

SOURCES = {
    "vérifié": "Contrôlé par l'équipe Tratra (pièce d'identité, justificatifs).",
    "plateforme": "Mesuré à partir de l'activité réelle sur Tratra.",
    "déclaré": "Renseigné par l'artisan, non vérifié.",
}


def badge_payload(award) -> Dict:
    return {"code": award.code, "label": BadgeAward.LABELS[award.code], "since": award.started_at}


def badges_of(profile) -> list:
    """Badges ACTUELS (lecture du champ dénormalisé : aucune requête supplémentaire en liste)."""
    return [{"code": c, "label": BadgeAward.LABELS[c]} for c in (profile.trust_badges or []) if c in BadgeAward.LABELS]


def _kyc_verified_on(profile):
    doc = (HandymanDocument.objects.filter(handyman=profile, document_type__in=sorted(profile.REQUIRED_KYC_DOCS),
                                           status="approved").order_by("-reviewed_at").first())
    return doc.reviewed_at if doc else None


def _certifications(profile) -> list:
    return [{"id": d.id, "title": d.title or (d.category.name if d.category_id else "Justificatif professionnel"),
             "category": ({"id": d.category_id, "name": d.category.name} if d.category_id else None),
             "issuer": d.issuer or "", "issued_on": d.issued_on, "expires_on": d.expires_on, "source": "vérifié"}
            for d in metrics.certifications(profile)]


def _declared_skills(profile) -> list:
    return [{"id": c.id, "name": c.name, "slug": c.slug, "source": "déclaré"} for c in profile.skills.all()]


def _history(profile, *, detailed: bool) -> list:
    rows = []
    for a in profile.badge_awards.exclude(code=BadgeAward.NOUVEAU).order_by("-started_at"):
        item = {"code": a.code, "label": BadgeAward.LABELS[a.code], "started_at": a.started_at, "ended_at": a.ended_at}
        if detailed:
            item.update(start_reason=a.start_reason, end_reason=a.end_reason)
        rows.append(item)
    return rows


def build(profile, *, request=None, owner: bool = False, config=None) -> Dict:
    """Passeport complet. `owner=True` ajoute les critères restants pour EXPERT/SUR, la liste de contrôle du
    dossier, l'historique motivé et les justificatifs en attente ; jamais de document ni de fichier."""
    config = config or TrustConfig.get_solo()
    m = metrics.collect(profile, config)
    score = engine.trust_score(m, config)
    active = {a.code: a for a in profile.badge_awards.filter(ended_at__isnull=True)}
    reviews = m["reviews"]
    data = {
        "profile_id": profile.id,
        "display_name": public_display_name(profile.user),
        "photo": absolute_media_url(request, profile.photo),
        "commune": profile.commune,
        "member_since": profile.user.date_joined,
        "evaluated_at": profile.trust_evaluated_at,
        "identity": {"verified": m["verified"], "verified_on": _kyc_verified_on(profile) if m["verified"] else None,
                     "source": "vérifié"},
        "badges": [badge_payload(active[c]) for c in BadgeAward.ORDER if c in active],
        "score": {"value": score["score"], "confidence": score["confidence"], "reason": score["reason"],
                  "note": score["note"],
                  "components": [{k: v for k, v in c.items() if k not in ("value",)} | {"ratio": c["value"]}
                                 for c in score["components"]]},
        "skills": {"declared": _declared_skills(profile), "certified": _certifications(profile)},
        "experience": {"years": m["declared_experience_years"], "source": "déclaré"},
        "missions": {"completed": m["completed_total"], "completed_window": m["completed_window"],
                     "window_days": config.sure_window_days, "source": "plateforme"},
        "satisfaction": {**reviews, "source": "plateforme"},
        "punctuality": {**m["punctuality"], "source": "plateforme"},
        "reactivity": {**m["reactivity"], "source": "plateforme"},
        "disputes": {"rate": m["disputes"]["rate"], "source": "plateforme"},
        "history": _history(profile, detailed=owner),
        "sources": SOURCES,
    }
    if owner:
        data["next_badges"] = {
            BadgeAward.EXPERT: {"label": "Expert", "earned": BadgeAward.EXPERT in active,
                                "requires_verified": True, "criteria": engine.expert_criteria(m, config)},
            BadgeAward.SUR: {"label": "Sûr", "earned": BadgeAward.SUR in active,
                             "requires_verified": True, "criteria": engine.sure_criteria(m, config)},
        }
        data["checklist"] = profile_checklist(profile)
        data["pending_certifications"] = [
            {"id": d.id, "title": d.title, "status": d.status, "uploaded_at": d.uploaded_at}
            for d in HandymanDocument.objects.filter(handyman=profile, document_type="certification")
            .exclude(status="approved").order_by("-uploaded_at")[:20]]
        data["evaluated_now"] = timezone.now()
    return data
