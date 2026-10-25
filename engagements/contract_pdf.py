"""Modèle A4 INSTITUTIONNEL des documents de contrat (salariés et indépendants) et des avenants, sur le moteur engagements/pdf.py.

  En-tête (chaque page)   logo officiel, TRATRA, nature du document, référence, version, date d'émission
  Page d'identification   titre selon la nature juridique, encadrés des deux parties (et de l'entreprise), synthèse contractuelle
  Articles                texte EXACT du modèle validé (titres numérotés, paragraphes espacés, jamais tronqués)
  Signatures              deux blocs : identité, consentement, date et heure, référence de la preuve
  Sécurité                QR code, référence, version, horodatage, clé Ed25519, empreintes ; vérification publique
  Pied de page            TRATRA + référence + version, « page X/Y », mention de vérification, mentions légales CONFIGURÉES

Le contenu juridique n'est jamais réécrit : seuls l'espacement et la ponctuation doublée (« .. ») sont corrigés. Aucune pièce KYC n'est
reproduite (seul le fait que l'identité a été contrôlée est indiqué). Les mentions légales viennent de `CONTRACT_PDF_LEGAL_MENTIONS`
(rien n'est imprimé si le réglage est vide)."""
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from django.conf import settings
from django.utils import timezone

from engagements import pdf
from engagements.pdf import BOLD, GREEN, GREEN_DARK, INK, ITALIC, LINE, MARGIN_X, MUTED, PAGE_H, PAGE_W, REGULAR, TINT, YELLOW, Layout

DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
ROLE_TITLES = {"employment": ("L'employeur", "Le salarié"), "independent": ("Le client", "Le prestataire")}
ROLE_LABELS = {"employment": ("Employeur", "Salarié(e)"), "independent": ("Client", "Prestataire")}
NATURE_TITLES = {"employment": "Contrat de travail", "independent": "Contrat de prestation de services"}
NATURES = {"employment": "Contrat de travail (emploi salarié)", "independent": "Prestation de services (travailleur indépendant)"}
STAGE_LABELS = {"for_signature": "Version soumise à signature", "final": "Exemplaire signé par les deux parties"}
PERIOD_WORDS = {"monthly": "par mois", "hourly": "de l'heure", "per_visit": "par intervention"}
FIELD_LABELS = {"amount": "Rémunération", "schedule": "Horaires", "hours_per_week": "Heures par semaine", "end_date": "Fin du contrat",
                "notice_period_days": "Préavis (jours)", "conditions": "Conditions particulières", "benefits": "Avantages", "description": "Missions",
                "auto_renew": "Renouvellement automatique", "renewal_term_months": "Durée du renouvellement (mois)", "payment_day": "Jour de paiement",
                "overtime_hourly_rate": "Taux des heures supplémentaires", "proration_mode": "Dernière période incomplète", "period": "Périodicité",
                "location_address": "Adresse du lieu", "location_city": "Ville", "title": "Intitulé", "start_date": "Début"}


def fmt_dt(dt: Optional[datetime]) -> str:
    return timezone.localtime(dt).strftime("%d/%m/%Y à %H:%M") if dt else "—"


def fmt_date(d: Optional[date]) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def fmt_amount(value, currency: str = "XOF") -> str:
    if value in (None, ""):
        return "—"
    n = float(value)
    text = f"{n:,.0f}" if n == int(n) else f"{n:,.2f}"
    return f"{text.replace(',', ' ')} {currency}"


def fmt_phone(raw: Optional[str]) -> str:
    """+2250700000000 → +225 07 00 00 00 00 ; autre format : tel quel."""
    s = (raw or "").strip()
    if s.startswith("+225") and len(s) == 14 and s[1:].isdigit():
        d = s[4:]
        return "+225 " + " ".join(d[i:i + 2] for i in range(0, 10, 2))
    return s or "—"


def person_name(user) -> Tuple[str, str]:
    return ((user.last_name or "").strip().upper() or "—", (user.first_name or "").strip() or "—")


