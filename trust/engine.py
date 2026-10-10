"""Moteur Tratra Trust : badges automatiques et auditables, score de confiance explicable.

- NOUVEAU : profil créé, identité pas encore vérifiée (disparaît quand VERIFIE est attribué).
- VERIFIE : exclusivement le KYC — règle d'éligibilité unique (compte actif, KYC approuvé, profil complet,
  validation de l'équipe : handy/eligibility.py). Jamais sur déclaration.
- EXPERT : VERIFIE + justificatifs professionnels approuvés + résultats (missions, avis, note, expérience).
- SUR : VERIFIE + fiabilité mesurée (ponctualité, litiges, note, volume de missions sur la période).
Les badges sont cumulables (VERIFIE + EXPERT + SUR). Perdre VERIFIE (suspension, KYC invalide, compte
désactivé) retire immédiatement EXPERT et SUR. Critères : trust.models.TrustConfig (administration).
"""
import logging
from typing import Dict, List, Optional

from django.db import transaction
from django.utils import timezone

from handy.models import HandymanProfile
from trust import metrics
from trust.models import AuditEvent, BadgeAward, TrustConfig, audit

logger = logging.getLogger(__name__)


# Composantes issues de l'ACTIVITÉ réelle : au moins une doit être mesurable pour qu'un score soit publié.
ACTIVITY_COMPONENTS = ("satisfaction", "reliability", "reactivity")


def _pct(x) -> str:
    return f"{round(x * 100)} %"


def _crit(key, label, current, required, met, *, source="plateforme", unit="", higher_better=True) -> Dict:
    return {"key": key, "label": label, "current": current, "required": required, "met": bool(met),
            "source": source, "unit": unit, "higher_better": higher_better}


def expert_criteria(m: Dict, c: TrustConfig) -> List[Dict]:
    rev = m["reviews"]
    rating = rev["average"]
    return [
        _crit("certifications", "Justificatifs professionnels approuvés", len(m["certifications"]),
              c.expert_min_certifications, len(m["certifications"]) >= c.expert_min_certifications, source="vérifié"),
        _crit("completed", "Missions terminées", m["completed_total"], c.expert_min_completed,
              m["completed_total"] >= c.expert_min_completed),
        _crit("reviews", "Avis clients retenus", rev["count"], c.expert_min_reviews, rev["count"] >= c.expert_min_reviews),
        _crit("rating", "Note moyenne", rating, c.expert_min_rating,
              rating is not None and rating >= c.expert_min_rating, unit="/5"),
        _crit("experience", "Années d'expérience", m["declared_experience_years"], c.expert_min_experience_years,
              m["declared_experience_years"] >= c.expert_min_experience_years, source="déclaré"),
    ]


def sure_criteria(m: Dict, c: TrustConfig) -> List[Dict]:
    rev, pun, dis = m["reviews"], m["punctuality"], m["disputes"]
    rate = pun["rate"]
    drate = dis["rate"]
    return [
        _crit("completed", f"Missions terminées ({c.sure_window_days} derniers jours)", m["completed_window"],
              c.sure_min_completed, m["completed_window"] >= c.sure_min_completed),
        _crit("punctuality_sample", "Missions mesurées pour la ponctualité", pun["sample"],
              c.sure_min_punctuality_sample, pun["sample"] >= c.sure_min_punctuality_sample),
        _crit("punctuality", "Taux de ponctualité", rate, c.sure_min_punctuality,
              rate is not None and pun["sample"] >= c.sure_min_punctuality_sample and rate >= c.sure_min_punctuality,
              unit="%"),
        _crit("disputes", "Taux de litiges", drate, c.sure_max_dispute_rate,
              drate is not None and drate <= c.sure_max_dispute_rate, unit="%", higher_better=False),
        _crit("reviews", "Avis clients retenus", rev["count"], c.sure_min_reviews, rev["count"] >= c.sure_min_reviews),
        _crit("rating", "Note moyenne", rev["average"], c.sure_min_rating,
              rev["average"] is not None and rev["average"] >= c.sure_min_rating, unit="/5"),
    ]


