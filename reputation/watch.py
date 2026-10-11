"""Surveillance des évaluations : la détection PROPOSE des dossiers expliqués par des chiffres réels ; l'humain décide.

Aucune sanction automatique. Les notes sont pondérées par leur fiabilité (un évaluateur qui note presque toujours très bas pèse moitié moins),
et rien n'est proposé sous un échantillon minimal. Bannissement : uniquement après un avertissement ou une suspension motivés, par un
Super Admin, avec journal des décisions et possibilité de recours."""
from collections import defaultdict
from datetime import timedelta
from typing import Dict, List

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from handy.models import Review, User
from reputation.models import ClientReview, EvaluationWatch, WatchDecision

MIN_SAMPLE = 5
WINDOW_DAYS = 180
LOW = 2


def _ratings():
    """(auteur, personne évaluée, rôle de l'évalué, note, date) — notes révélées et non masquées, sur la fenêtre d'observation."""
    since = timezone.now() - timedelta(days=WINDOW_DAYS)
    rows = []
    for author, subject, rating, at in Review.objects.filter(is_hidden=False, revealed_at__isnull=False, created_at__gte=since, booking__status="completed") \
            .values_list("booking__client_id", "booking__handyman_id", "rating", "created_at"):
        rows.append((author, subject, "provider", rating, at))
    for author, subject, rating, at in ClientReview.objects.filter(is_hidden=False, revealed_at__isnull=False, created_at__gte=since) \
            .values_list("author_id", "subject_id", "rating", "created_at"):
        rows.append((author, subject, "requester", rating, at))
    return rows


def _propose(subject_id: int, kind: str, priority: int, explanation: str, evidence: dict, newest) -> str:
    now = timezone.now()
    active = EvaluationWatch.objects.filter(subject_id=subject_id, kind=kind, status__in=EvaluationWatch.ACTIVE).first()
    if active:
        active.evidence, active.last_detected_at = evidence, now
        active.save(update_fields=["evidence", "last_detected_at", "updated_at"])
        return "updated"
    cleared = EvaluationWatch.objects.filter(subject_id=subject_id, kind=kind, status__in=("cleared", "banned")).order_by("-updated_at").first()
    if cleared and newest is not None and cleared.updated_at >= newest:
        return "skipped"          # classé depuis : rien de nouveau, on ne le rouvre pas
    EvaluationWatch.objects.create(subject_id=subject_id, kind=kind, priority=priority, explanation=explanation, evidence=evidence)
    return "created"


