"""Analyse assistée d'un document KYC : lecture (OCR), contrôles explicables, rapport. Elle PROPOSE ; elle ne change jamais le statut d'un
document, l'approbation d'un profil ni un badge. Un OCR n'est pas une preuve d'authenticité."""
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from django.conf import settings
from django.utils import timezone

from handy.models import HandymanDocument
from intelligence import ai, risk
from intelligence.models import DocumentAnalysis

IMAGE_MIMES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
EXPIRY_WARNING_DAYS = 30
NAME_OK, NAME_WARN = 0.85, 0.6

TYPE_PATTERNS = [("passport", r"\bPASS?(?:E)?PORT\b|PASSEPORT|^P<[A-Z]{3}"), ("id_card", r"CARTE\s+NATIONALE|IDENTITY\s+CARD|CARTE\s+D.IDENTIT"),
                 ("diploma", r"DIPL[ÔO]ME|DIPLOMA"), ("certificate", r"CERTIFICAT|CERTIFICATE|ATTESTATION")]
DECLARED_TO_DETECTED = {"id_card": {"id_card", "passport"}, "certification": {"diploma", "certificate"}, "license": {"license"}, "casier": {"certificate"}, "insurance": {"certificate"}}


def norm(text: str) -> str:
    return re.sub(r"[^a-z ]", "", "".join(c for c in unicodedata.normalize("NFD", (text or "").lower()) if unicodedata.category(c) != "Mn")).strip()


def name_similarity(a: str, b: str) -> float:
    ta, tb = sorted(norm(a).split()), sorted(norm(b).split())
    if not ta or not tb:
        return 0.0
    return round(SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio(), 2)


def fingerprint(number: str) -> str:
    """Empreinte protégée (HMAC-SHA256 avec un sel serveur) du numéro de document : permet de reconnaître un numéro déjà vu sans le conserver."""
    pepper = (getattr(settings, "KYC_FINGERPRINT_PEPPER", "") or settings.SECRET_KEY).encode()
    return hmac.new(pepper, re.sub(r"[^A-Z0-9]", "", number.upper()).encode(), hashlib.sha256).hexdigest()


def _mime(name: str, head: bytes) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if head.startswith(b"%PDF"):
        return "application/pdf"
    return IMAGE_MIMES.get(ext, "application/octet-stream")


def local_ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def local_ocr(data: bytes, mime: str) -> Optional[str]:
    """OCR local (Tesseract) : le document ne quitte jamais le serveur. Images seulement ; le texte n'est pas conservé."""
    if mime not in IMAGE_MIMES.values() or not local_ocr_available():
        return None
    fd, path = tempfile.mkstemp(suffix=".img")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        for lang in ("fra+eng", "eng"):
            run = subprocess.run(["tesseract", path, "stdout", "-l", lang], capture_output=True, text=True, timeout=45)
            if run.returncode == 0 and run.stdout.strip():
                return run.stdout
        return None
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ─── Extraction déterministe (par étiquettes : l'inconnu vaut mieux qu'une valeur douteuse) ──────────────────────────────────────────────────

DATE = r"(\d{2})[./\- ](\d{2})[./\- ](\d{4})"


def _date(m) -> Optional[date]:
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _after(label: str, text: str, pattern: str):
    m = re.search(label + r"[^\n\d]{0,40}" + pattern, text, re.I)
    return m


def _yymmdd(s: str, *, future: bool) -> Optional[date]:
    try:
        yy, mm, dd = int(s[0:2]), int(s[2:4]), int(s[4:6])
        year = 2000 + yy if (future or yy <= timezone.localdate().year % 100) else 1900 + yy
        return date(year, mm, dd)
    except ValueError:
        return None


def parse_mrz(text: str) -> Dict:
    lines = [re.sub(r"\s", "", l) for l in text.splitlines() if "<" in l and len(re.sub(r"\s", "", l)) >= 40]
    if len(lines) < 2 or not lines[-2].startswith("P"):
        return {}
    l1, l2 = lines[-2], lines[-1]
    names = l1[5:].split("<<", 1)
    out = {"surname": names[0].replace("<", " ").strip(), "given_names": (names[1].replace("<", " ").strip() if len(names) > 1 else ""), "document_number": l2[0:9].replace("<", "")}
    b, e = _yymmdd(l2[13:19], future=False), _yymmdd(l2[21:27], future=True)
    if b:
        out["birth_date"] = b.isoformat()
    if e:
        out["expiry_date"] = e.isoformat()
    return {k: v for k, v in out.items() if v}


