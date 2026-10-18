"""Gestion intelligente : synthèses et alertes EXPLICABLES, calculées par des règles sur les données réelles (jamais par un modèle de langage).

Chaque alerte dit : ce qui est constaté (`count`), la règle appliquée (`explanation`, avec son seuil), des exemples et des ACTIONS PROPOSÉES
(libellé + lien vers le module concerné). Rien n'est exécuté ici : aucun bannissement, aucune suppression, aucune validation KYC, aucun envoi.
Un signal est un indice à vérifier par une personne, pas une preuve.

Chaque synthèse n'inclut que les sections que les droits de l'administrateur autorisent ; les autres sont listées dans `omitted`."""
from datetime import timedelta
from typing import Dict, List, Optional, Set

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.utils import timezone

from backoffice.assistant.safety import mask_ip
from backoffice.common import public_name

KYC_WAIT_DAYS = 3
KYC_EXPIRY_DAYS = 30
BURST_FACTOR = 3
BURST_MIN = 20
REPORT_WAIT_HOURS = 48
DISPUTE_WAIT_DAYS = 5
CANCEL_MIN = 3
PAIR_MIN = 4
FAILURE_SOURCE_MIN = 10
STUFFING_MIN_USERNAMES = 5
SENSITIVE_ACCESS_MIN = 30
EXAMPLES = 5

SCOPES = {"accounts": "users.view", "security": "security.manage", "bookings": "bookings.view"}


def _alert(key: str, severity: str, title: str, count: int, explanation: str, examples: Optional[List[Dict]] = None,
           actions: Optional[List[Dict]] = None) -> Dict:
    return {"key": key, "severity": severity, "title": title, "count": count, "explanation": explanation,
            "examples": (examples or [])[:EXAMPLES], "actions": [{**a, "executed": False} for a in (actions or [])]}


