"""Service KYC biométrique centralisé : consentement, sessions courtes, captures chiffrées, soumission au fournisseur, décision côté serveur,
limites de tentatives, reprise, expiration, suppression. Rien n'est validé sans un résultat réel d'un fournisseur ou une décision humaine."""
import hashlib
import hmac
import io
import secrets
from datetime import timedelta
from typing import Dict, List, Optional

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from biometrics import consent, crypto, quality
from biometrics.crypto import BiometricUnavailable
from biometrics.models import BiometricCapture, BiometricConsent, BiometricDecision, BiometricSession, BiometricVerification
from biometrics.providers import ProviderError, ProviderResult, get_provider
from handy.models import HandymanDocument
from handy.notifications import notify
from trust.models import audit

POSES = ["left", "right", "up", "down"]
INSTRUCTIONS = {"front": "Regardez droit devant vous", "left": "Tournez lentement la tête vers la gauche", "right": "Tournez lentement la tête vers la droite",
                "up": "Inclinez la tête vers le haut", "down": "Inclinez la tête vers le bas", "smile": "Souriez"}
MAX_TOKEN_USES = 60
MIN_CAPTURE_SPAN_SECONDS = 3.0           # six captures « humaines » ne tiennent pas en moins de quelques secondes
BAD_FLAGS = {"screen_replay", "mask", "deepfake", "printed_photo", "injection"}


class BiometricError(Exception):
    def __init__(self, code: str, detail: str, status: int = 409, extra: Optional[dict] = None, flag: Optional[str] = None):
        super().__init__(detail)
        self.code, self.detail, self.status, self.extra = code, detail, status, extra or {}
        self.flag = flag          # anomalie à CONSERVER même si la transaction est annulée (indice de fraude)


def enabled() -> bool:
    return bool(getattr(settings, "BIOMETRIC_ENABLED", False))


def _profile(user):
    profile = getattr(user, "handyman_profile", None)
    if profile is None:
        raise BiometricError("no_profile", "Créez d'abord votre profil professionnel pour vérifier votre identité.", 409)
    return profile


def verification_for(profile) -> BiometricVerification:
    obj, _ = BiometricVerification.objects.get_or_create(profile=profile)
    return obj


def id_document(profile) -> Optional[HandymanDocument]:
    return HandymanDocument.objects.filter(handyman=profile, document_type="id_card").exclude(status="rejected").order_by("-uploaded_at").first()


def active_consent(user) -> Optional[BiometricConsent]:
    return BiometricConsent.objects.filter(user=user, withdrawn_at__isnull=True, version=consent.version()).first()


def satisfied(profile) -> bool:
    """Vérification faciale satisfaisante OU procédure alternative approuvée par un humain (lue par le moteur de badges)."""
    return BiometricVerification.objects.filter(profile=profile, status__in=BiometricVerification.SATISFIED).exists()


def _token_ok(session: BiometricSession, token: str) -> bool:
    return bool(token) and hmac.compare_digest(session.token_hash, hashlib.sha256(token.encode()).hexdigest())


def _new_token(session: BiometricSession) -> str:
    token = secrets.token_urlsafe(32)
    session.token_hash, session.token_uses = hashlib.sha256(token.encode()).hexdigest(), 0
    return token


def _challenges() -> List[str]:
    rng = secrets.SystemRandom()
    order = POSES[:]
    rng.shuffle(order)                                           # ordre propre à CHAQUE session (non prévisible pour un enregistrement préparé)
    return ["front"] + order + ["smile"]


def _payload(session: BiometricSession, token: Optional[str] = None) -> Dict:
    done = list(session.captures.filter(deleted_at__isnull=True).values_list("index", flat=True))
    out = {"session_id": session.pk, "expires_at": session.expires_at, "status": session.status, "captured": done,
           "challenges": [{"index": i, "kind": k, "instruction": INSTRUCTIONS[k]} for i, k in enumerate(session.challenges)]}
    if token:
        out["token"] = token
    return out


# ═══ État et consentement ════════════════════════════════════════════════════════════════════════════════════════════