def scan() -> Dict[str, int]:
    rows = _ratings()
    stats = defaultdict(int)
    given_by = defaultdict(list)        # auteur -> [(sujet, note, date)]
    got_by = defaultdict(list)          # (sujet, rôle) -> [(auteur, note, date)]
    for author, subject, role, rating, at in rows:
        given_by[author].append((subject, rating, at))
        got_by[(subject, role)].append((author, rating, at))
    serial_low = {a for a, v in given_by.items() if len(v) >= MIN_SAMPLE and sum(1 for _, r, _ in v if r <= LOW) / len(v) >= 0.8}

    # 1. Notes basses reçues de façon répétée (pondérées : une note d'un évaluateur « toujours sévère » compte moitié).
    for (subject, role), items in got_by.items():
        if len(items) < MIN_SAMPLE:
            continue
        weights = [0.5 if a in serial_low else 1.0 for a, _, _ in items]
        wavg = sum(w * r for w, (_, r, _) in zip(weights, items)) / sum(weights)
        low_share = sum(w for w, (_, r, _) in zip(weights, items) if r <= LOW) / sum(weights)
        if low_share >= 0.6 and wavg <= 2.5:
            prio = 3 if (low_share >= 0.8 and len(items) >= 10) else 2
            ev = {"role": role, "count": len(items), "low_share": round(low_share, 2), "weighted_average": round(wavg, 2), "window_days": WINDOW_DAYS,
                  "from_serial_low_raters": sum(1 for a, _, _ in items if a in serial_low)}
            stats[_propose(subject, "low_received", prio, f"{len(items)} notes reçues sur {WINDOW_DAYS} jours, dont {round(low_share * 100)} % de 1 ou 2 étoiles (moyenne pondérée {round(wavg, 2)}/5). "
                           "À examiner : cela peut refléter un vrai problème de qualité ou des notes abusives — à vérifier sur les missions concernées.", ev, max(at for _, _, at in items))] += 1

    # 2. Mauvaises notes données de façon répétée alors que les personnes évaluées sont bien notées par ailleurs.
    for author in serial_low:
        items = given_by[author]
        others = []
        for subject, _, _ in items:
            for a, r, _ in (got_by.get((subject, "provider"), []) + got_by.get((subject, "requester"), [])):
                if a != author:
                    others.append(r)
        if len(others) >= MIN_SAMPLE and sum(others) / len(others) >= 3.5:
            ev = {"given": len(items), "low_share": round(sum(1 for _, r, _ in items if r <= LOW) / len(items), 2), "others_average": round(sum(others) / len(others), 2), "others_count": len(others)}
            stats[_propose(author, "low_given", 2, f"{len(items)} évaluations données, presque toutes à 1 ou 2 étoiles, alors que les personnes évaluées sont notées {ev['others_average']}/5 par les autres. "
                           "Indice d'abus possible — à vérifier, jamais une preuve en soi.", ev, max(at for _, _, at in items))] += 1

    # 3. Rafale : beaucoup d'évaluations écrites en moins de 24 h.
    for author, items in given_by.items():
        times = sorted(at for _, _, at in items)
        for i in range(len(times) - MIN_SAMPLE + 1):
            if times[i + MIN_SAMPLE - 1] - times[i] <= timedelta(hours=24):
                stats[_propose(author, "burst", 1, f"{MIN_SAMPLE} évaluations ou plus écrites en moins de 24 heures.", {"count_24h": MIN_SAMPLE, "since": times[i].isoformat()}, times[-1])] += 1
                break

    # 4. Notes réciproques de 5 étoiles répétées entre les mêmes deux personnes (gonflement mutuel possible).
    pair = defaultdict(list)
    for author, subject, role, rating, at in rows:
        pair[(author, subject)].append(rating)
    seen = set()
    for (a, b), mine in pair.items():
        if (b, a) in seen or (a, b) in seen or (b, a) not in pair:
            continue
        seen.add((a, b))
        theirs = pair[(b, a)]
        if len(mine) >= 3 and len(theirs) >= 3 and all(r == 5 for r in mine + theirs):
            for who in (a, b):
                stats[_propose(who, "reciprocal", 1, "Plusieurs évaluations réciproques de 5 étoiles entre les deux mêmes personnes : peut être légitime (clients fidèles) — à vérifier.",
                               {"pair_count": len(mine) + len(theirs)}, timezone.now())] += 1
    return dict(stats)


# ═══ Décisions humaines ═══════════════════════════════════════════════════════════════════════════════════════════

ALLOWED = {
    "investigate": {"open"},
    "warn": {"open", "investigating"},
    "suspend": {"open", "investigating", "warned"},
    "ban": {"warned", "suspended"},                # jamais sans décision motivée préalable (avertissement ou suspension)
    "appeal": {"warned", "suspended", "banned"},
    "reinstate": {"suspended", "banned"},
    "clear": {"open", "investigating", "warned"},
}
NEW_STATUS = {"investigate": "investigating", "warn": "warned", "suspend": "suspended", "ban": "banned", "reinstate": "cleared", "clear": "cleared"}


@transaction.atomic
def decide(watch: EvaluationWatch, *, by: User, decision: str, reason: str) -> EvaluationWatch:
    from backoffice import services as bo_services

    watch = EvaluationWatch.objects.select_for_update().select_related("subject").get(pk=watch.pk)
    reason = (reason or "").strip()
    if decision not in ALLOWED:
        raise ValidationError("Décision inconnue.", code="decision")
    if len(reason) < 10:
        raise ValidationError("Un motif d'au moins 10 caractères est obligatoire.", code="reason_required")
    if watch.status not in ALLOWED[decision]:
        raise ValidationError(f"Décision impossible depuis l'état « {watch.get_status_display()} »"
                              + (" : un bannissement exige d'abord un avertissement ou une suspension motivés." if decision == "ban" else "."), code="transition")
    user = watch.subject
    if decision in ("suspend", "ban") and user.is_active:
        bo_services.suspend_user(user, by=by, reason=reason)
    if decision == "reinstate" and not user.is_active:
        bo_services.reactivate_user(user)
    if decision in NEW_STATUS:
        watch.status = NEW_STATUS[decision]
        watch.save(update_fields=["status", "updated_at"])
    WatchDecision.objects.create(watch=watch, actor=by, decision=decision, reason=reason[:1000])
    if decision == "warn":
        from handy.notifications import notify

        notify(user, "system", "Votre activité d'évaluation est examinée par l'équipe Tratra. Merci de respecter les règles de la communauté : des notes sincères, fondées sur des missions réelles.",
               title="Avertissement", dedupe_key=f"watch:{watch.pk}:warn:{WatchDecision.objects.filter(watch=watch).count()}")
    return watch