def _days(delta) -> int:
    return max(0, int(delta.total_seconds() // 86400))


def _base(scope: str) -> Dict:
    return {"scope": scope, "generated_at": timezone.now().isoformat(), "stats": {}, "alerts": [], "omitted": [],
            "note": "Règles explicites sur les données réelles ; ce sont des signaux à vérifier, pas des preuves. Aucune action n'est exécutée."}


# ═══ Comptes ════════════════════════════════════════════════════════════════════════════════════════════════════════

def accounts(perms: Set[str]) -> Dict:
    from handy.models import HandymanDocument, HandymanProfile, Report, User

    now = timezone.now()
    out = _base("accounts")
    members = User.objects.filter(is_staff=False, deleted_at__isnull=True)
    d1, d7, d30 = now - timedelta(days=1), now - timedelta(days=7), now - timedelta(days=30)
    out["stats"] = {
        "members": members.count(), "active": members.filter(is_active=True).count(), "verified_phone": members.filter(is_verified=True).count(),
        "new_24h": members.filter(date_joined__gte=d1).count(), "new_7d": members.filter(date_joined__gte=d7).count(),
        "new_30d": members.filter(date_joined__gte=d30).count(),
        "artisans": HandymanProfile.objects.count(), "artisans_approved": HandymanProfile.objects.filter(is_approved=True).count(),
    }
    alerts = out["alerts"]

    # Pic d'inscriptions : 24 h comparées à la moyenne journalière des 7 jours précédents.
    previous = members.filter(date_joined__gte=now - timedelta(days=8), date_joined__lt=d1).count() / 7
    if out["stats"]["new_24h"] >= BURST_MIN and out["stats"]["new_24h"] >= BURST_FACTOR * max(previous, 1):
        alerts.append(_alert("signup_burst", "warning", "Pic d'inscriptions", out["stats"]["new_24h"],
                             f"{out['stats']['new_24h']} inscriptions en 24 h, contre une moyenne de {previous:.1f} par jour sur les 7 jours précédents "
                             f"(règle : au moins {BURST_MIN} et {BURST_FACTOR} fois la moyenne). Peut venir d'une campagne : à vérifier.",
                             actions=[{"label": "Voir les comptes récents", "href": "/backoffice/users"}]))

    if "kyc.review" in perms:
        waiting = HandymanDocument.objects.filter(status="pending", uploaded_at__lt=now - timedelta(days=KYC_WAIT_DAYS)).select_related("handyman__user")
        n = waiting.count()
        out["stats"]["kyc_pending_documents"] = HandymanDocument.objects.filter(status="pending").count()
        if n:
            ex = [{"label": f"{public_name(d.handyman.user)} — {d.get_document_type_display()}, en attente depuis {_days(now - d.uploaded_at)} j",
                   "link": f"/backoffice/kyc/{d.handyman_id}"} for d in waiting.order_by("uploaded_at")[:EXAMPLES]]
            alerts.append(_alert("kyc_waiting", "warning", "Pièces KYC en attente depuis trop longtemps", n,
                                 f"Pièces à examiner déposées il y a plus de {KYC_WAIT_DAYS} jours. Un artisan non approuvé ne peut ni publier ni recevoir de mission.",
                                 ex, [{"label": "Traiter la file KYC (les plus anciennes d'abord)", "href": "/backoffice/kyc"}]))
        soon = HandymanDocument.objects.filter(status="approved", expires_on__isnull=False, expires_on__lte=timezone.localdate() + timedelta(days=KYC_EXPIRY_DAYS)
                                               ).select_related("handyman__user")
        n = soon.count()
        if n:
            ex = [{"label": f"{public_name(d.handyman.user)} — {d.get_document_type_display()}, échéance {d.expires_on:%d/%m/%Y}", "link": f"/backoffice/kyc/{d.handyman_id}"}
                  for d in soon.order_by("expires_on")[:EXAMPLES]]
            alerts.append(_alert("kyc_expiring", "info", "Pièces approuvées expirées ou bientôt expirées", n,
                                 f"Pièces approuvées dont l'échéance tombe dans les {KYC_EXPIRY_DAYS} jours ou est dépassée.", ex,
                                 [{"label": "Demander un renouvellement au membre (Messagerie)", "href": "/backoffice/messages?tab=compose"}]))
        from intelligence.models import RiskCase

        high = RiskCase.objects.filter(status__in=RiskCase.ACTIVE, priority=3).select_related("subject")
        out["stats"]["risk_cases_active"] = RiskCase.objects.filter(status__in=RiskCase.ACTIVE).count()
        n = high.count()
        if n:
            ex = [{"label": f"{public_name(c.subject)} — {c.get_kind_display()}", "link": f"/backoffice/kyc?tab=risks&case={c.pk}"} for c in high.order_by("-detected_at")[:EXAMPLES]]
            alerts.append(_alert("risk_high", "danger", "Dossiers de risque de priorité haute", n,
                                 "Dossiers proposés par les règles (doublons, incohérences, activité anormale) et classés priorité haute, pas encore tranchés par l'équipe.",
                                 ex, [{"label": "Examiner et décider (l'IA ne tranche jamais)", "href": "/backoffice/kyc?tab=risks"}]))
    else:
        out["omitted"].append("kyc.review")

    if "reviews.moderate" in perms:
        old = Report.objects.filter(is_resolved=False, created_at__lt=now - timedelta(hours=REPORT_WAIT_HOURS))
        out["stats"]["reports_unresolved"] = Report.objects.filter(is_resolved=False).count()
        n = old.count()
        if n:
            alerts.append(_alert("reports_waiting", "warning", "Signalements non traités depuis plus de 48 h", n,
                                 f"Signalements d'avis ou de messages non résolus après {REPORT_WAIT_HOURS} h.", [],
                                 [{"label": "Traiter les signalements", "href": "/backoffice/reviews?tab=reports"}]))
    else:
        out["omitted"].append("reviews.moderate")
    return out


# ═══ Sécurité ═══════════════════════════════════════════════════════════════════════════════════════════════════════

SENSITIVE_ACTIONS = ("backoffice.kyc.document_viewed", "backoffice.kyc.biometric_capture_viewed", "backoffice.contacts.unmasked_view",
                     "backoffice.user.contact_viewed", "backoffice.live.position_viewed", "backoffice.export.downloaded")


def security(perms: Set[str]) -> Dict:
    from axes.models import AccessAttempt, AccessLog

    from backoffice.models import StaffMFA
    from handy.models import IPBlacklist
    from trust.models import AuditEvent

    now = timezone.now()
    out = _base("security")
    d1, d7 = now - timedelta(days=1), now - timedelta(days=7)
    limit = int(getattr(settings, "AXES_FAILURE_LIMIT", 5) or 5)
    cooloff = float(getattr(settings, "AXES_COOLOFF_TIME", 1) or 1)
    attempts = AccessAttempt.objects.filter(attempt_time__gte=d1)
    locked = AccessAttempt.objects.filter(failures_since_start__gte=limit, attempt_time__gte=now - timedelta(hours=cooloff))
    logins = AccessLog.objects.filter(attempt_time__gte=d1)
    mfa_locked = StaffMFA.objects.filter(locked_until__gt=now).count()
    out["stats"] = {
        "failed_logins_24h": attempts.aggregate(n=Sum("failures_since_start"))["n"] or 0,
        "sources_failing_24h": attempts.values("ip_address").distinct().count(),
        "locked_now": locked.count(), "lockout_threshold": limit,
        "successful_logins_24h": logins.count(), "distinct_accounts_logged_in_24h": logins.values("username").distinct().count(),
        "staff_mfa_locked": mfa_locked, "ip_blacklist_entries": IPBlacklist.objects.count(),
    }
    alerts = out["alerts"]
    if out["stats"]["locked_now"]:
        alerts.append(_alert("lockouts", "warning", "Sources actuellement bloquées après échecs de connexion", out["stats"]["locked_now"],
                             f"Sources ayant atteint {limit} échecs de connexion consécutifs, encore dans la période de blocage ({cooloff:g} h).",
                             [{"label": f"Source {mask_ip(a.ip_address)} — {a.failures_since_start} échecs"} for a in locked.order_by("-failures_since_start")[:EXAMPLES]],
                             [{"label": "Consulter le journal d'audit", "href": "/backoffice/security?tab=audit"}]))
    heavy = list(attempts.values("ip_address").annotate(n=Sum("failures_since_start"), users=Count("username", distinct=True)).order_by("-n")[:20])
    sources = [h for h in heavy if (h["n"] or 0) >= FAILURE_SOURCE_MIN]
    if sources:
        alerts.append(_alert("brute_force_source", "danger", "Source avec un très grand nombre d'échecs de connexion", len(sources),
                             f"Une même source cumule au moins {FAILURE_SOURCE_MIN} échecs de connexion en 24 h : tentative de force brute possible.",
                             [{"label": f"Source {mask_ip(h['ip_address'])} — {h['n']} échecs sur {h['users']} compte(s) visé(s)"} for h in sources],
                             [{"label": "Consulter le journal d'audit et décider d'un blocage d'adresse (décision humaine)", "href": "/backoffice/security?tab=audit"}]))
    stuffing = [h for h in heavy if (h["users"] or 0) >= STUFFING_MIN_USERNAMES]
    if stuffing:
        alerts.append(_alert("credential_stuffing", "danger", "Source qui essaie de nombreux comptes différents", len(stuffing),
                             f"Une même source échoue sur au moins {STUFFING_MIN_USERNAMES} comptes différents en 24 h : tentative de bourrage d'identifiants possible.",
                             [{"label": f"Source {mask_ip(h['ip_address'])} — {h['users']} comptes visés"} for h in stuffing]))
    if mfa_locked:
        alerts.append(_alert("staff_mfa_locked", "warning", "Comptes d'administration verrouillés (double authentification)", mfa_locked,
                             "Trop de codes de double authentification erronés : verrouillage temporaire du compte du personnel.", [],
                             [{"label": "Voir le personnel et les rôles", "href": "/backoffice/security?tab=staff"}]))

    audit = AuditEvent.objects.filter(created_at__gte=d1, action__in=SENSITIVE_ACTIONS, actor__isnull=False)
    heavy_actors = list(audit.values("actor_id").annotate(n=Count("id")).filter(n__gte=SENSITIVE_ACCESS_MIN).order_by("-n")[:EXAMPLES])
    if heavy_actors:
        from handy.models import User

        names = {u.pk: public_name(u) for u in User.objects.filter(pk__in=[h["actor_id"] for h in heavy_actors])}
        alerts.append(_alert("sensitive_access_volume", "warning", "Consultations de données sensibles inhabituellement nombreuses", len(heavy_actors),
                             f"Compte d'administration ayant consulté au moins {SENSITIVE_ACCESS_MIN} fois en 24 h des pièces KYC, coordonnées complètes, positions ou exports. "
                             "Peut être normal lors d'une campagne de vérification : à confronter à son activité.",
                             [{"label": f"{names.get(h['actor_id'], 'Compte')} — {h['n']} consultations", "link": f"/backoffice/security?tab=audit&actor={h['actor_id']}"} for h in heavy_actors],
                             [{"label": "Examiner le journal d'audit de ce compte", "href": "/backoffice/security?tab=audit"}]))
    changes = AuditEvent.objects.filter(created_at__gte=d7, action__startswith="backoffice.security.")
    n = changes.count()
    out["stats"]["staff_security_changes_7d"] = n
    if n:
        by_action = dict(changes.values_list("action").annotate(n=Count("id")).values_list("action", "n"))
        alerts.append(_alert("staff_changes", "info", "Changements de rôles ou de sessions du personnel (7 jours)", n,
                             "Ajouts ou retraits de personnel, changements de rôles, révocations de sessions : à confronter aux demandes internes.",
                             [{"label": f"{k.replace('backoffice.security.', '')} : {v}"} for k, v in by_action.items()],
                             [{"label": "Ouvrir le journal d'audit", "href": "/backoffice/security?tab=audit"}]))
    out["stats"]["audit_actions_7d"] = dict(AuditEvent.objects.filter(created_at__gte=d7).values_list("action").annotate(n=Count("id")).order_by("-n").values_list("action", "n")[:12])
    return out


# ═══ Réservations ═══════════════════════════════════════════════════════════════════════════════════════════════════

def bookings(perms: Set[str]) -> Dict:
    from backoffice.api_system import STUCK_RULES
    from handy.models import Booking, Dispute, User

    now = timezone.now()
    out = _base("bookings")
    d30 = now - timedelta(days=30)
    window = Booking.objects.filter(created_at__gte=d30)
    total = window.count()
    by_status = dict(window.values_list("status").annotate(n=Count("id")).values_list("status", "n"))
    rate = lambda n: round(n / total, 4) if total else None    # noqa: E731
    out["stats"] = {"window_days": 30, "created": total, "by_status": by_status, "cancellation_rate": rate(by_status.get("cancelled", 0)),
                    "completion_rate": rate(by_status.get("completed", 0)),
                    "disputes_open": Dispute.objects.filter(status__in=("open", "under_review")).count()}
    alerts = out["alerts"]
    for key, (label, rule) in STUCK_RULES.items():
        qs = Booking.objects.filter(rule(now))
        n = qs.count()
        out["stats"][f"stuck_{key}"] = n
        if n:
            alerts.append(_alert(f"stuck_{key}", "warning", f"Réservations bloquées : {label.lower()}", n, f"Règle : {label}.",
                                 [{"label": f"Réservation #{b.pk} ({b.get_status_display()})", "link": f"/backoffice/bookings/{b.pk}"} for b in qs.order_by("booking_date")[:EXAMPLES]],
                                 [{"label": "Examiner les réservations bloquées", "href": "/backoffice/continuity"}]))
    old = Dispute.objects.filter(status__in=("open", "under_review"), created_at__lt=now - timedelta(days=DISPUTE_WAIT_DAYS))
    n = old.count()
    if n:
        alerts.append(_alert("disputes_waiting", "danger", "Litiges ouverts depuis plus de 5 jours", n,
                             f"Litiges encore ouverts ou en examen {DISPUTE_WAIT_DAYS} jours après leur ouverture.",
                             [{"label": f"Litige #{d.pk} sur la réservation #{d.booking_id}", "link": f"/backoffice/bookings/{d.booking_id}"} for d in old.order_by("created_at")[:EXAMPLES]],
                             [{"label": "Traiter les litiges", "href": "/backoffice/bookings?tab=disputes"}]))
    for field, who in (("client_id", "clients"), ("handyman_id", "artisans")):
        rows = list(window.values(field).annotate(total=Count("id"), cancelled=Count("id", filter=Q(status="cancelled"))).filter(cancelled__gte=CANCEL_MIN).order_by("-cancelled")[:30])
        rows = [r for r in rows if r["cancelled"] * 2 >= r["total"]]
        if rows:
            names = {u.pk: public_name(u) for u in User.objects.filter(pk__in=[r[field] for r in rows[:EXAMPLES]])}
            alerts.append(_alert(f"cancellations_{who}", "warning", f"Annulations répétées côté {who}", len(rows),
                                 f"Comptes avec au moins {CANCEL_MIN} réservations annulées en 30 jours, soit la moitié ou plus de leurs réservations. "
                                 "Les annulations légitimes existent : à confronter au contexte.",
                                 [{"label": f"{names.get(r[field], 'Compte')} — {r['cancelled']} annulées sur {r['total']}", "link": f"/backoffice/users/{r[field]}"} for r in rows],
                                 [{"label": "Consulter la fiche du compte avant toute décision", "href": "/backoffice/users"}]))
    pairs = list(window.values("client_id", "handyman_id").annotate(n=Count("id")).filter(n__gte=PAIR_MIN).order_by("-n")[:20])
    if pairs:
        alerts.append(_alert("repeat_pairs", "info", "Mêmes client et artisan, réservations très répétées", len(pairs),
                             f"Même client et même artisan avec au moins {PAIR_MIN} réservations en 30 jours : peut être un service récurrent légitime, "
                             "ou des réservations artificielles (avis ou missions fictifs) : à vérifier.",
                             [{"label": f"Client #{p['client_id']} et artisan #{p['handyman_id']} — {p['n']} réservations"} for p in pairs],
                             [{"label": "Consulter les réservations concernées", "href": "/backoffice/bookings"}]))
    if "kyc.review" in perms:
        from intelligence.models import RiskCase

        n = RiskCase.objects.filter(kind="artificial_bookings", status__in=RiskCase.ACTIVE).count()
        out["stats"]["artificial_bookings_cases"] = n
        if n:
            alerts.append(_alert("artificial_bookings", "danger", "Réservations artificielles possibles (dossiers de risque)", n,
                                 "Dossiers de risque ouverts par les règles de détection ; l'équipe tranche.", [],
                                 [{"label": "Ouvrir les dossiers de risque", "href": "/backoffice/kyc?tab=risks"}]))
    else:
        out["omitted"].append("kyc.review")
    return out


HANDLERS = {"accounts": accounts, "security": security, "bookings": bookings}
