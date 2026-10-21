"""Supervision Smart Dispatch (Back-Office et Tratra AI, lecture seule) : chiffres réels de la période et recommandations EXPLICABLES.

Chaque recommandation cite la règle appliquée et les chiffres qui la déclenchent ; elle ne modifie rien : l'équipe décide (réglages)."""
from datetime import timedelta
from statistics import median
from typing import Dict, List

from django.db.models import Count
from django.utils import timezone

from flash.models import DispatchConfig, DispatchEvent, MissionOffer, MissionRequest


def overview(days: int = 7, *, now=None) -> Dict:
    now = now or timezone.now()
    since = now - timedelta(days=days)
    config = DispatchConfig.current()
    reqs = MissionRequest.objects.filter(created_at__gte=since)
    by_status = dict(reqs.values_list("status").annotate(n=Count("id")).values_list("status", "n"))
    total = sum(by_status.values())
    assigned = list(reqs.filter(status=MissionRequest.ASSIGNED, assigned_at__isnull=False).values_list("created_at", "assigned_at"))
    delays = [(a - c).total_seconds() for c, a in assigned]
    offers = MissionOffer.objects.filter(sent_at__gte=since)
    offer_status = dict(offers.values_list("status").annotate(n=Count("id")).values_list("status", "n"))
    answered = offers.filter(status__in=(MissionOffer.ACCEPTED, MissionOffer.QUOTED, MissionOffer.DECLINED), response_seconds__isnull=False)
    times = list(answered.values_list("response_seconds", flat=True))
    decided = sum(offer_status.get(s, 0) for s in (MissionOffer.ACCEPTED, MissionOffer.QUOTED, MissionOffer.DECLINED, MissionOffer.EXPIRED))
    reasons = {dict(MissionOffer.DECLINE_REASONS).get(k, "Sans motif"): n
               for k, n in offers.filter(status=MissionOffer.DECLINED).values_list("decline_reason").annotate(n=Count("id"))}
    waiting = MissionRequest.objects.filter(status=MissionRequest.SEARCHING, created_at__lt=now - timedelta(minutes=10))
    data = {
        "period_days": days,
        "requests": {"total": total, "by_status": by_status,
                     "assignment_rate": round(by_status.get(MissionRequest.ASSIGNED, 0) / total, 3) if total else None,
                     "median_seconds_to_assign": int(median(delays)) if delays else None},
        "offers": {"total": sum(offer_status.values()), "by_status": offer_status,
                   "expiry_rate": round(offer_status.get(MissionOffer.EXPIRED, 0) / decided, 3) if decided else None,
                   "median_response_seconds": int(median(times)) if times else None, "decline_reasons": reasons},
        "by_matching": {m: {"total": reqs.filter(matching=m).count(), "assigned": reqs.filter(matching=m, status=MissionRequest.ASSIGNED).count()}
                        for m, _ in MissionRequest.MATCHINGS},
        "switches": DispatchEvent.objects.filter(kind="switched", at__gte=since).count(),
        "awaiting_choice": MissionRequest.objects.filter(status=MissionRequest.AWAITING).count(),
        "auto_paused": DispatchEvent.objects.filter(kind="auto_paused", at__gte=since).count(),
        "no_candidate": DispatchEvent.objects.filter(kind="no_candidate", at__gte=since).count(),
        "waiting_over_10_min": waiting.count(),
        "config": {"wave_size": config.wave_size, "max_waves": config.max_waves, "offer_timeout_seconds": config.offer_timeout_seconds,
                   "radius_km": config.radius_km},
    }
    data["recommendations"] = recommendations(data)
    return data


def recommendations(d: Dict) -> List[Dict]:
    """Règles simples et lisibles ; rien n'est appliqué automatiquement."""
    out: List[Dict] = []
    r, o, cfg = d["requests"], d["offers"], d["config"]
    if o["expiry_rate"] is not None and o["total"] >= 10 and o["expiry_rate"] >= 0.5:
        out.append({"rule": "Plus de la moitié des propositions restent sans réponse",
                    "evidence": f"{round(o['expiry_rate'] * 100)} % sans réponse sur {o['total']} propositions",
                    "suggestion": f"Allonger le délai de réponse (actuellement {cfg['offer_timeout_seconds']} s) ou rappeler aux professionnels "
                                  "de passer « Indisponible » quand ils ne peuvent pas répondre."})
    if r["total"] >= 5 and r["assignment_rate"] is not None and r["assignment_rate"] < 0.5:
        out.append({"rule": "Moins d'une demande sur deux est attribuée",
                    "evidence": f"{round(r['assignment_rate'] * 100)} % attribuées sur {r['total']} demandes",
                    "suggestion": f"Élargir le rayon ({cfg['radius_km']} km) ou le nombre de vagues ({cfg['max_waves']}), "
                                  "ou recruter des professionnels dans les métiers les plus demandés."})
    if d["no_candidate"] >= 3:
        out.append({"rule": "Demandes sans aucun professionnel éligible",
                    "evidence": f"{d['no_candidate']} demande(s) sans candidat sur la période",
                    "suggestion": "Consulter l'historique des attributions pour voir les motifs d'exclusion (zone, disponibilité, métier)."})
    top = max(o["decline_reasons"].items(), key=lambda kv: kv[1]) if o["decline_reasons"] else None
    if top and top[0] == "Montant insuffisant" and top[1] >= 5:
        out.append({"rule": "Refus surtout pour montant insuffisant", "evidence": f"{top[1]} refus « montant insuffisant »",
                    "suggestion": "Indiquer aux clients une fourchette de prix habituelle par métier."})
    if d["waiting_over_10_min"]:
        out.append({"rule": "Demandes en recherche depuis plus de 10 minutes", "evidence": f"{d['waiting_over_10_min']} demande(s)",
                    "suggestion": "Les suivre dans la supervision ; contacter le client si besoin."})
    return out