def full_name(user) -> str:
    last, first = person_name(user)
    parts = [p for p in (first, last) if p != "—"]
    return " ".join(parts) or "Membre Tratra"


def schedule_label(schedule) -> str:
    slots = [s for s in (schedule or []) if isinstance(s, dict)]
    if not slots:
        return "À convenir dans le planning du contrat"
    return ", ".join(f"{DAYS[int(s.get('weekday', 0)) % 7]} {s.get('start', '')}–{s.get('end', '')}" for s in slots)


def duration_label(contract) -> str:
    from engagements.dates import add_months

    start, end = contract.start_date, contract.end_date
    if not end:
        text = f"À partir du {fmt_date(start)}, durée indéterminée"
    else:
        months = next((m for m in range(1, 241) if add_months(start, m) - timedelta(days=1) == end), None)
        text = f"Du {fmt_date(start)} au {fmt_date(end)}" + (f" ({months} mois)" if months else "")
    if contract.auto_renew and end:
        text += f" ; renouvellement automatique de {contract.renewal_term_months or '—'} mois, sauf non-renouvellement dans le délai de préavis"
    return text


def trade_path(category) -> str:
    if category is None:
        return "—"
    parent = getattr(category, "parent", None)
    return f"{parent.name} › {category.name}" if parent is not None else category.name


def _tratra_id(user) -> str:
    profile = getattr(user, "handyman_profile", None)
    code = getattr(getattr(profile, "professional_id", None), "code", None) if profile is not None else None
    return code or "—"


def _address(user) -> str:
    if (user.address or "").strip():
        return user.address.strip()
    profile = getattr(user, "handyman_profile", None)
    if profile is not None:
        parts = [p for p in ((profile.quartier or "").strip(), (profile.commune or "").strip()) if p]
        if parts:
            return ", ".join(parts)
    return "—"


def _verification(user) -> str:
    from handy.eligibility import is_user_publishable

    if getattr(user, "handyman_profile", None) is not None and is_user_publishable(user):
        return "Identité contrôlée par Tratra (pièce d'identité non reproduite)"
    return "Téléphone vérifié par code" if getattr(user, "is_verified", False) else "—"


def party_rows(contract, role: str) -> List[Tuple[str, str]]:
    user = contract.principal if role == "principal" else contract.worker
    labels = ROLE_LABELS.get(contract.work_relationship, ROLE_LABELS["independent"])
    last, first = person_name(user)
    org = contract.organization if role == "principal" else None
    if role == "worker":
        profession = trade_path(contract.category).split(" › ")[0]
        quality = labels[1]
    else:
        profession = (org.industry if org is not None and org.industry else "—") if org is not None else "Particulier"
        quality = labels[0] + (f", représentant {org.legal_name or org.name}" if org is not None else "")
    rows = [("Nom", last), ("Prénom(s)", first), ("Tratra ID", _tratra_id(user)), ("Téléphone", fmt_phone(user.phone)),
            ("Adresse", _address(user)), ("Qualité", quality), ("Profession", profession), ("Vérification", _verification(user))]
    if org is not None:
        rows += [("Entreprise", org.legal_name or org.name), ("RCCM / immatriculation", org.registration_number or "—"),
                 ("Siège", ", ".join(p for p in ((org.address or "").strip(), (org.city or "").strip()) if p) or "—"),
                 ("Téléphone de l'entreprise", fmt_phone(org.phone))]
    return rows