def state(user) -> Dict:
    profile = _profile(user)
    ver = verification_for(profile)
    doc = id_document(profile)
    now = timezone.now()
    since_day, since_week = now - timedelta(days=1), now - timedelta(days=7)
    sessions = BiometricSession.objects.filter(user=user)
    active = sessions.filter(status__in=(BiometricSession.CREATED, BiometricSession.CAPTURING), expires_at__gt=now).first()
    last = sessions.exclude(outcome="").first()
    provider = get_provider()
    return {
        "enabled": enabled(), "provider_configured": enabled() and provider.configured(), "status": ver.status, "status_label": ver.get_status_display(), "satisfied": ver.satisfied,
        "consent": {"version": consent.version(), "text": consent.CONSENT_TEXT, "granted": active_consent(user) is not None},
        "document": {"present": doc is not None, "status": doc.status if doc else None, "type_label": "Carte d'identité ou passeport"},
        "human_review_requested": ver.human_review_requested_at is not None and ver.status == BiometricVerification.PENDING_REVIEW,
        "active_session": _payload(active) if active else None,
        "last_outcome": {"outcome": last.outcome, "at": last.completed_at or last.submitted_at} if last else None,
        "attempts": {"day": sessions.filter(created_at__gte=since_day).count(), "max_day": settings.BIOMETRIC_MAX_ATTEMPTS_PER_DAY,
                     "week": sessions.filter(created_at__gte=since_week).count(), "max_week": settings.BIOMETRIC_MAX_ATTEMPTS_PER_WEEK},
        "decision_reason": ver.decision_reason if ver.status in (BiometricVerification.REJECTED, BiometricVerification.RECAPTURE, BiometricVerification.DOCUMENTS) else "",
        "alternative": {"available": True, "label": "Demander une vérification par l'équipe Tratra"},
    }


@transaction.atomic
def grant_consent(user, *, version: str, ip: str = "") -> BiometricConsent:
    _profile(user)
    if version != consent.version():
        raise BiometricError("consent_version", "Le texte du consentement a changé : relisez-le avant de continuer.", 409)
    existing = active_consent(user)
    if existing:
        return existing
    c = BiometricConsent.objects.create(user=user, version=version, text_sha256=consent.text_sha256(), ip_hash=hashlib.sha256(ip.encode()).hexdigest() if ip else "")
    audit("biometric.consent_granted", actor=user, target=user, version=version)
    return c


@transaction.atomic
def withdraw_consent(user) -> int:
    """Retire le consentement ET supprime immédiatement toutes les captures de l'utilisateur. Renvoie le nombre de captures supprimées."""
    n = _delete_captures(BiometricCapture.objects.filter(session__user=user, deleted_at__isnull=True))
    BiometricConsent.objects.filter(user=user, withdrawn_at__isnull=True).update(withdrawn_at=timezone.now())
    BiometricSession.objects.filter(user=user, status__in=(BiometricSession.CREATED, BiometricSession.CAPTURING)).update(status=BiometricSession.CANCELLED)
    profile = getattr(user, "handyman_profile", None)
    if profile:
        BiometricVerification.objects.filter(profile=profile, status__in=(BiometricVerification.PASSED, BiometricVerification.IN_PROGRESS, BiometricVerification.PENDING_REVIEW,
                                                                         BiometricVerification.FAILED, BiometricVerification.INCONCLUSIVE)).update(status=BiometricVerification.NOT_STARTED)
    audit("biometric.consent_withdrawn", actor=user, target=user, captures_deleted=n)
    return n


# ═══ Session ═════════════════════════════════════════════════════════════════════════════════════════════════════════

