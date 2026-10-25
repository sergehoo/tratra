"""Documents de contrat ANTI-FALSIFICATION : émission, signature des parties, scellement, vérification publique.

Chaque document émis (`ContractDocument`, jamais modifié ni supprimé — déclencheur PostgreSQL) porte :
 - une référence unique TRT-CTR-AAAA-NNNNNN (avenants : même référence suivie de -AVn ; l'original n'est jamais modifié) ;
 - un QR code vers la page publique de vérification, avec un JETON aléatoire de 256 bits (seule son empreinte est en base) ;
 - l'empreinte SHA-256 du fichier PDF final et la signature numérique Ed25519 de la plateforme sur {référence, type, étape,
   version, empreinte du PDF, empreinte des conditions, date d'émission} (engagements/signing.py, clés publiques publiées) ;
 - sa version, son horodatage, et chaque événement dans l'historique du contrat et le journal d'audit.

Étapes : « à signer » (émis quand les deux parties ont accepté les conditions) → chaque partie signe (signature électronique simple :
compte, date, heure, empreinte du document signé) → « final » (bloc de signatures, scellé) : le contrat passe « Signé ».
La vérification publique ne révèle AUCUNE donnée personnelle : ni nom, ni montant, ni adresse, ni téléphone."""
import hashlib
import re
import secrets
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from engagements import contract_pdf, pdf, signing

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
ROLE_LABELS = {"employment": ("Employeur", "Salarié(e)"), "independent": ("Client", "Prestataire")}
# Statut public du contrat : libellés génériques, sans détail des conditions.
PUBLIC_STATUS = {"draft": "en préparation", "pending_acceptance": "en préparation", "accepted": "en cours de signature",
                 "signed": "signé, pas encore commencé", "active": "en vigueur", "suspended": "suspendu", "notice": "en préavis",
                 "terminated": "résilié", "completed": "terminé", "cancelled": "annulé"}


class DocumentError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def verify_url(token: str) -> str:
    return f"{settings.PUBLIC_WEB_URL.rstrip('/')}/verify/contract/{token}"


def allocate_reference(year: int) -> str:
    """TRT-CTR-AAAA-NNNNNN : compteur annuel incrémenté sous verrou (jamais deux fois le même numéro, même en concurrence)."""
    from engagements.models import ContractReferenceCounter

    with transaction.atomic():
        ContractReferenceCounter.objects.get_or_create(year=year)
        counter = ContractReferenceCounter.objects.select_for_update().get(year=year)
        counter.last = F("last") + 1
        counter.save(update_fields=["last"])
        counter.refresh_from_db(fields=["last"])
    return f"TRT-CTR-{year}-{counter.last:06d}"


def ensure_reference(contract) -> str:
    if not contract.reference:
        type(contract).objects.filter(pk=contract.pk, reference__isnull=True).update(reference=allocate_reference(timezone.now().year))
        contract.refresh_from_db(fields=["reference"])
    return contract.reference


def _payload(doc_fields: Dict) -> Dict:
    return {k: doc_fields[k] for k in ("reference", "kind", "stage", "version", "sha256", "terms_hash", "issued_at")}


def _fmt(dt: datetime) -> str:
    return timezone.localtime(dt).strftime("%d/%m/%Y à %H:%M")


def _person(user) -> str:
    return " ".join(p for p in ((user.first_name or "").strip(), (user.last_name or "").strip()) if p) or "Membre Tratra"