def synthesis_rows(contract) -> List[Tuple[str, str]]:
    period = PERIOD_WORDS.get(contract.period, contract.period)
    payment = (f"Le {contract.payment_day} de chaque mois" if contract.payment_day and contract.period == "monthly"
               else "À chaque période, au jour convenu")
    payment += " ; paiement déclaré par une partie et confirmé par l'autre sur Tratra (Tratra ne verse ni n'encaisse la rémunération)"
    if contract.proration_mode == "calendar_days":
        payment += " ; dernière période incomplète au prorata des jours calendaires"
    hours = f" ; {float(contract.hours_per_week):g} heures par semaine" if contract.hours_per_week else ""
    overtime = (f" ; heures supplémentaires à {fmt_amount(contract.overtime_hourly_rate, contract.currency)} de l'heure"
                if contract.overtime_hourly_rate else "")
    location = ", ".join(p for p in ((contract.location_address or "").strip(), (contract.location_city or "").strip()) if p) or "—"
    return [
        ("Nature", NATURES.get(contract.work_relationship, NATURES["independent"])),
        ("Métier", trade_path(contract.category)),
        ("Intitulé", contract.title),
        ("Missions", contract.description or "—"),
        ("Lieu d'exécution", location),
        ("Durée", duration_label(contract)),
        ("Horaires", schedule_label(contract.schedule) + hours),
        ("Rémunération", f"{fmt_amount(contract.amount, contract.currency)} {period}{overtime}"),
        ("Échéances", payment),
        ("Préavis", f"{contract.notice_period_days} jours"),
        ("Avantages", contract.benefits or "Aucun"),
        ("Conditions particulières", contract.conditions or "Aucune"),
    ]


def legal_mentions() -> List[str]:
    raw = str(getattr(settings, "CONTRACT_PDF_LEGAL_MENTIONS", "") or "").strip()
    return [part.strip() for part in raw.split("|") if part.strip()]


def logo_path() -> str:
    for candidate in (Path(settings.BASE_DIR) / "static" / "img" / "tratra_logo.webp", Path(settings.BASE_DIR) / "trust" / "assets" / "tratra_logo.webp"):
        if candidate.exists():
            return str(candidate)
    return ""


def _decorator(doc_type: str, reference: str, version: int, issued_at: datetime, stage_label: str):
    mentions = legal_mentions()
    verify_base = f"{settings.PUBLIC_WEB_URL.rstrip('/')}/verify/contract"

    def decorate(layout: Layout, page: List[bytes], i: int, n: int):
        top = PAGE_H - 34
        if not layout.image_logo(MARGIN_X, top - 28, 28, page=page):
            layout.rect(MARGIN_X, top - 28, 28, 28, fill=GREEN, page=page)
        layout.text(MARGIN_X + 36, top - 13, "TRATRA", 13.5, BOLD, GREEN, page=page)
        layout.text(MARGIN_X + 36, top - 25, doc_type, 7.6, REGULAR, MUTED, page=page)
        right = PAGE_W - MARGIN_X
        layout.text_right(right, top - 9, f"Réf. {reference}", 9.2, BOLD, INK, page=page)
        layout.text_right(right, top - 20, f"Version {version} · émis le {fmt_dt(issued_at)}", 7.6, REGULAR, MUTED, page=page)
        layout.text_right(right, top - 30, stage_label, 7.6, BOLD, GREEN_DARK, page=page)
        y_rule = top - 39
        layout.line(MARGIN_X, y_rule, right, y_rule, GREEN, 1.1, page=page)
        layout.line(MARGIN_X, y_rule, MARGIN_X + 64, y_rule, YELLOW, 2.6, page=page)
        # Pied de page
        layout.line(MARGIN_X, 66, right, 66, LINE, 0.6, page=page)
        layout.text(MARGIN_X, 55, f"TRATRA · {reference} · version {version}", 7.6, BOLD, INK, page=page)
        layout.text_right(right, 55, f"Page {i}/{n}", 7.6, BOLD, INK, page=page)
        layout.text(MARGIN_X, 45, f"Authenticité vérifiable : QR code du document ou {verify_base}", 6.8, REGULAR, MUTED, page=page)
        y = 36
        for mention in mentions[:3]:
            for line in pdf.wrap(pdf.clean(mention), 6.3, right - MARGIN_X)[:2]:
                if y < 14:
                    break
                layout.text(MARGIN_X, y, line, 6.3, REGULAR, MUTED, page=page)
                y -= 8

    return decorate