@transaction.atomic
def start_session(user) -> Dict:
    """Crée une session (ou reprend celle en cours avec un NOUVEAU jeton : l'ancien devient invalide)."""
    if not enabled():
        raise BiometricUnavailable("disabled", "La vérification faciale automatique n'est pas activée : demandez une vérification par l'équipe Tratra.")
    crypto.ensure_configured()                                 # clé de chiffrement obligatoire avant toute capture
    profile = _profile(user)
    ver = BiometricVerification.objects.select_for_update().get_or_create(profile=profile)[0]
    if ver.satisfied:
        raise BiometricError("already_verified", "Votre vérification faciale est déjà satisfaisante.")
    if ver.status == BiometricVerification.REJECTED:
        raise BiometricError("rejected", "Votre vérification a été refusée par l'équipe Tratra : contactez le support pour un recours.")
    if active_consent(user) is None:
        raise BiometricError("consent_required", "Votre consentement explicite est requis avant toute capture.")
    doc = id_document(profile)
    if doc is None:
        raise BiometricError("document_required", "Déposez d'abord votre carte d'identité ou votre passeport.")
    now = timezone.now()
    live = BiometricSession.objects.select_for_update().filter(user=user, status__in=(BiometricSession.CREATED, BiometricSession.CAPTURING), expires_at__gt=now).first()
    if live:                                                   # reprise après interruption : nouveau jeton, captures déjà reçues conservées
        token = _new_token(live)
        live.save(update_fields=["token_hash", "token_uses"])
        audit("biometric.session_resumed", actor=user, target=live)
        return _payload(live, token)
    day = BiometricSession.objects.filter(user=user, created_at__gte=now - timedelta(days=1)).count()
    week = BiometricSession.objects.filter(user=user, created_at__gte=now - timedelta(days=7)).count()
    if day >= settings.BIOMETRIC_MAX_ATTEMPTS_PER_DAY or week >= settings.BIOMETRIC_MAX_ATTEMPTS_PER_WEEK:
        audit("biometric.attempts_limited", actor=user, target=user, day=day, week=week)
        raise BiometricError("too_many_attempts", "Trop de tentatives. Demandez une vérification par l'équipe Tratra ou réessayez demain.", 429)
    session = BiometricSession(verification=ver, user=user, consent=active_consent(user), document=doc, challenges=_challenges(), attempt_no=day + 1,
                               provider=get_provider().name, expires_at=now + timedelta(seconds=int(settings.BIOMETRIC_SESSION_TTL_SECONDS)),
                               thresholds={"liveness": settings.BIOMETRIC_LIVENESS_THRESHOLD, "match": settings.BIOMETRIC_MATCH_THRESHOLD})
    token = _new_token(session)
    session.save()
    ver.status = BiometricVerification.IN_PROGRESS
    ver.save(update_fields=["status", "updated_at"])
    audit("biometric.session_created", actor=user, target=session, attempt=session.attempt_no)
    return _payload(session, token)


def _authorize(user, session_id: int, token: str) -> BiometricSession:
    """Vérifie jeton, propriétaire, expiration et plafond d'usage HORS transaction : l'usage du jeton est compté même si l'appel échoue ensuite."""
    session = BiometricSession.objects.filter(pk=session_id, user=user).first()
    if session is None or not _token_ok(session, token):
        raise BiometricError("invalid_token", "Session de vérification invalide.", 403)
    if session.status in (BiometricSession.EXPIRED, BiometricSession.CANCELLED) or session.expires_at <= timezone.now():
        if session.status in (BiometricSession.CREATED, BiometricSession.CAPTURING):
            BiometricSession.objects.filter(pk=session.pk).update(status=BiometricSession.EXPIRED)
        raise BiometricError("expired", "La session a expiré : relancez la vérification.", 410)
    if session.token_uses >= MAX_TOKEN_USES:
        raise BiometricError("token_exhausted", "Session épuisée : relancez la vérification.", 410)
    BiometricSession.objects.filter(pk=session.pk).update(token_uses=F("token_uses") + 1)
    return session


def add_capture(user, session_id: int, token: str, *, index: int, kind: str, data: bytes) -> Dict:
    session = _authorize(user, session_id, token)
    try:
        with transaction.atomic():
            return _add_capture(session.pk, user, index=index, kind=kind, data=data)
    except BiometricError as exc:
        if exc.flag:
            _flag_id(session.pk, exc.flag)
        raise