def extract_fields(text: str) -> Dict:
    out: Dict = {}
    for kind, pattern in TYPE_PATTERNS:
        if re.search(pattern, text, re.I | re.M):
            out["detected_type"] = kind
            break
    mrz = parse_mrz(text)
    out.update(mrz)
    if "birth_date" not in out and (m := _after(r"(?:N[ÉE]E?\s+LE|DATE\s+DE\s+NAISSANCE|DATE\s+OF\s+BIRTH|BORN)", text, DATE)) and (d := _date(m)):
        out["birth_date"] = d.isoformat()
    if "expiry_date" not in out and (m := _after(r"(?:EXPIR\w*|VALABLE\s+JUSQU\w*|VALID\s+UNTIL|DATE\s+OF\s+EXPIRY)", text, DATE)) and (d := _date(m)):
        out["expiry_date"] = d.isoformat()
    if "surname" not in out and (m := re.search(r"(?:NOM|SURNAME)\s*[:/]?\s*([A-ZÀ-ÖØ-Ý' -]{2,40})", text)):
        out["surname"] = m.group(1).strip()
    if "given_names" not in out and (m := re.search(r"(?:PR[ÉE]NOMS?|GIVEN\s+NAMES?)\s*[:/]?\s*([A-Za-zÀ-ÿ' -]{2,60})", text, re.I)):
        out["given_names"] = m.group(1).strip()
    if "document_number" not in out and (m := re.search(r"(?:N[°O]|NUM[ÉE]RO|DOCUMENT\s+NO|CARD\s+NO|PASSPORT\s+NO)\s*[:.]?\s*([A-Z0-9]{6,14})\b", text, re.I)):
        out["document_number"] = m.group(1).upper()
    return out


def _vision_fields(data: bytes, mime: str) -> Tuple[Dict, str]:
    """Extraction par un fournisseur externe : uniquement si l'envoi de documents KYC est explicitement autorisé (voir ai.kyc_external_allowed)."""
    res = ai.complete("kyc_vision_extract", "Tu extrais des champs d'un document d'identité ou d'un diplôme. Ne devine rien : laisse null ce qui n'est pas lisible.",
                      'Renvoie un objet JSON avec les clés: detected_type (id_card|passport|diploma|certificate|license|other), surname, given_names, birth_date (AAAA-MM-JJ), '
                      'document_number, expiry_date (AAAA-MM-JJ). Valeurs null si illisibles.', images=[(mime, data)], sensitive=True)
    fields = {k: v for k, v in res["data"].items() if k in ("detected_type", "surname", "given_names", "birth_date", "document_number", "expiry_date") and v}
    return fields, res["provider"]


# ─── Contrôles ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _check(code: str, status: str, label: str, detail: str = "") -> Dict:
    return {"code": code, "status": status, "label": label, "detail": detail}