def _title_block(layout: Layout, eyebrow: str, title: str, subtitle: str, note: str, badge: str, url: str):
    """Bloc de titre de la première page, QR code de vérification à droite."""
    qr_size = 74.0
    text_width = layout.width - qr_size - 18
    top = layout.y
    layout.qr(url, layout.right - qr_size, top, qr_size)
    layout.text(layout.right - qr_size, top - qr_size - 9, "Vérifier l'authenticité", 6.4, REGULAR, MUTED)
    y = top
    layout.text(layout.left, y - 8, eyebrow, 7.8, BOLD, GREEN_DARK)
    y -= 16
    for line in pdf.wrap(pdf.clean(title).upper(), 19, text_width, BOLD):
        layout.text(layout.left, y - 17, line, 19, BOLD, INK)
        y -= 23
    for line in pdf.wrap(pdf.clean(subtitle), 11.5, text_width, REGULAR):
        layout.text(layout.left, y - 11, line, 11.5, REGULAR, INK)
        y -= 15
    y -= 3
    for line in pdf.wrap(pdf.clean(note), 7.8, text_width, ITALIC):
        layout.text(layout.left, y - 8, line, 7.8, ITALIC, MUTED)
        y -= 10.5
    y -= 5
    badge_w = pdf.width(badge.upper(), 7.6, BOLD) + 16
    layout.rect(layout.left, y - 15, badge_w, 15, fill=TINT, stroke=GREEN, lw=0.6)
    layout.text(layout.left + 8, y - 10.6, badge.upper(), 7.6, BOLD, GREEN_DARK)
    y -= 15
    layout.y = min(y, top - qr_size - 14) - 10


def _security_block(layout: Layout, url: str, rows: Sequence[Tuple[str, str]], explanation: str):
    """QR code + éléments de sécurité + adresse de vérification complète (sur une seule ligne) : bloc insécable."""
    qr_size, pad, size = 96.0, 10.0, 8.2
    col_x = layout.left + pad + qr_size + 14
    col_w = layout.right - pad - col_x
    lines: List[Tuple[str, str]] = []
    for label, value in rows:
        lines.append((pdf.clean(label), "label"))
        lines += [(t, "value") for t in pdf.wrap(pdf.clean(value), size, col_w, REGULAR)]
    rows_h = sum(10.4 if kind == "label" else 11.2 for _, kind in lines)
    url_size = 7.2
    while url_size > 5 and pdf.width(url, url_size) > layout.width - 2 * pad:
        url_size -= 0.2
    expl = pdf.wrap(pdf.clean(explanation), 7.8, layout.width - 2 * pad, REGULAR)
    height = pad + max(qr_size + 12, rows_h) + 8 + 12 + len(expl) * 10.5 + pad
    layout.ensure(height)
    top = layout.y
    layout.rect(layout.left, top - height, layout.width, height, fill=(0.976, 0.988, 0.980), stroke=GREEN, lw=0.8)
    layout.qr(url, layout.left + pad, top - pad, qr_size)
    layout.text(layout.left + pad, top - pad - qr_size - 9, "Scanner pour vérifier", 6.6, REGULAR, MUTED)
    y = top - pad
    for text, kind in lines:
        if kind == "label":
            layout.text(col_x, y - 7.6, text, 7.4, BOLD, GREEN_DARK)
            y -= 10.4
        else:
            layout.text(col_x, y - 8, text, size, REGULAR, INK)
            y -= 11.2
    y = top - pad - max(qr_size + 12, rows_h) - 8
    layout.text(layout.left + pad, y - url_size, url, url_size, BOLD, INK)
    y -= 12
    for line in expl:
        layout.text(layout.left + pad, y - 7.8, line, 7.8, REGULAR, MUTED)
        y -= 10.5
    layout.y = top - height - 6


