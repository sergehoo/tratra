"""Parcours guidé « Vérifier mon identité » (7 étapes). La progression est enregistrée ICI (`KycDossier`) : l’application l’affiche et la
reprend après une fermeture, elle ne décide rien.

 1 personal    Informations personnelles : nom et prénoms tels qu'ils figurent sur la pièce, date de naissance
 2 document    Choix de la pièce : carte nationale d'identité (recto + verso) ou passeport (page photo)
 3 capture     Photo de la pièce avec la caméra
 4 quality     Contrôle qualité (netteté, lumière, résolution) et lecture automatique, puis transmission à l'équipe
 5 face        Vérification faciale SEULEMENT si elle est activée (BIOMETRIC_ENABLED), avec consentement explicite ; sinon l'équipe vérifie
 6 review      Revue humaine des pièces par l'équipe Tratra : aucune validation automatique
 7 activation  Activation du profil professionnel : règle unique `handy.eligibility`

Aucun second système de vérification : les photos transmises deviennent des pièces `HandymanDocument` (« id_card », comme le module de
vérification faciale), revues dans la file KYC du Back-Office ; la lecture réutilise `intelligence.documents` ; la vérification faciale est
LUE dans `biometrics` (jamais modifiée ici). Le texte lu sur une pièce n'est jamais conservé : seulement des indicateurs.
"""
from datetime import date
from typing import Dict, List, Optional

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from handy.models import HandymanDocument, HandymanProfile, KycDossier

STEPS = [
    ("personal", "Informations personnelles"),
    ("document", "Choix de la pièce"),
    ("capture", "Photo de la pièce"),
    ("quality", "Contrôle qualité et lecture"),
    ("face", "Vérification faciale"),
    ("review", "Revue par l’équipe Tratra"),
    ("activation", "Activation du profil professionnel"),
]
SIDES = {"cni": ["front", "back"], "passport": ["front"]}
SIDE_LABELS = {("cni", "front"): "Recto", ("cni", "back"): "Verso", ("passport", "front"): "Page photo"}
DOC_TITLES = {("cni", "front"): "Carte nationale d’identité — recto", ("cni", "back"): "Carte nationale d’identité — verso",
              ("passport", "front"): "Passeport — page photo"}
# Défauts d’image : (message, bloquant). Bloquant = la pièce ne pourrait pas être examinée ; sinon « reprendre » est seulement conseillé.
QUALITY = {
    "unreadable": ("Image illisible : reprenez la photo.", True),
    "low_resolution": ("Résolution insuffisante : rapprochez-vous de la pièce et utilisez l’appareil photo arrière.", True),
    "too_dark": ("Photo trop sombre : placez-vous près d’une fenêtre ou d’une lampe.", False),
    "overexposed": ("Reflet ou surexposition : évitez le flash et la lumière directe sur la pièce.", False),
    "blurry": ("Photo floue : tenez le téléphone immobile et attendez la mise au point.", False),
}
IMAGE_SIGNATURES = ((b"\xff\xd8\xff", "image/jpeg", ".jpg"), (b"\x89PNG\r\n\x1a\n", "image/png", ".png"))


class KycFlowError(Exception):
    def __init__(self, code: str, detail: str, status: int = 400):
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def profile_of(user) -> HandymanProfile:
    profile = HandymanProfile.objects.filter(user=user).select_related("user").first()
    if profile is None:
        raise KycFlowError("no_profile", "Créez d’abord votre profil professionnel pour vérifier votre identité.", 409)
    return profile


def dossier_for(profile: HandymanProfile) -> KycDossier:
    """Dossier du profil (créé à la première visite, pré-rempli avec le nom du compte)."""
    dossier, _ = KycDossier.objects.get_or_create(
        profile=profile, defaults={"legal_first_name": (profile.user.first_name or "").strip()[:150],
                                   "legal_last_name": (profile.user.last_name or "").strip()[:150]})
    return dossier