def issue(contract, *, kind: str = "contract", stage: str = "for_signature", amendment=None, actor=None):
    """Émet, scelle et enregistre un document. Renvoie le document (le jeton de vérification n'existe en clair que dans le PDF)."""
    from engagements.models import ContractDocument, ContractEvent, ContractSignature
    from trust.models import audit

    ensure_reference(contract)
    issued_at = timezone.now().replace(microsecond=0)
    token = secrets.token_urlsafe(32)
    url = verify_url(token)
    key = signing.active_key()                       # la clé imprimée dans le document est celle qui le scelle
    if kind == "amendment":
        original = contract.documents.filter(kind="contract", stage="final").order_by("-issued_at").first()
        if original is None:
            raise DocumentError("no_original", "Aucun contrat signé : l'avenant ne peut pas être scellé.", 409)
        n = contract.documents.filter(kind="amendment").count() + 1
        reference, parent = f"{contract.reference}-AV{n}", original
        data = contract_pdf.render_amendment(contract, amendment, original, number=n, reference=reference, issued_at=issued_at, url=url, kid=key.kid)
    else:
        reference, parent = contract.reference, None
        signatures, signed_sha = [], ""
        if stage == "final":
            source = contract.documents.filter(kind="contract", stage="for_signature", version=contract.terms_version).order_by("-issued_at").first()
            signatures = list(ContractSignature.objects.filter(document=source).select_related("user").order_by("role")) if source else []
            signed_sha, parent = (source.sha256 if source else ""), source
        data = contract_pdf.render_contract(contract, stage=stage, reference=reference, issued_at=issued_at, url=url, kid=key.kid,
                                            signatures=signatures, signed_sha=signed_sha)
    # Scellement INCHANGÉ : empreinte SHA-256 des octets du PDF final, puis signature Ed25519 de la charge utile canonique.
    fields = {"reference": reference, "kind": kind, "stage": stage, "version": contract.terms_version, "sha256": pdf.sha256(data),
              "terms_hash": contract.terms_hash, "issued_at": issued_at.isoformat()}
    kid, signature = signing.sign(_payload(fields), key=key)
    doc = ContractDocument(contract=contract, kind=kind, stage=stage, reference=reference, version=contract.terms_version, parent=parent,
                           amendment=amendment, sha256=fields["sha256"], size=len(data), terms_hash=contract.terms_hash,
                           token_hash=_hash_token(token), signing_key_id=kid, signature=signature, issued_at=issued_at, issued_by=actor)
    doc.file.save(f"{uuid.uuid4().hex}.pdf", ContentFile(data), save=False)
    doc.save()
    ContractEvent.objects.create(contract=contract, actor=actor, type=f"document.{kind}.{stage}",
                                 data={"reference": reference, "version": doc.version, "sha256": doc.sha256, "kid": kid})
    audit("contract.document_issued", actor=actor, target_type="engagement_contract", target_id=contract.pk, reference=reference,
          kind=kind, stage=stage, sha256=doc.sha256, kid=kid)
    return doc


def revoke(document, *, actor, reason: str):
    """Révocation (document émis par erreur, fraude) : SEULS les champs de révocation changent ; le fichier et l'empreinte restent."""
    from engagements.models import ContractDocument, ContractEvent
    from trust.models import audit

    if not (reason or "").strip():
        raise DocumentError("reason_required", "Indiquez le motif de la révocation.")
    if document.revoked_at is None:
        ContractDocument.objects.filter(pk=document.pk, revoked_at__isnull=True).update(revoked_at=timezone.now(), revoked_reason=reason[:500],
                                                                                         revoked_by=actor)
        document.refresh_from_db()
        ContractEvent.objects.create(contract=document.contract, actor=actor, type="document.revoked",
                                     data={"reference": document.reference, "reason": reason[:500]})
        audit("contract.document_revoked", actor=actor, target_type="engagement_contract", target_id=document.contract_id,
              reference=document.reference, reason=reason[:500])
    return document


# ── Vérification publique ────────────────────────────────────────────────────────────────────────────────────────────

def _signature_check(doc) -> Dict:
    fields = {"reference": doc.reference, "kind": doc.kind, "stage": doc.stage, "version": doc.version, "sha256": doc.sha256,
              "terms_hash": doc.terms_hash, "issued_at": doc.issued_at.isoformat()}
    return signing.verify(_payload(fields), doc.signature, doc.signing_key_id)


def stored_file_intact(doc) -> bool:
    """Le fichier conservé correspond-il toujours à son empreinte (stockage non altéré) ?"""
    try:
        with doc.file.open("rb") as fh:
            return pdf.sha256(fh.read()) == doc.sha256
    except (OSError, ValueError):
        return False


def seal_payload(doc) -> Dict:
    """Charge utile EXACTE scellée par Tratra (à sérialiser en JSON canonique pour vérifier la signature avec la clé publique)."""
    return _payload({"reference": doc.reference, "kind": doc.kind, "stage": doc.stage, "version": doc.version, "sha256": doc.sha256,
                     "terms_hash": doc.terms_hash, "issued_at": doc.issued_at.isoformat()})


