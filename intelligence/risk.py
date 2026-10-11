"""Dossiers de risque : propositions (règles + analyse de documents) et décisions humaines. Aucune sanction ni accusation automatique.

Un nom, une adresse ou un appareil partagé n'est JAMAIS une preuve suffisante : un doublon de compte exige un identifiant fort
(empreinte du numéro de document, fichier identique, numéro de téléphone normalisé identique), éventuellement corroboré par la similarité."""
from collections import defaultdict
from datetime import timedelta
from typing import Dict, Iterable, List, Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from handy.models import Booking, HandymanDocument, HandymanProfile, User
from intelligence.models import DocumentAnalysis, RiskCase, RiskDecision

ID_TYPES = ("id_card",)


def propose(subject_id: int, kind: str, priority: int, explanation: str, evidence: dict, *, dedupe_key: str = "", related: Iterable[int] = (), source: str = "rules") -> str:
    """Crée ou met à jour le dossier ACTIF du même signal ; un dossier écarté n'est pas rouvert sans nouvel élément."""
    now = timezone.now()
    related = sorted({int(r) for r in related if int(r) != subject_id})
    active = RiskCase.objects.filter(subject_id=subject_id, kind=kind, dedupe_key=dedupe_key, status__in=RiskCase.ACTIVE).first()
    if active:
        active.evidence, active.last_detected_at, active.related_users = evidence, now, related
        active.save(update_fields=["evidence", "last_detected_at", "related_users", "updated_at"])
        return "updated"
    closed = RiskCase.objects.filter(subject_id=subject_id, kind=kind, dedupe_key=dedupe_key, status__in=("dismissed", "confirmed")).order_by("-updated_at").first()
    if closed and closed.evidence == evidence:
        return "skipped"           # même signal déjà tranché par un humain
    RiskCase.objects.create(subject_id=subject_id, kind=kind, priority=priority, explanation=explanation, evidence=evidence, dedupe_key=dedupe_key, related_users=related, source=source)
    return "created"


def _digits(phone: Optional[str]) -> str:
    return "".join(c for c in (phone or "") if c.isdigit())


def scan() -> Dict[str, int]:
    from handy.sms import SMSError, normalize_msisdn

    stats: Dict[str, int] = defaultdict(int)
    today = timezone.localdate()

    # Doublons : numéro de téléphone normalisé E.164 identique sur plusieurs comptes (formats différents d'un même numéro).
    by_phone = defaultdict(list)
    for uid, phone in User.objects.filter(is_staff=False, phone__isnull=False).values_list("pk", "phone"):
        try:
            by_phone[normalize_msisdn(phone)].append(uid)
        except SMSError:
            continue
    for e164, ids in by_phone.items():
        if len(ids) > 1:
            for uid in ids:
                stats[propose(uid, "duplicate_account", 3, "Le même numéro de téléphone (format E.164 normalisé) apparaît sur plusieurs comptes. À vérifier : ce n'est pas une preuve de fraude en soi.",
                              {"signal": "phone_e164", "accounts": len(ids)}, dedupe_key="phone:" + e164[-6:], related=ids)] += 1

    # Doublons : même fichier ou même empreinte de numéro de document sur plusieurs profils (identifiants forts).
    for field, label in (("file_sha256", "Le même fichier de document"), ("id_fingerprint", "Le même numéro de document (empreinte protégée)")):
        groups = defaultdict(set)
        for a in DocumentAnalysis.objects.exclude(**{field: ""}).values("document__handyman__user_id", field):
            groups[a[field]].add(a["document__handyman__user_id"])
        for key, users in groups.items():
            if len(users) > 1:
                for uid in users:
                    stats[propose(uid, "duplicate_account", 3, f"{label} a été déposé par {len(users)} comptes. À vérifier par un humain : réutilisation de document ou doublon de profil possible.",
                                  {"signal": field, "accounts": len(users)}, dedupe_key=f"{field}:{key[:10]}", related=users, source="document_analysis")] += 1

    # KYC : profil approuvé dont la pièce d'identité approuvée est expirée, ou sans pièce d'identité approuvée.
    approved = HandymanProfile.objects.filter(is_approved=True).select_related("user")
    for p in approved:
        ids = list(p.documents.filter(document_type__in=ID_TYPES, status="approved"))
        if not ids:
            stats[propose(p.user_id, "identity_incomplete", 2, "Profil approuvé sans pièce d'identité approuvée au dossier : à régulariser par l'équipe KYC.", {"profile_id": p.pk}, dedupe_key=f"profile:{p.pk}")] += 1
        elif all(d.expires_on and d.expires_on < today for d in ids):
            stats[propose(p.user_id, "kyc_expired", 2, "Toutes les pièces d'identité approuvées de ce profil sont expirées : demander un nouveau document.",
                          {"profile_id": p.pk, "expired_on": max(d.expires_on for d in ids).isoformat()}, dedupe_key=f"profile:{p.pk}")] += 1

    # Activités anormales : beaucoup de réservations créées en 24 h.
    since = timezone.now() - timedelta(hours=24)
    burst = defaultdict(int)
    for cid in Booking.objects.filter(created_at__gte=since).values_list("client_id", flat=True):
        burst[cid] += 1
    for cid, n in burst.items():
        if n >= 10:
            stats[propose(cid, "abnormal_activity", 2, f"{n} réservations créées en 24 heures par le même compte. À vérifier (usage professionnel légitime possible).", {"bookings_24h": n}, dedupe_key="burst24")] += 1

    # Réservations artificielles possibles : mêmes deux comptes, nombreuses missions terminées en peu de temps.
    pair = defaultdict(int)
    for cid, hid in Booking.objects.filter(status="completed", updated_at__gte=timezone.now() - timedelta(days=14)).values_list("client_id", "handyman_id"):
        pair[(cid, hid)] += 1
    for (cid, hid), n in pair.items():
        if n >= 5:
            for uid in (cid, hid):
                stats[propose(uid, "artificial_bookings", 1, f"{n} missions terminées en 14 jours entre les deux mêmes comptes : cela peut être légitime (client fidèle) ou un gonflement artificiel — à vérifier.",
                              {"completed_14d": n}, dedupe_key=f"pair:{min(cid, hid)}-{max(cid, hid)}", related=[cid, hid])] += 1
    return dict(stats)


ALLOWED = {"investigate": {"open"}, "confirm": {"open", "investigating"}, "dismiss": {"open", "investigating"}, "reopen": {"confirmed", "dismissed"}}
NEW_STATUS = {"investigate": "investigating", "confirm": "confirmed", "dismiss": "dismissed", "reopen": "open"}


@transaction.atomic
def decide(case: RiskCase, *, by, decision: str, reason: str) -> RiskCase:
    case = RiskCase.objects.select_for_update().get(pk=case.pk)
    reason = (reason or "").strip()
    if decision not in ALLOWED:
        raise ValidationError("Décision inconnue.", code="decision")
    if len(reason) < 10:
        raise ValidationError("Un motif d'au moins 10 caractères est obligatoire.", code="reason_required")
    if case.status not in ALLOWED[decision]:
        raise ValidationError(f"Décision impossible depuis l'état « {case.get_status_display()} ».", code="transition")
    case.status = NEW_STATUS[decision]
    case.save(update_fields=["status", "updated_at"])
    RiskDecision.objects.create(case=case, actor=by, decision=decision, reason=reason[:1000])
    return case          # aucun effet sur le compte : suspension, rejet KYC… restent des actions humaines distinctes, avec leurs propres garde-fous