# ═══ Revue humaine (lue sur les pièces) ════════════════════════════════════════════════════════════════════════════════

def _reason(docs) -> str:
    reasons = [r for r in dict.fromkeys((d.rejection_reason or "").strip() for d in docs if d.status == "rejected") if r]
    return " ".join(reasons) or "Votre pièce n’a pas pu être validée. Reprenez des photos nettes et complètes."


def review_state(profile: HandymanProfile, dossier: Optional[KycDossier]) -> Dict:
    """none | pending | rejected | approved.

    - une pièce d'identité approuvée suffit (même règle que l'éligibilité) ;
    - sinon la dernière transmission du parcours décide : une face refusée = nouvelle pièce demandée ;
    - une nouvelle tentative en cours dans le parcours (photos reprises après un refus) repart de « none » ;
    - à défaut, les pièces d’identité déposées avant le parcours guidé (écran historique des documents)."""
    if profile.has_required_kyc():
        return {"state": "approved", "reason": ""}
    if dossier is not None and dossier.sent_at:
        docs = list(dossier.documents.all())
        if any(d.status == "rejected" for d in docs):
            return {"state": "rejected", "reason": _reason(docs)}
        return {"state": "pending", "reason": ""}
    if dossier is not None and (dossier.attempts or dossier.front or dossier.back):
        return {"state": "none", "reason": ""}
    docs = list(HandymanDocument.objects.filter(handyman=profile, document_type="id_card").order_by("-uploaded_at")[:2])
    if any(d.status == "pending" for d in docs):
        return {"state": "pending", "reason": ""}
    if docs and docs[0].status == "rejected":
        return {"state": "rejected", "reason": _reason(docs[:1])}
    return {"state": "none", "reason": ""}


def _previous_reason(profile: HandymanProfile) -> str:
    """Motif du dernier refus DÉCIDÉ par l’équipe sur une pièce d’identité (rappelé pendant la nouvelle tentative) ; les retraits
    automatiques d’un envoi remplacé ne sont pas des refus."""
    last = (HandymanDocument.objects.filter(handyman=profile, document_type="id_card", status="rejected").exclude(rejection_reason=SUPERSEDED_REASON)
            .order_by("-reviewed_at", "-uploaded_at").first())
    return (last.rejection_reason or "").strip() if last is not None else ""


def kyc_status(profile: HandymanProfile) -> Dict:
    """État d’identité affiché partout (profil, tableau de bord, parcours) : draft | pending | rejected | approved."""
    dossier = KycDossier.objects.filter(profile=profile).first()
    review = review_state(profile, dossier)
    state = {"none": "draft"}.get(review["state"], review["state"])
    labels = {"draft": "Identité non vérifiée", "pending": "Vérification en cours", "rejected": "Nouvelle pièce demandée", "approved": "Identité vérifiée"}
    return {"status": state, "label": labels[state], "reason": review["reason"] or None, "started": bool(dossier and (dossier.document_kind or dossier.front))}


# ═══ Vérification faciale (lue, jamais modifiée) ═══════════════════════════════════════════════════════════════════════

def _face(profile: HandymanProfile, dossier: KycDossier) -> Dict:
    from biometrics import services as bio
    from biometrics.models import BiometricVerification

    ver = BiometricVerification.objects.filter(profile=profile).first()
    status = ver.status if ver else BiometricVerification.NOT_STARTED
    enabled = bio.enabled()
    human = bool(ver and ver.human_review_requested_at)
    done = (not enabled) or bool(ver and ver.satisfied) or status == BiometricVerification.PENDING_REVIEW or human
    return {"enabled": enabled, "required": False, "status": status, "satisfied": bool(ver and ver.satisfied), "choice": dossier.face_choice,
            "human_review_requested": human, "done": done,
            "note": ("Comparez votre visage à votre pièce, après votre consentement explicite, ou demandez une vérification par l’équipe."
                     if enabled else "Non requise : l’équipe Tratra vérifie votre pièce elle-même.")}