def _add_capture(session_id: int, user, *, index: int, kind: str, data: bytes) -> Dict:
    session = BiometricSession.objects.select_for_update().get(pk=session_id)
    if session.status not in (BiometricSession.CREATED, BiometricSession.CAPTURING):
        raise BiometricError("not_capturing", "Cette session n'accepte plus de captures.")
    if not 0 <= index < len(session.challenges) or session.challenges[index] != kind:
        raise BiometricError("wrong_challenge", "Cette capture ne correspond pas à l'étape demandée.", 400)
    if session.captures.filter(index=index).exists():
        raise BiometricError("replayed", "Cette étape a déjà été enregistrée.", 409, flag=None)
    try:
        metrics, problems = quality.analyze(data)
    except quality.CaptureRejected as exc:
        raise BiometricError(exc.code, exc.detail, 422)
    if problems:
        raise BiometricError("poor_quality", quality.MESSAGES[problems[0]], 422, {"problems": problems, "metrics": metrics})
    sha = hashlib.sha256(data).hexdigest()
    if session.captures.filter(sha256=sha).exists():
        raise BiometricError("duplicate_frame", "Deux étapes ne peuvent pas utiliser la même image.", 422, flag="identical_frames")
    if BiometricCapture.objects.filter(sha256=sha).exclude(session__user=user).exists():
        _flag(session, "capture_reused_elsewhere")             # image déjà vue dans la session d'un AUTRE compte : signal fort de rejeu, pas de reconnaissance faciale
    capture = BiometricCapture(session=session, index=index, kind=kind, sha256=sha, size=len(data), quality=metrics)
    capture.file.save(f"{index}.bin", ContentFile(crypto.encrypt(data)), save=False)
    capture.save()
    if session.status == BiometricSession.CREATED:
        session.status = BiometricSession.CAPTURING
        session.save(update_fields=["status"])
    return {"index": index, "captured": list(session.captures.values_list("index", flat=True)), "remaining": len(session.challenges) - session.captures.count()}


def _flag_id(session_id: int, code: str) -> None:
    session = BiometricSession.objects.filter(pk=session_id).first()
    if session is not None:
        _flag(session, code)


def _flag(session: BiometricSession, code: str) -> None:
    if code not in session.anomalies:
        session.anomalies = [*session.anomalies, code]
        session.save(update_fields=["anomalies"])


def read_capture(capture: BiometricCapture) -> bytes:
    """Octets en clair d'une capture (déchiffrés en mémoire, jamais écrits en clair sur disque ni dans le stockage)."""
    with capture.file.open("rb") as fh:
        return crypto.decrypt(fh.read())


def _document_bytes(doc: Optional[HandymanDocument]) -> Optional[bytes]:
    """Image de la pièce (JPEG) pour la comparaison ; un PDF n'est pas comparable automatiquement (revue humaine)."""
    if doc is None:
        return None
    try:
        with doc.file.open("rb") as fh:
            raw = fh.read()
    except (OSError, ValueError):
        return None
    if raw.startswith(b"\xff\xd8\xff"):
        return raw
    if raw.startswith(b"\x89PNG"):
        from PIL import Image

        out = io.BytesIO()
        Image.open(io.BytesIO(raw)).convert("RGB").save(out, "JPEG", quality=92)
        return out.getvalue()
    return None


def decide_outcome(result: ProviderResult, thresholds: Dict) -> str:
    """Décision CÔTÉ SERVEUR à partir d'un résultat RÉEL du fournisseur : jamais favorable sans les deux scores au-dessus des seuils."""
    if set(result.flags) & BAD_FLAGS or result.liveness_passed is False or (result.liveness_score is not None and result.liveness_score < thresholds["liveness"]):
        return "failed"
    if result.liveness_passed is not True or result.liveness_score is None or result.match_score is None or result.match_score < thresholds["match"]:
        return "inconclusive"
    return "passed"


STATUS_FOR = {"passed": BiometricVerification.PASSED, "failed": BiometricVerification.FAILED, "inconclusive": BiometricVerification.INCONCLUSIVE,
              "pending_review": BiometricVerification.PENDING_REVIEW, "provider_error": BiometricVerification.PENDING_REVIEW}


def submit(user, session_id: int, token: str) -> Dict:
    session = _authorize(user, session_id, token)
    try:
        with transaction.atomic():
            return _submit(session.pk, user)
    except BiometricError as exc:
        if exc.flag:
            _flag_id(session.pk, exc.flag)
        raise