def public_result(doc, *, check_file: bool = True) -> Dict:
    """Ce que n'importe qui peut savoir d'un document : authenticité, état, empreinte, scellement. Aucune donnée personnelle.

    Deux notions DISTINCTES : le SCELLEMENT de la plateforme (Ed25519, prouve que Tratra a émis ce fichier exact) et les SIGNATURES
    électroniques simples des parties (acceptation du document : indiquées sans nom)."""
    contract = doc.contract
    check = _signature_check(doc)
    newer_final = None
    if doc.kind == "contract" and doc.stage == "for_signature":
        # Une fois le contrat final émis, la version à signer reste « remplacée », même si ce final est révoqué ensuite
        # (sinon le brouillon redeviendrait « authentique » et pourrait être présenté comme le contrat en vigueur).
        newer_final = contract.documents.filter(kind="contract", stage="final", version=doc.version).first()
    if doc.revoked_at:
        state, label = "revoked", "Document révoqué par Tratra"
    elif check_file and not stored_file_intact(doc):
        state, label = "altered", "Le fichier conservé par Tratra ne correspond plus à son empreinte : ne vous y fiez pas et contactez Tratra"
    elif not check["valid"]:
        state, label = "invalid_signature", "Scellement invalide : ce document ne doit pas être considéré comme authentique"
    elif check["key_status"] == "revoked":
        state, label = "key_revoked", "Scellé par une clé révoquée : demander un nouveau document"
    elif newer_final is not None:
        state, label = "superseded", "Version soumise à signature — remplacée par le contrat signé"
    else:
        state, label = "authentic", "Document authentique émis par Tratra"
    amendments = [{"reference": a.reference, "issued_at": a.issued_at, "sha256": a.sha256, "revoked": a.revoked_at is not None}
                  for a in contract.documents.filter(kind="amendment").order_by("issued_at")]
    return {"state": state, "label": label, "reference": doc.reference, "kind": doc.kind, "stage": doc.stage, "version": doc.version,
            "issued_at": doc.issued_at, "sha256": doc.sha256, "revoked_at": doc.revoked_at,
            "nature": "contrat de travail (emploi salarié)" if contract.work_relationship == "employment" else "prestation de services (indépendant)",
            "contract_status": PUBLIC_STATUS.get(contract.status, "—"), "superseded_by": newer_final.reference if newer_final else None,
            "seal": {**check, "payload": seal_payload(doc), "signature": doc.signature,
                     "how_to_verify": "JSON canonique de « payload » (clés triées, sans espace, UTF-8), signature Ed25519 vérifiée avec la clé "
                                      "publique « kid » publiée sur /handy/public/contracts/keys/."},
            "parties_signed": (doc.stage == "final" and doc.parent is not None
                               and set(doc.parent.signatures.values_list("role", flat=True)) >= {"principal", "worker"}),
            "amendments": amendments}


def by_token(raw: str):
    from engagements.models import ContractDocument

    token = (raw or "").strip().rsplit("/", 1)[-1]
    if not TOKEN_RE.match(token):
        return None
    return ContractDocument.objects.select_related("contract").filter(token_hash=_hash_token(token)).first()


def by_file(data: bytes):
    from engagements.models import ContractDocument

    return ContractDocument.objects.select_related("contract").filter(sha256=pdf.sha256(data)).first()


def sign_document(contract, user, *, role: str, ip: str = "", user_agent: str = ""):
    """Signature électronique simple d'une partie sur le document « à signer » de la version courante. Idempotente."""
    from engagements.models import ContractSignature

    doc = contract.documents.filter(kind="contract", stage="for_signature", version=contract.terms_version, revoked_at__isnull=True).order_by("-issued_at").first()
    if doc is None:
        raise DocumentError("no_document", "Aucun document à signer pour cette version du contrat.", 409)
    sig, created = ContractSignature.objects.get_or_create(
        document=doc, role=role,
        defaults={"contract": contract, "user": user, "document_sha256": doc.sha256,
                  "ip_hash": hashlib.sha256(f"{ip}|{settings.SECRET_KEY}".encode()).hexdigest() if ip else "",
                  "user_agent": (user_agent or "")[:200]})
    return doc, sig, created