# ═══ Contrôle qualité et lecture d’une photo ═══════════════════════════════════════════════════════════════════════════

def _read(upload) -> tuple:
    size = getattr(upload, "size", None) or 0
    limit = settings.KYC_MAX_UPLOAD_BYTES
    if size > limit:
        raise KycFlowError("too_large", f"Photo trop lourde : {limit // (1024 * 1024)} Mo au maximum.", 413)
    upload.seek(0)
    data = upload.read(limit + 1)
    if len(data) > limit:
        raise KycFlowError("too_large", f"Photo trop lourde : {limit // (1024 * 1024)} Mo au maximum.", 413)
    kind = next(((mime, ext) for sig, mime, ext in IMAGE_SIGNATURES if data.startswith(sig)), None)
    if not data or kind is None:
        raise KycFlowError("unsupported_type", "Photo non reconnue : prenez la pièce en photo (JPEG ou PNG).")
    return data, kind[0], kind[1]


def check_photo(data: bytes, mime: str, dossier: KycDossier, side: str) -> Dict:
    """Qualité mesurée (`intelligence.documents`) et lecture automatique INDICATIVE : seuls des indicateurs sont renvoyés et conservés."""
    from intelligence import documents

    problems = [{"code": c, "label": QUALITY[c][0], "blocking": QUALITY[c][1]} for c in documents.image_quality_problems(data)]
    reading = {"status": "unavailable", "notes": []}
    if getattr(settings, "KYC_FLOW_OCR", True) and documents.local_ocr_available():
        text = documents.local_ocr(data, mime)
        fields = documents.extract_fields(text) if text else {}
        del text                                                    # le texte lu n'est jamais conservé
        reading["status"] = "read" if len([k for k in fields if k != "detected_type"]) >= 1 else "unread"
        notes = reading["notes"]
        detected = fields.get("detected_type")
        if detected == "passport" and dossier.document_kind == "cni":
            notes.append("La pièce ressemble à un passeport : vérifiez le type de pièce choisi.")
        elif detected == "id_card" and dossier.document_kind == "passport":
            notes.append("La pièce ressemble à une carte d’identité : vérifiez le type de pièce choisi.")
        try:
            expiry = date.fromisoformat(str(fields.get("expiry_date") or ""))
        except ValueError:
            expiry = None
        if expiry and expiry < timezone.localdate():
            notes.append(f"La date d’expiration lue ({expiry:%d/%m/%Y}) semble dépassée : une pièce en cours de validité est nécessaire.")
        doc_name = f"{fields.get('given_names', '')} {fields.get('surname', '')}".strip()
        legal = f"{dossier.legal_first_name} {dossier.legal_last_name}".strip()
        if doc_name and legal and documents.name_similarity(doc_name, legal) < documents.NAME_WARN:
            notes.append("Le nom lu ne correspond pas exactement à celui saisi : vérifiez l’étape « Informations personnelles ».")
    blocking = any(p["blocking"] for p in problems)
    return {"side": side, "quality": "fail" if blocking else "warn" if problems else "ok", "problems": problems, "reading": reading,
            "checked_at": timezone.now().isoformat()}


# ═══ État complet du parcours ══════════════════════════════════════════════════════════════════════════════════════════

def _personal_errors(first: str, last: str, birth: Optional[date]) -> Dict[str, str]:
    errors = {}
    if len(first.strip()) < 2:
        errors["first_name"] = "Indiquez vos prénoms tels qu’ils figurent sur la pièce."
    if len(last.strip()) < 2:
        errors["last_name"] = "Indiquez votre nom tel qu’il figure sur la pièce."
    if birth is None:
        errors["birth_date"] = "Indiquez votre date de naissance."
    else:
        today = timezone.localdate()
        age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
        minimum = int(getattr(settings, "KYC_MIN_AGE", 18))
        if birth >= today or age > 110:
            errors["birth_date"] = "Date de naissance invalide."
        elif age < minimum:
            errors["birth_date"] = f"Vous devez avoir au moins {minimum} ans pour proposer vos services."
    return errors