def trust_score(m: Dict, c: TrustConfig) -> Dict:
    """Score 0-100 EXPLICABLE : somme pondérée des seules composantes mesurables. Une composante sans données
    suffisantes est écartée (jamais comptée comme zéro) : un nouvel artisan n'est pas pénalisé. Sans identité
    vérifiée, aucun score n'est publié."""
    rev, pun, rea, dis = m["reviews"], m["punctuality"], m["reactivity"], m["disputes"]
    n = c.min_sample
    parts = []

    def part(key, label, weight, value, detail, source, available=True, missing=""):
        parts.append({"key": key, "label": label, "weight": weight, "available": bool(available and value is not None),
                      "value": None if value is None or not available else round(value, 3), "detail": detail if available and value is not None else missing,
                      "source": source})

    part("identity", "Identité vérifiée (KYC)", c.weight_identity, 1.0 if m["verified"] else 0.0,
         "Pièce d'identité contrôlée par l'équipe Tratra" if m["verified"] else "Identité non vérifiée", "vérifié")
    part("satisfaction", "Satisfaction des clients", c.weight_satisfaction,
         (rev["average"] / 5) if rev["average"] is not None else None,
         f"{str(rev['average']).replace('.', ',')}/5 sur {rev['count']} avis", "plateforme",
         available=rev["count"] >= n, missing=f"Pas encore assez d'avis ({rev['count']}/{n})")
    pun_value = None
    if pun["rate"] is not None:
        pun_value = pun["rate"]
        if dis["rate"] is not None:
            pun_value = max(0.0, pun_value - dis["rate"])  # un litige pèse sur la fiabilité
    part("reliability", "Fiabilité (ponctualité, litiges)", c.weight_reliability, pun_value,
         f"{_pct(pun['rate'] or 0)} à l'heure sur {pun['sample']} missions"
         + (f", {dis['count']} litige(s)" if dis["count"] else ""), "plateforme",
         available=pun["sample"] >= n, missing=f"Pas encore assez de missions mesurées ({pun['sample']}/{n})")
    rea_value = None
    if rea["median_minutes"] is not None:
        mn = rea["median_minutes"]
        rea_value = 1.0 if mn <= 30 else max(0.0, 1.0 - (mn - 30) / (1440 - 30))
    part("reactivity", "Réactivité aux demandes", c.weight_reactivity, rea_value,
         f"Réponse médiane en {int(rea['median_minutes'] or 0)} min sur {rea['sample']} demandes", "plateforme",
         available=rea["sample"] >= n, missing=f"Pas encore assez de demandes traitées ({rea['sample']}/{n})")
    part("track_record", "Missions terminées", c.weight_track_record, min(m["completed_total"], 30) / 30,
         f"{m['completed_total']} mission(s) terminée(s)", "plateforme",
         available=m["completed_total"] >= 1, missing="Aucune mission terminée pour le moment")
    certs = len(m["certifications"])
    part("certifications", "Justificatifs professionnels", c.weight_certifications, min(certs, 3) / 3,
         f"{certs} justificatif(s) approuvé(s)", "vérifié", available=certs >= 1,
         missing="Aucun justificatif déposé (facultatif)")

    live = [p for p in parts if p["available"] and p["weight"] > 0]
    activity = [p for p in live if p["key"] in ACTIVITY_COMPONENTS]
    total_weight = sum(p["weight"] for p in live)
    if not m["verified"]:
        score, reason = None, "Identité non vérifiée : aucun score n'est publié."
    elif not activity:
        # L'identité seule ne fait pas un score : sans activité mesurée (avis, ponctualité, réactivité), on
        # n'affiche rien plutôt qu'un chiffre flatteur ou punitif — un nouvel artisan reste « en démarrage ».
        score, reason = None, "Pas encore assez d'activité mesurée pour publier un score (aucune pénalité)."
    else:
        score = round(100 * sum(p["weight"] * p["value"] for p in live) / total_weight)
        reason = ""
    for p in parts:
        shown = score is not None and p in live
        p["points"] = round(100 * p["weight"] * p["value"] / total_weight, 1) if shown else None
        p["max_points"] = round(100 * p["weight"] / total_weight, 1) if shown else None
    measured = len(live)
    confidence = "élevée" if measured >= 5 else ("moyenne" if measured >= 3 else "faible")
    return {"score": score, "confidence": confidence if score is not None else None, "reason": reason,
            "components": parts,
            "note": "Seules les composantes mesurables comptent : une donnée manquante n'est jamais comptée comme un zéro."}


def desired_badges(m: Dict, c: TrustConfig) -> Dict[str, Dict]:
    """{code: {reason, snapshot}} des badges que l'artisan DOIT avoir maintenant."""
    out: Dict[str, Dict] = {}
    if not m["account_active"]:
        return out  # compte suspendu/désactivé : aucun badge, aucune visibilité
    if not m["verified"]:
        out[BadgeAward.NOUVEAU] = {"reason": "Profil créé, identité pas encore vérifiée (KYC)."}
        return out
    out[BadgeAward.VERIFIE] = {"reason": "KYC approuvé, profil complet et validé par l'équipe Tratra."}
    expert = expert_criteria(m, c)
    if all(x["met"] for x in expert):
        out[BadgeAward.EXPERT] = {"reason": "Expertise démontrée : justificatifs approuvés et résultats atteints.",
                                  "criteria": expert}
    sure = sure_criteria(m, c)
    if all(x["met"] for x in sure):
        out[BadgeAward.SUR] = {"reason": "Fiabilité démontrée par les interventions (ponctualité, litiges, avis).",
                               "criteria": sure}
    return out