def render_contract(contract, *, stage: str, reference: str, issued_at: datetime, url: str, kid: str, signatures: Sequence = (),
                    signed_sha: str = "") -> bytes:
    rel = contract.work_relationship if contract.work_relationship in NATURE_TITLES else "independent"
    principal_title, worker_title = ROLE_TITLES[rel]
    principal_label, worker_label = ROLE_LABELS[rel]
    template = contract.template
    layout = Layout(logo_path=logo_path())

    if template is not None:
        validated = template.status == template.VALIDATED and template.reviewed_at
        note = (f"Établi sur le modèle « {template.title} » (version {template.version}), validé par revue juridique le "
                f"{fmt_dt(template.reviewed_at)}." if validated else
                f"Modèle « {template.title} » NON VALIDÉ juridiquement : document non définitif.")
    else:
        note = "Conditions acceptées par les deux parties sur Tratra."
    _title_block(layout, f"CONTRAT N° {reference} · VERSION {contract.terms_version}", NATURE_TITLES[rel], contract.title, note,
                 STAGE_LABELS.get(stage, stage), url)

    layout.heading("Identification des parties", 1, keep_with=150)
    layout.boxes([(principal_title, party_rows(contract, "principal")), (worker_title, party_rows(contract, "worker"))])
    layout.space(4)
    layout.paragraph("Données d'identification issues des comptes Tratra des parties. Aucune pièce d'identité n'est reproduite dans ce document.",
                     7.6, ITALIC, MUTED, after=2)

    layout.heading("Synthèse contractuelle", 1, keep_with=60)
    layout.table(synthesis_rows(contract), label_width=138)

    layout.heading("Articles du contrat", 1, keep_with=80)
    if contract.articles:
        for article in contract.articles:
            layout.heading(f"Article {article.get('number')} — {article.get('title', '')}", 2, keep_with=30)
            for paragraph in [p for p in str(article.get("body") or "").split("\n") if p.strip()]:
                layout.paragraph(paragraph, 9.6, leading=13.8, after=5)
    else:
        from engagements.services.contracts import snapshot

        rows = [(FIELD_LABELS.get(k, k), str(v)) for k, v in snapshot(contract).items() if v not in (None, "", [], {})]
        layout.table(rows, label_width=150)
    refs = (template.legal_references if template is not None else []) or []
    if refs:
        layout.heading("Références juridiques", 2)
        for r in refs:
            layout.paragraph(f"{r.get('label', '')} : {r.get('citation', '')} ({r.get('status', '')})", 8.2, color=MUTED, after=3)

    layout.heading("Signatures", 1, keep_with=170)
    layout.paragraph("Signature électronique simple sur Tratra : chaque partie, connectée à son compte, signe le document à signer identifié par son "
                     "empreinte SHA-256. Cette signature est distincte du scellement numérique de Tratra, qui atteste l'origine et l'intégrité du "
                     "fichier.", 8.4, color=MUTED, after=8)
    by_role = {s.role: s for s in signatures}
    consent = f"« J'ai lu le contrat {reference} (version {contract.terms_version}) et je le signe électroniquement. »"
    blocks = []
    for role, title, label, user in (("principal", principal_title, principal_label, contract.principal), ("worker", worker_title, worker_label, contract.worker)):
        s = by_role.get(role)
        if s is not None:
            rows = [("Signataire", full_name(s.user)), ("Qualité", label), ("Consentement", consent),
                    ("Date et heure", f"Signé électroniquement le {fmt_dt(s.signed_at)} (heure d'Abidjan)"),
                    ("Preuve de signature", f"SIG-{s.pk:06d} (signature électronique simple)"),
                    ("Document signé (SHA-256)", s.document_sha256)]
        else:
            rows = [("Signataire", full_name(user)), ("Qualité", label),
                    ("Statut", "En attente de signature électronique sur Tratra" if stage == "for_signature" else "Non signé"),
                    ("Consentement demandé", consent)]
        blocks.append((title, rows))
    layout.boxes(blocks, size=8.4)

    layout.heading("Sécurité et authenticité du document", 1, keep_with=210)
    rows = [("Référence unique", reference), ("Version des conditions", str(contract.terms_version)),
            ("Horodatage d'émission", f"{fmt_dt(issued_at)} — {issued_at.isoformat()}"),
            ("Scellement numérique Tratra", f"Ed25519 · clé {kid}"),
            ("Empreinte des conditions acceptées (SHA-256)", contract.terms_hash)]
    if signed_sha:
        rows.append(("Empreinte du document signé par les parties (SHA-256)", signed_sha))
    _security_block(layout, url, rows,
                    "L'empreinte SHA-256 de ce fichier PDF et son scellement Ed25519 sont enregistrés par Tratra à l'émission. La page de vérification "
                    "(QR code ci-dessus) recalcule l'empreinte, contrôle le scellement avec la clé publique et signale tout document modifié, remplacé "
                    "ou révoqué. Un document scellé n'est jamais modifié : toute évolution fait l'objet d'un avenant distinct.")
    return layout.finish(_decorator(NATURE_TITLES[rel], reference, contract.terms_version, issued_at, STAGE_LABELS.get(stage, stage)))