def _captures(dossier: KycDossier, *, retake: bool = False) -> List[Dict]:
    """Photos de la pièce choisie. `retake` : pièce refusée par l’équipe, les photos transmises ne valent plus (« à reprendre »)."""
    out = []
    for side in SIDES.get(dossier.document_kind, []):
        check = {} if retake else (dossier.front_check if side == "front" else dossier.back_check) or {}
        out.append({"side": side, "label": SIDE_LABELS[(dossier.document_kind, side)], "present": bool(getattr(dossier, side)) and not retake,
                    "quality": check.get("quality"), "problems": check.get("problems", []), "reading": check.get("reading")})
    return out


def state(user) -> Dict:
    from handy.eligibility import eligibility_summary

    profile = profile_of(user)
    dossier = dossier_for(profile)
    review = review_state(profile, dossier)
    sent = review["state"] in ("pending", "approved")                 # pièce déjà entre les mains de l’équipe (ou validée)
    captures = _captures(dossier, retake=review["state"] == "rejected")
    personal_ok = not _personal_errors(dossier.legal_first_name, dossier.legal_last_name, dossier.birth_date)
    captured = bool(captures) and all(c["present"] for c in captures)
    quality_ok = captured and not any(c["quality"] == "fail" for c in captures)
    face = _face(profile, dossier)
    eligibility = eligibility_summary(profile)
    done = {
        "personal": personal_ok or sent,
        "document": bool(dossier.document_kind) or sent,
        "capture": captured or sent,
        "quality": sent,
        "face": face["done"] and sent,
        "review": review["state"] == "approved",
        "activation": eligibility["publication"]["authorized"],
    }
    steps, current = [], None
    for key, label in STEPS:
        if key == "face" and not face["enabled"]:
            st = "skipped"
        elif key == "capture" and review["state"] == "rejected":
            st = "error"                                            # nouvelle pièce demandée : on reprend les photos
        elif done[key]:
            st = "done"
        elif key == "review" and review["state"] == "pending":
            st = "waiting"
        else:
            st = "todo"
        if current is None and st in ("todo", "error", "waiting"):
            current = key
            st = st if st != "todo" else "current"
        steps.append({"key": key, "label": label, "state": st})
    status = {"none": "draft", "pending": "in_review", "rejected": "changes_requested", "approved": "verified"}[review["state"]]
    return {
        "status": status,
        "status_label": {"draft": "À compléter", "in_review": "En cours de revue", "changes_requested": "Nouvelle pièce demandée",
                         "verified": "Identité vérifiée"}[status],
        "current_step": current or "activation",
        "steps": steps,
        "personal": {"first_name": dossier.legal_first_name, "last_name": dossier.legal_last_name,
                     "birth_date": dossier.birth_date.isoformat() if dossier.birth_date else None, "complete": personal_ok},
        "document": {"kind": dossier.document_kind or None, "kinds": [{"value": v, "label": l, "sides": len(SIDES[v])} for v, l in KycDossier.DOC_KINDS],
                     "captures": captures, "ready_to_send": quality_ok and personal_ok and not sent},
        "face": face,
        "review": {**review, "sent_at": dossier.sent_at.isoformat() if dossier.sent_at else None, "attempts": dossier.attempts,
                   "previous_reason": (_previous_reason(profile) or None) if review["state"] == "none" and dossier.attempts else None},
        "activation": eligibility,
        "editable": not sent,
        "updated_at": dossier.updated_at.isoformat(),
    }


# ═══ Actions ═══════════════════════════════════════════════════════════════════════════════════════════════════════════