def _lost_reason(code: str, m: Dict, c: TrustConfig) -> str:
    if code in (BadgeAward.EXPERT, BadgeAward.SUR) and not m["verified"]:
        return "Retrait immédiat : l'identité n'est plus vérifiée (suspension, KYC invalide ou compte désactivé)."
    if code == BadgeAward.VERIFIE:
        return "Identité plus vérifiée : KYC non approuvé, profil incomplet, compte inactif ou suspendu."
    if code == BadgeAward.NOUVEAU:
        return "Identité vérifiée."
    crit = expert_criteria(m, c) if code == BadgeAward.EXPERT else sure_criteria(m, c)
    unmet = [f"{x['label']} ({x['current']} / {x['required']})" for x in crit if not x["met"]]
    return "Critères non atteints : " + "; ".join(unmet) if unmet else "Critères non atteints."


@transaction.atomic
def evaluate_profile(profile: HandymanProfile, *, trigger: str = "signal", actor=None, config: Optional[TrustConfig] = None) -> Dict:
    """Réévalue UN artisan : attribue/retire les badges (historisés et audités), met à jour le score copié sur
    le profil. Idempotent. Renvoie {awarded, revoked, badges, score}."""
    config = config or TrustConfig.get_solo()
    now = timezone.now()
    metrics_ = metrics.collect(profile, config, now)
    wanted = desired_badges(metrics_, config)
    score = trust_score(metrics_, config)

    active = {a.code: a for a in BadgeAward.objects.select_for_update().filter(profile=profile, ended_at__isnull=True)}
    awarded, revoked = [], []
    # Retraits d'abord : ordre déterministe (les badges dépendants partent avec VERIFIE).
    for code, award in active.items():
        if code not in wanted:
            award.ended_at = now
            award.end_reason = _lost_reason(code, metrics_, config)
            award.save(update_fields=["ended_at", "end_reason"])
            revoked.append(code)
            audit("badge.revoked", actor=actor, target=profile, badge=code, reason=award.end_reason, trigger=trigger)
    for code, info in wanted.items():
        if code not in active:
            snap = {"criteria": info.get("criteria", []), "score": score["score"]}
            BadgeAward.objects.create(profile=profile, code=code, start_reason=info["reason"], snapshot=snap)
            awarded.append(code)
            audit("badge.awarded", actor=actor, target=profile, badge=code, reason=info["reason"], trigger=trigger)
    codes = [c for c in BadgeAward.ORDER if c in wanted]
    HandymanProfile.objects.filter(pk=profile.pk).update(
        trust_score=score["score"], trust_badges=codes, trust_evaluated_at=now)
    profile.trust_score, profile.trust_badges, profile.trust_evaluated_at = score["score"], codes, now
    return {"awarded": awarded, "revoked": revoked, "badges": codes, "score": score["score"]}


def evaluate_user(user_id, *, trigger="signal") -> Optional[Dict]:
    profile = HandymanProfile.objects.select_related("user").filter(user_id=user_id).first()
    if profile is None:
        return None
    try:
        return evaluate_profile(profile, trigger=trigger)
    except Exception:  # une réévaluation ne doit jamais faire échouer l'action métier qui l'a déclenchée
        logger.exception("Réévaluation Tratra Trust impossible (profil %s)", profile.pk)
        return None


def reevaluate_all(*, force: bool = False, trigger: str = "periodic") -> int:
    """Réévaluation périodique de tous les profils (ceux évalués depuis moins de `reevaluation_hours` sont
    ignorés sauf `force`)."""
    config = TrustConfig.get_solo()
    from datetime import timedelta

    limit = timezone.now() - timedelta(hours=config.reevaluation_hours)
    n = 0
    for profile in HandymanProfile.objects.select_related("user").iterator():
        if not force and profile.trust_evaluated_at and profile.trust_evaluated_at > limit:
            continue
        try:
            evaluate_profile(profile, trigger=trigger, config=config)
            n += 1
        except Exception:
            logger.exception("Réévaluation périodique impossible (profil %s)", profile.pk)
    return n