def _submit(session_id: int, user) -> Dict:
    session = BiometricSession.objects.select_for_update().select_related("verification").get(pk=session_id)
    if session.status in (BiometricSession.SUBMITTED, BiometricSession.COMPLETED):
        raise BiometricError("already_submitted", "Cette session a déjà été soumise.")
    captures = list(session.captures.filter(deleted_at__isnull=True).order_by("index"))
    if len(captures) != len(session.challenges):
        raise BiometricError("incomplete", "Toutes les étapes doivent être capturées avant l'envoi.", 409, {"remaining": len(session.challenges) - len(captures)})
    span = (captures[-1].created_at - captures[0].created_at).total_seconds()
    if span < MIN_CAPTURE_SPAN_SECONDS:
        _flag(session, "too_fast")
    now = timezone.now()
    session.status, session.submitted_at = BiometricSession.SUBMITTED, now
    provider = get_provider()
    outcome, ver_note = "", ""
    if not provider.configured():
        outcome, ver_note = "pending_review", "no_provider"        # AUCUN fournisseur réel : revue humaine, jamais de validation
    else:
        frames = [(c.kind, read_capture(c)) for c in captures]
        document = _document_bytes(session.document)
        try:
            result = provider.verify(reference=f"tratra-{session.pk}", challenges=session.challenges, frames=frames, document=document)
        except ProviderError:
            outcome, ver_note = "provider_error", "provider_unavailable"
        else:
            session.liveness_passed, session.liveness_score, session.match_score = result.liveness_passed, result.liveness_score, result.match_score
            for f in result.flags:
                _flag(session, f"provider:{f}")
            outcome = decide_outcome(result, session.thresholds)
            if document is None and outcome == "passed":
                outcome = "inconclusive"                           # pièce non comparable automatiquement (PDF) : jamais favorable sans comparaison
                _flag(session, "document_not_comparable")
    session.outcome, session.status, session.completed_at = outcome, BiometricSession.COMPLETED, now
    session.save()
    ver = session.verification
    ver.status = STATUS_FOR[outcome]
    if outcome in ("pending_review", "provider_error"):
        ver.human_review_requested_at, ver.human_review_reason = now, ver_note
    ver.save()
    audit("biometric.session_submitted", actor=user, target=session, outcome=outcome, provider=session.provider, anomalies=session.anomalies)
    from biometrics import fraud

    fraud.after_session(session)
    _reevaluate(session.verification.profile)
    return {"outcome": outcome, "status": ver.status, "status_label": ver.get_status_display(), "human_review": outcome in ("pending_review", "provider_error")}


def _reevaluate(profile) -> None:
    try:
        from trust import engine

        engine.evaluate_profile(profile, trigger="biometric")
    except Exception:  # noqa: BLE001 - la réévaluation ne doit jamais faire échouer la soumission
        pass


@transaction.atomic
def request_human_review(user, reason: str = "other") -> BiometricVerification:
    """Alternative accessible : le dossier passe EN ATTENTE d'une vérification par l'équipe, sans capture biométrique."""
    profile = _profile(user)
    ver = BiometricVerification.objects.select_for_update().get_or_create(profile=profile)[0]
    if ver.satisfied:
        raise BiometricError("already_verified", "Votre vérification est déjà satisfaisante.")
    if reason not in ("camera_refused", "accessibility", "provider_unavailable", "other"):
        reason = "other"
    ver.status, ver.human_review_requested_at, ver.human_review_reason = BiometricVerification.PENDING_REVIEW, timezone.now(), reason
    ver.save()
    BiometricSession.objects.filter(user=user, status__in=(BiometricSession.CREATED, BiometricSession.CAPTURING)).update(status=BiometricSession.CANCELLED)
    audit("biometric.human_review_requested", actor=user, target=user, reason=reason)
    return ver


# ═══ Expiration et conservation ══════════════════════════════════════════════════════════════════════════════════════

def _delete_captures(qs) -> int:
    n = 0
    for capture in list(qs):
        try:
            capture.file.delete(save=False)
        except Exception:  # noqa: BLE001 - fichier déjà absent ou stockage indisponible : la ligne est tout de même marquée supprimée
            pass
        capture.deleted_at = timezone.now()
        capture.save(update_fields=["deleted_at"])
        n += 1
    return n