def _editable(profile: HandymanProfile, dossier: KycDossier) -> None:
    """Refuse toute modification d’une pièce validée ou en revue ; après un refus, rouvre le dossier pour une nouvelle tentative."""
    review = review_state(profile, dossier)["state"]
    if review == "approved":
        raise KycFlowError("already_verified", "Votre identité est déjà vérifiée.", 409)
    if review == "pending":
        raise KycFlowError("in_review", "Votre pièce est en cours de revue par l’équipe Tratra : elle ne peut pas être modifiée pour l’instant.", 409)
    if review == "rejected" and dossier.sent_at:
        _reopen(dossier)


SUPERSEDED_REASON = "Remplacée par un nouvel envoi de l’artisan (parcours « Vérifier mon identité »)."


def _reopen(dossier: KycDossier) -> None:
    """Nouvelle tentative : informations saisies et type de pièce gardés, nouvelles photos demandées (toutes les faces : une pièce se
    revoit en entier). Rien n'est supprimé : les pièces de l'envoi précédent restent dans l'historique du dossier KYC ; celles encore
    « en attente » sont retirées de la file de l’examinateur (motif explicite, sans notification à l’artisan : ce n’est pas une décision)."""
    from trust.models import audit

    stale = list(dossier.documents.filter(status="pending").values_list("pk", flat=True))
    if stale:
        HandymanDocument.objects.filter(pk__in=stale).update(status="rejected", rejection_reason=SUPERSEDED_REASON, reviewed_at=timezone.now())
        audit("kyc.identity_superseded", actor=dossier.profile.user, target=dossier.profile.user, documents=stale)
    dossier.front, dossier.back, dossier.front_check, dossier.back_check, dossier.sent_at = "", "", {}, {}, None
    dossier.save(update_fields=["front", "back", "front_check", "back_check", "sent_at", "updated_at"])
    dossier.documents.clear()


@transaction.atomic
def update(user, data: Dict) -> Dict:
    """Enregistre l’étape 1 (informations personnelles), l’étape 2 (type de pièce) ou le choix de l’étape 5, sans rien transmettre."""
    profile = profile_of(user)
    dossier = KycDossier.objects.select_for_update().get(pk=dossier_for(profile).pk)
    fields = []
    if "face_choice" in data:
        choice = str(data.get("face_choice") or "")
        if choice not in dict(KycDossier.FACE_CHOICES):
            raise KycFlowError("invalid", "Choix inconnu.")
        dossier.face_choice = choice
        fields.append("face_choice")
    personal = data.get("personal")
    kind = data.get("document_kind")
    if personal is not None or kind is not None:
        _editable(profile, dossier)
    if personal is not None:
        if not isinstance(personal, dict):
            raise KycFlowError("invalid", "Informations personnelles invalides.")
        first, last = str(personal.get("first_name") or "").strip()[:150], str(personal.get("last_name") or "").strip()[:150]
        try:
            birth = date.fromisoformat(str(personal.get("birth_date") or ""))
        except ValueError:
            birth = None
        errors = _personal_errors(first, last, birth)
        if errors:
            exc = KycFlowError("invalid_personal", "Vérifiez les informations saisies.")
            exc.fields = errors
            raise exc
        dossier.legal_first_name, dossier.legal_last_name, dossier.birth_date = first, last, birth
        fields += ["legal_first_name", "legal_last_name", "birth_date"]
    if kind is not None:
        if kind not in SIDES:
            raise KycFlowError("invalid_kind", "Choisissez une carte nationale d’identité ou un passeport.")
        if kind != dossier.document_kind:                           # autre pièce : les photos de l'ancienne ne valent plus
            dossier.document_kind = kind
            dossier.front, dossier.back, dossier.front_check, dossier.back_check = "", "", {}, {}
            fields += ["document_kind", "front", "back", "front_check", "back_check"]
    if fields:
        dossier.save(update_fields=[*dict.fromkeys(fields), "updated_at"])
    return state(user)