def _parse_iso(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def image_quality_check(data: bytes) -> Dict:
    """Qualité documentaire réelle (résolution, éclairage, netteté) : une pièce illisible ne peut pas être examinée correctement."""
    import io

    from PIL import Image, ImageFilter, ImageStat

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:  # noqa: BLE001
        return _check("image_quality", "warn", "Qualité de l'image", "Image illisible.")
    gray = img.convert("L")
    w, h = gray.size
    small = gray.resize((min(w, 800), max(1, int(h * min(w, 800) / w))))
    edges = small.filter(ImageFilter.FIND_EDGES)
    ew, eh = edges.size
    sharp = ImageStat.Stat(edges.crop((3, 3, max(4, ew - 3), max(4, eh - 3)))).var[0]
    bright = ImageStat.Stat(small).mean[0]
    problems = []
    if max(w, h) < 800:
        problems.append("résolution insuffisante")
    if bright < 50:
        problems.append("trop sombre")
    elif bright > 225:
        problems.append("surexposée")
    if sharp < 40:
        problems.append("floue")
    return _check("image_quality", "warn" if problems else "ok", "Qualité de l'image (résolution, éclairage, netteté)", ", ".join(problems).capitalize() + "." if problems else "")


def analyze(document: HandymanDocument, by=None) -> DocumentAnalysis:
    user = document.handyman.user
    today = timezone.localdate()
    with document.file.open("rb") as fh:
        data = fh.read()
    sha = hashlib.sha256(data).hexdigest()
    mime = _mime(document.file.name or "", data[:8])
    fields: Dict = {}
    ocr_engine, external, legal = "none", False, ""
    checks: List[Dict] = []

    text = local_ocr(data, mime)
    if text:
        fields, ocr_engine = extract_fields(text), "tesseract"
    del text                                                   # le texte intégral n'est jamais conservé
    if len(fields) < 2 and mime in (*IMAGE_MIMES.values(), "application/pdf") and ai.kyc_external_allowed():
        try:
            fields, provider = _vision_fields(data, mime)
            ocr_engine, external, legal = provider, True, str(settings.AI_KYC_LEGAL_BASIS)[:300]
        except ai.AIUnavailable:
            pass

    readable = mime != "application/octet-stream"
    if mime in IMAGE_MIMES.values():
        checks.append(image_quality_check(data))
    checks.append(_check("readable", "ok" if readable else "fail", "Fichier lisible (image ou PDF)", "" if readable else "Format de fichier non reconnu."))
    if ocr_engine == "none":
        checks.append(_check("ocr", "unknown", "Lecture automatique du contenu", "Aucun OCR disponible pour ce fichier : le contrôle reste entièrement manuel."))

    if document.document_type == "id_card" and fields:
        required = {"surname": "nom", "given_names": "prénoms", "birth_date": "date de naissance", "document_number": "numéro", "expiry_date": "date d'expiration"}
        missing = [label for key, label in required.items() if not fields.get(key)]
        checks.append(_check("fields_complete", "warn" if missing else "ok", "Champs essentiels lisibles sur la pièce",
                             f"Non lus : {', '.join(missing)}." if missing else ""))
    detected = fields.get("detected_type")
    if detected:
        expected = DECLARED_TO_DETECTED.get(document.document_type)
        ok = expected is None or detected in expected or detected == "other"
        checks.append(_check("type_match", "ok" if ok else "warn", "Type déclaré cohérent avec le contenu", "" if ok else f"Déclaré « {document.get_document_type_display()} », contenu lu : « {detected} »."))

    expiry = _parse_iso(fields.get("expiry_date")) or document.expires_on
    if expiry:
        if expiry < today:
            checks.append(_check("expiry", "fail", "Document en cours de validité", f"Expiré le {expiry:%d/%m/%Y}."))
        elif expiry <= today + timedelta(days=EXPIRY_WARNING_DAYS):
            checks.append(_check("expiry", "warn", "Document en cours de validité", f"Expire le {expiry:%d/%m/%Y} (moins de {EXPIRY_WARNING_DAYS} jours)."))
        else:
            checks.append(_check("expiry", "ok", "Document en cours de validité", f"Valable jusqu'au {expiry:%d/%m/%Y}."))
    elif document.document_type == "id_card":
        checks.append(_check("expiry", "warn", "Document en cours de validité", "Aucune date d'expiration lisible ni renseignée."))

    account = f"{user.first_name} {user.last_name}".strip()
    doc_name = f"{fields.get('given_names', '')} {fields.get('surname', '')}".strip()
    if doc_name and account:
        score = name_similarity(doc_name, account)
        status = "ok" if score >= NAME_OK else "warn" if score >= NAME_WARN else "fail"
        checks.append(_check("name_match", status, "Nom du document conforme au nom du compte", f"Similarité {round(score * 100)} % (indicatif)."))
    else:
        checks.append(_check("name_match", "unknown", "Nom du document conforme au nom du compte", "Nom non lisible ou compte sans nom : à comparer manuellement."))

    birth = _parse_iso(fields.get("birth_date"))
    others = [_parse_iso(a.fields.get("birth_date")) for a in DocumentAnalysis.objects.filter(document__handyman=document.handyman).exclude(document=document).order_by("-created_at")[:5]]
    others = [d for d in others if d]
    if birth and others:
        checks.append(_check("dob_consistency", "ok" if all(d == birth for d in others) else "fail", "Date de naissance cohérente entre les documents",
                             "" if all(d == birth for d in others) else "Les dates de naissance lues diffèrent d'un document à l'autre."))
    if document.document_type == "certification":
        miss = [f for f, v in (("intitulé", document.title), ("émetteur", document.issuer)) if not (v or "").strip()]
        checks.append(_check("completeness", "warn" if miss else "ok", "Justificatif complet (intitulé, émetteur)", f"Manquant : {', '.join(miss)}." if miss else ""))
    elif document.document_type == "id_card":
        has_id = document.handyman.documents.filter(document_type="id_card").exists()
        checks.append(_check("completeness", "ok" if has_id else "fail", "Pièce d'identité au dossier", ""))

    fp = fingerprint(fields["document_number"]) if fields.get("document_number") else ""
    same_file = DocumentAnalysis.objects.filter(file_sha256=sha).exclude(document__handyman=document.handyman)
    checks.append(_check("duplicate_file", "fail" if same_file.exists() else "ok", "Fichier jamais déposé par un autre compte",
                         f"Ce fichier identique a été déposé par {same_file.values('document__handyman').distinct().count()} autre(s) compte(s)." if same_file.exists() else ""))
    if fp:
        same_id = DocumentAnalysis.objects.filter(id_fingerprint=fp).exclude(document__handyman=document.handyman)
        checks.append(_check("duplicate_identifier", "fail" if same_id.exists() else "ok", "Numéro de document jamais vu sur un autre compte",
                             f"Ce numéro (empreinte protégée) apparaît sur {same_id.values('document__handyman').distinct().count()} autre(s) compte(s)." if same_id.exists() else ""))

    statuses = {c["status"] for c in checks}
    level = "high" if "fail" in statuses else "medium" if "warn" in statuses else "low" if "ok" in statuses and "unknown" not in statuses else "unknown"
    summary = _summary(checks, level)
    ai_report, ai_provider = _ai_report(checks, level)
    safe_fields = {k: (v if k != "document_number" else "•••" + str(v)[-3:]) for k, v in fields.items()}      # numéro masqué : jamais en clair
    analysis = DocumentAnalysis.objects.create(document=document, requested_by=by, ocr_engine=ocr_engine, external_used=external, legal_basis=legal, fields=safe_fields,
                                               id_fingerprint=fp, file_sha256=sha, checks=checks, risk_level=level, summary=summary, ai_report=ai_report, ai_provider=ai_provider)
    _propose_cases(document, user, analysis)
    return analysis


def _ai_report(checks: List[Dict], level: str) -> Tuple[str, str]:
    """Rapport rédigé par un modèle de langage (DeepSeek d'abord, Anthropic en repli) À PARTIR DES SEULS résultats des contrôles : jamais un nom, un
    numéro, une date de naissance ni une image. Aide à la décision, jamais une preuve ; vide si aucun fournisseur n'est configuré."""
    safe = [{"controle": c["code"], "etat": c["status"], "detail": re.sub(r"\d{2}/\d{2}/\d{4}", "[date]", c["detail"])} for c in checks]
    try:
        res = ai.complete("kyc_report", "Tu aides un examinateur KYC. Tu résumes en français, en 4 phrases maximum, des résultats de contrôles automatiques. Tu ne déclares jamais un document authentique ou faux.",
                          'Résultats : ' + json.dumps({"niveau_de_risque": level, "controles": safe}, ensure_ascii=False) + '\nRéponds par un objet JSON {"rapport": "..."}.', sensitive=False)
        return str(res["data"].get("rapport", ""))[:1200], res["provider"]
    except (ai.AIUnavailable, KeyError, ValueError):
        return "", ""


def _summary(checks: List[Dict], level: str) -> str:
    bad = [c for c in checks if c["status"] in ("fail", "warn")]
    head = {"high": "Points bloquants à examiner avant toute décision.", "medium": "Quelques points à vérifier.", "low": "Aucune anomalie détectée par les contrôles automatiques.",
            "unknown": "Contrôles automatiques insuffisants : examen manuel nécessaire."}[level]
    return head + (" " + " ".join(f"{c['label']} : {c['detail'] or c['status']}" for c in bad) if bad else "") + " La décision reste celle de l'équipe KYC."


def _propose_cases(document: HandymanDocument, user, analysis: DocumentAnalysis) -> None:
    by_code = {c["code"]: c for c in analysis.checks}
    related = lambda f: [a["document__handyman__user_id"] for a in DocumentAnalysis.objects.filter(**f).exclude(document__handyman=document.handyman).values("document__handyman__user_id")]
    for code, field in (("duplicate_file", {"file_sha256": analysis.file_sha256}), ("duplicate_identifier", {"id_fingerprint": analysis.id_fingerprint})):
        if by_code.get(code, {}).get("status") == "fail" and all(field.values()):
            ids = related(field)
            risk.propose(user.pk, "duplicate_account", 3, f"{by_code[code]['label']} : {by_code[code]['detail']} À vérifier par un humain : réutilisation de document ou doublon de profil possible.",
                         {"signal": code, "document": document.pk}, dedupe_key=f"{code}:{list(field.values())[0][:10]}", related=ids, source="document_analysis")
    for code in ("name_match", "dob_consistency", "type_match"):
        if by_code.get(code, {}).get("status") == "fail" or (code == "type_match" and by_code.get(code, {}).get("status") == "warn"):
            risk.propose(user.pk, "document_inconsistent", 2, f"{by_code[code]['label']} : {by_code[code]['detail']} Indicatif : un OCR peut se tromper, à confirmer visuellement.",
                         {"signal": code, "document": document.pk}, dedupe_key=f"{code}:{document.pk}", source="document_analysis")
    if by_code.get("expiry", {}).get("status") == "fail":
        risk.propose(user.pk, "kyc_expired", 2, by_code["expiry"]["detail"] + " Demander un nouveau document.", {"signal": "expiry", "document": document.pk}, dedupe_key=f"expiry:{document.pk}", source="document_analysis")