def expire_and_purge(now=None) -> Dict[str, int]:
    """Tâche horaire (rejouable) : expire les sessions abandonnées et supprime les captures arrivées au terme de leur conservation."""
    now = now or timezone.now()
    expired = BiometricSession.objects.filter(status__in=(BiometricSession.CREATED, BiometricSession.CAPTURING), expires_at__lte=now).update(status=BiometricSession.EXPIRED)
    keep = timedelta(days=int(settings.BIOMETRIC_RETENTION_DAYS))
    abandoned = timedelta(days=2)
    from django.db.models import Q

    due = BiometricCapture.objects.filter(deleted_at__isnull=True).filter(
        Q(session__status=BiometricSession.COMPLETED, session__completed_at__lte=now - keep)
        | Q(session__status__in=(BiometricSession.EXPIRED, BiometricSession.CANCELLED), session__expires_at__lte=now - abandoned))
    return {"expired": expired, "captures_deleted": _delete_captures(due)}


# ═══ Décisions humaines (Back-Office) ════════════════════════════════════════════════════════════════════════════════

DECISION_STATUS = {"approve_manual": BiometricVerification.MANUAL_APPROVED, "approve_alternative": BiometricVerification.ALTERNATIVE_APPROVED, "reject": BiometricVerification.REJECTED,
                   "request_recapture": BiometricVerification.RECAPTURE, "request_documents": BiometricVerification.DOCUMENTS, "open_review": BiometricVerification.PENDING_REVIEW}
USER_MESSAGE = {
    "approve_manual": ("Vérification d'identité validée", "Votre vérification faciale a été validée par l'équipe Tratra."),
    "approve_alternative": ("Vérification d'identité validée", "Votre vérification d'identité a été validée par l'équipe Tratra."),
    "reject": ("Vérification d'identité refusée", "Votre vérification faciale n'a pas pu être validée. Vous pouvez contacter le support pour un recours."),
    "request_recapture": ("Nouvelle capture demandée", "Merci de refaire la vérification faciale dans l'application."),
    "request_documents": ("Pièces complémentaires demandées", "Merci d'envoyer les pièces demandées dans Vérification d'identité."),
}


@transaction.atomic
def decide(verification: BiometricVerification, *, by, decision: str, reason: str) -> BiometricVerification:
    verification = BiometricVerification.objects.select_for_update().select_related("profile__user").get(pk=verification.pk)
    reason = (reason or "").strip()
    if decision not in DECISION_STATUS:
        raise BiometricError("decision", "Décision inconnue.", 400)
    if len(reason) < 10:
        raise BiometricError("reason_required", "Un motif d'au moins 10 caractères est obligatoire.", 400)
    if decision in ("approve_manual", "approve_alternative"):
        missing = approval_checks(verification)
        if missing:
            raise BiometricError("checks_required", "Contrôles requis avant approbation : " + "; ".join(missing), 409, {"missing": missing})
    verification.status, verification.decided_by, verification.decision_reason, verification.decided_at = DECISION_STATUS[decision], by, reason[:1000], timezone.now()
    if decision == "open_review" and verification.human_review_requested_at is None:
        verification.human_review_requested_at = timezone.now()
    verification.save()
    BiometricDecision.objects.create(verification=verification, actor=by, decision=decision, reason=reason[:1000])
    user = verification.profile.user
    if decision in USER_MESSAGE:
        title, text = USER_MESSAGE[decision]
        notify(user, "system", text, title=title, dedupe_key=f"biometric:{verification.pk}:{decision}:{verification.decisions.count()}")
    _reevaluate(verification.profile)
    return verification


def approval_checks(verification: BiometricVerification) -> List[str]:
    """Contrôles requis avant d'approuver : pièce d'identité approuvée, aucun dossier de risque actif lié à la biométrie."""
    from intelligence.models import RiskCase

    missing = []
    profile = verification.profile
    if not profile.documents.filter(document_type="id_card", status="approved").exists():
        missing.append("pièce d'identité non approuvée")
    if RiskCase.objects.filter(subject=profile.user, kind__in=("liveness_bypass", "biometric_attempts", "biometric_technical"), status__in=RiskCase.ACTIVE).exists():
        missing.append("dossier de risque biométrique encore actif")
    return missing