@transaction.atomic
def capture(user, side: str, upload) -> Dict:
    """Étapes 3 et 4 : enregistre la photo d’une face (remplace la précédente non transmise) et renvoie son contrôle qualité / lecture."""
    profile = profile_of(user)
    dossier = KycDossier.objects.select_for_update().get(pk=dossier_for(profile).pk)
    _editable(profile, dossier)
    if not dossier.document_kind:
        raise KycFlowError("no_kind", "Choisissez d’abord le type de pièce.", 409)
    if side not in SIDES[dossier.document_kind]:
        raise KycFlowError("invalid_side", "Cette face n’est pas demandée pour la pièce choisie.")
    if upload is None:
        raise KycFlowError("no_file", "Ajoutez la photo de la pièce.")
    data, mime, ext = _read(upload)
    check = check_photo(data, mime, dossier, side)
    getattr(dossier, side).save(f"capture{ext}", ContentFile(data), save=False)
    setattr(dossier, f"{side}_check", check)
    dossier.save(update_fields=[side, f"{side}_check", "updated_at"])
    return {**state(user), "check": check}


@transaction.atomic
def send(user) -> Dict:
    """Fin de l’étape 4 : les photos deviennent des pièces « en attente » dans la file KYC de l’équipe ; l’analyse assistée est lancée."""
    from trust.models import audit

    profile = profile_of(user)
    dossier = KycDossier.objects.select_for_update().get(pk=dossier_for(profile).pk)
    _editable(profile, dossier)
    if _personal_errors(dossier.legal_first_name, dossier.legal_last_name, dossier.birth_date):
        raise KycFlowError("personal_incomplete", "Complétez d’abord vos informations personnelles.", 409)
    captures = _captures(dossier)
    if not captures or not all(c["present"] for c in captures):
        missing = ", ".join(c["label"].lower() for c in captures if not c["present"]) or "pièce"
        raise KycFlowError("capture_missing", f"Photo manquante : {missing}.", 409)
    if any(c["quality"] == "fail" for c in captures):
        raise KycFlowError("quality_failed", "Une photo n’est pas exploitable : reprenez-la avant de l’envoyer.", 409)
    created = []
    for side in SIDES[dossier.document_kind]:
        doc = HandymanDocument(handyman=profile, document_type="id_card", status="pending", title=DOC_TITLES[(dossier.document_kind, side)],
                               description="Transmis par le parcours « Vérifier mon identité ».")
        doc.file.name = getattr(dossier, side).name                # même fichier privé : aucune copie
        doc.save()
        created.append(doc)
    dossier.documents.set(created)
    dossier.sent_at = timezone.now()
    dossier.attempts += 1
    dossier.save(update_fields=["sent_at", "attempts", "updated_at"])
    ids = [d.pk for d in created]
    audit("kyc.identity_sent", actor=user, target=user, documents=ids, kind=dossier.document_kind, attempt=dossier.attempts)
    transaction.on_commit(lambda: _queue_analysis(ids))
    return state(user)


def _queue_analysis(ids: List[int]) -> None:
    import logging

    from intelligence.tasks import analyze_document

    for pk in ids:
        try:
            analyze_document.delay(pk)
        except Exception:  # noqa: BLE001 - file de tâches indisponible : l'examinateur lance l'analyse depuis le Back-Office
            logging.getLogger(__name__).warning("Analyse de la pièce %s non programmée", pk)


@transaction.atomic
def restart(user) -> Dict:
    """Nouvelle pièce après un refus (voir `_reopen`)."""
    profile = profile_of(user)
    dossier = KycDossier.objects.select_for_update().get(pk=dossier_for(profile).pk)
    if review_state(profile, dossier)["state"] != "rejected":
        raise KycFlowError("not_rejected", "Aucune nouvelle pièce n’est demandée pour le moment.", 409)
    _reopen(dossier)
    return state(user)