def _change_value(key: str, value, currency: str) -> str:
    if key == "schedule":
        return schedule_label(value)
    if key in ("amount", "overtime_hourly_rate"):
        return fmt_amount(value, currency)
    if isinstance(value, bool):
        return "Oui" if value else "Non"
    if isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-":
        try:
            return fmt_date(date.fromisoformat(value))
        except ValueError:
            return value
    return "—" if value in (None, "") else str(value)


def render_amendment(contract, amendment, original, *, number: int, reference: str, issued_at: datetime, url: str, kid: str) -> bytes:
    from engagements.services.contracts import json_safe

    rel = contract.work_relationship if contract.work_relationship in NATURE_TITLES else "independent"
    principal_title, worker_title = ROLE_TITLES[rel]
    principal_label, worker_label = ROLE_LABELS[rel]
    layout = Layout(logo_path=logo_path())
    _title_block(layout, f"AVENANT N° {number} · CONTRAT {original.reference}", f"Avenant n° {number}",
                 f"au {NATURE_TITLES[rel].lower()} « {contract.title} »",
                 f"Le contrat d'origine {original.reference} reste inchangé (empreinte {original.sha256}).", "Avenant accepté par les deux parties", url)
    layout.heading("Parties", 1, keep_with=80)
    layout.boxes([(principal_title, [("Nom et prénom(s)", full_name(contract.principal)), ("Qualité", principal_label)]),
                  (worker_title, [("Nom et prénom(s)", full_name(contract.worker)), ("Qualité", worker_label)])])
    layout.heading("Objet de l'avenant", 1, keep_with=60)
    changes = json_safe(amendment.changes or {})
    rows = [("Nature", amendment.get_kind_display()), ("Prise d'effet", fmt_date(amendment.effective_date)),
            ("Motif", amendment.reason or "—")]
    rows += [(FIELD_LABELS.get(k, k), _change_value(k, v, contract.currency)) for k, v in changes.items()]
    rows += [("Proposé le", fmt_dt(amendment.created_at)), ("Accepté par l'autre partie le", fmt_dt(amendment.responded_at or issued_at)),
             ("Conditions après l'avenant", f"version {contract.terms_version} — empreinte {contract.terms_hash}")]
    layout.table(rows, label_width=150)
    layout.heading("Sécurité et authenticité du document", 1, keep_with=210)
    _security_block(layout, url, [("Référence unique", reference), ("Contrat d'origine (inchangé)", f"{original.reference} — SHA-256 {original.sha256}"),
                                  ("Horodatage d'émission", f"{fmt_dt(issued_at)} — {issued_at.isoformat()}"),
                                  ("Scellement numérique Tratra", f"Ed25519 · clé {kid}")],
                    "L'empreinte SHA-256 de cet avenant et son scellement Ed25519 sont enregistrés par Tratra. La page de vérification signale tout "
                    "document modifié, remplacé ou révoqué. Le contrat d'origine n'est jamais modifié.")
    return layout.finish(_decorator("Avenant au contrat", reference, contract.terms_version, issued_at, "Avenant accepté"))
