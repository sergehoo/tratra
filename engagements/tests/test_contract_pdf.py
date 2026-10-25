"""Modèle A4 institutionnel des contrats : en-tête et pied de page sur chaque page, identification des parties, synthèse, articles complets,
signatures, sécurité (QR, référence, horodatage, Ed25519), mentions légales configurées, pagination des contrats longs, accents, aucune
pièce KYC, documents historiques intacts, cohérence métier / missions."""
import re
from datetime import date, datetime, timedelta, timezone as tz
from types import SimpleNamespace as NS

import pytest
from rest_framework.test import APIClient

from engagements import contract_pdf, documents, pdf, signing
from engagements.services import contracts
from engagements.services.quality import coherence_warnings
from engagements.testing import allow_employment, category, contract_data, person, pro
from engagements.tests.test_contract_documents import TODAY, final_doc, pdf_bytes, token_of, validated_template
from handy.models import HandymanProfile, ServiceCategory

pytestmark = pytest.mark.django_db


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


DECORATION = re.compile(r"^(Réf\. TRT-|Version \d+ · émis le|TRATRA|Page \d+/\d+|Authenticité vérifiable|Contrat de travail$|Contrat de prestation de services$|"
                        r"Avenant au contrat$|Version soumise à signature$|Exemplaire signé par les deux parties$|Avenant accepté$)")


def body_text(pages) -> str:
    """Texte courant sans en-têtes ni pieds de page : un paragraphe qui continue sur la page suivante se relit d'un seul tenant."""
    return "\n".join(line for page in pages for line in page.split("\n") if not DECORATION.match(line))


def signed_employment(**over):
    nounou = category("nounou", "Nounou")
    allow_employment(nounou)
    validated_template("employment", code="domestique-pdf", categories=[nounou])
    principal, worker = person("famille_pdf"), pro("nounou_pdf")
    principal.first_name, principal.last_name, principal.phone = "Awa", "Kouassi", "+2250707070707"
    principal.save()
    worker.first_name, worker.last_name, worker.phone = "Aminata", "Traoré", "+2250505050505"
    worker.save()
    profile = HandymanProfile.objects.get(user=worker)
    profile.cni_number = "CI0012345678"                                      # pièce KYC : ne doit JAMAIS apparaître
    profile.save()
    data = contract_data(worker, start=TODAY + timedelta(days=10), cat=nounou, work_relationship="employment", legal_notice_ack=True,
                         notice_period_days=30, title="Nounou à domicile — Cocody",
                         description="Garde de deux enfants après l'école, aide aux devoirs et préparation du goûter..",
                         conditions="Tenue fournie ,, horaires adaptés pendant les vacances scolaires. " * 6,
                         schedule=[{"weekday": d, "start": "15:00", "end": "19:00"} for d in range(5)], **over)
    c = contracts.create_draft(principal, data, today=TODAY)
    contracts.propose(c, principal, today=TODAY)
    c.refresh_from_db()
    contracts.accept(c, worker, c.terms_hash, today=TODAY)
    c.refresh_from_db()
    contracts.sign(c, worker, consent=True, today=TODAY)
    contracts.sign(c, principal, consent=True, today=TODAY)
    c.refresh_from_db()
    return c, principal, worker


def test_signed_employment_contract_uses_the_institutional_template_on_every_page():
    c, principal, worker = signed_employment()
    doc = final_doc(c)
    data = pdf_bytes(doc)
    pages = pdf.page_texts(data)
    n = len(pages)
    assert n >= 3 and f"/Count {n}".encode() in data
    for i, text in enumerate(pages, start=1):                               # en-tête et pied de page sur chaque page
        assert f"Réf. {c.reference}" in text and f"Page {i}/{n}" in text and f"TRATRA · {c.reference} · version {c.terms_version}" in text
        assert "Authenticité vérifiable" in text and "émis le" in text
    first = pages[0]
    for expected in ("CONTRAT DE TRAVAIL", "L'EMPLOYEUR", "LE SALARIÉ", "Identification des parties", "Synthèse contractuelle", "KOUASSI", "Awa",
                     "TRAORÉ", "Aminata", "+225 07 07 07 07 07", "Tratra ID", "Profession", "Nounou", "Prénom(s)"):
        assert expected in first, expected
    everything = "\n".join(pages)
    for label in ("Métier", "Missions", "Lieu d'exécution", "Durée", "Horaires", "Rémunération", "Échéances", "Avantages", "Conditions particulières"):
        assert label in everything, label
    assert "CI0012345678" not in everything and b"CI0012345678" not in data          # aucune pièce KYC
    flat = compact(body_text(pages))
    for article in c.articles:                                              # aucun article tronqué
        assert compact(f"Article {article['number']} — {article['title']}") in flat
        assert compact(pdf.clean(article["body"])) in flat, article["title"]
    assert not re.search(r"(?<!\.)\.\.(?!\.)", everything) and ",," not in everything   # ponctuation doublée supprimée
    assert "Signé électroniquement le" in everything and everything.count("SIG-") == 2
    signed_source = c.documents.get(stage="for_signature")
    assert compact(signed_source.sha256) in flat and compact("Document signé (SHA-256)") in flat
    assert f"Ed25519 · clé {doc.signing_key_id}" in everything and "Horodatage d'émission" in everything
    assert token_of(doc) and b"/Subtype /Image" in data                        # QR de vérification et logo officiel
    assert "RCCM" not in everything                                         # aucune mention légale inventée
    # Scellement inchangé : empreinte des octets, signature Ed25519 de la charge utile, vérification publique.
    assert pdf.sha256(data) == doc.sha256 and documents.public_result(doc)["state"] == "authentic"
    assert signing.verify(documents.seal_payload(doc), doc.signature, doc.signing_key_id)["valid"]


def test_configured_legal_mentions_appear_in_every_footer(settings):
    settings.CONTRACT_PDF_LEGAL_MENTIONS = "Tratra SAS au capital de 1 000 000 FCFA | RCCM CI-ABJ-TEST-0001 | Siège : Abidjan"
    c, *_ = signed_employment()
    pages = pdf.page_texts(pdf_bytes(final_doc(c)))
    assert all("RCCM CI-ABJ-TEST-0001" in p and "Tratra SAS au capital" in p for p in pages)


def test_independent_contract_to_sign_has_two_pending_signature_blocks():
    validated_template()
    principal, worker = person("client_pdf"), pro("presta_pdf")
    c = contracts.create_draft(principal, contract_data(worker, start=TODAY, description="Entretien des locaux, nettoyage et petites réparations."), today=TODAY)
    contracts.propose(c, principal, today=TODAY)
    c.refresh_from_db()
    contracts.accept(c, worker, c.terms_hash, today=TODAY)
    c.refresh_from_db()
    doc = c.documents.get(stage="for_signature")
    everything = "\n".join(pdf.page_texts(pdf_bytes(doc)))
    for expected in ("CONTRAT DE PRESTATION DE SERVICES", "LE CLIENT", "LE PRESTATAIRE", "VERSION SOUMISE À SIGNATURE", "Consentement demandé"):
        assert compact(expected) in compact(everything), expected
    assert compact(everything).count(compact("En attente de signature électronique sur Tratra")) == 2


def test_amendment_document_keeps_the_template_and_never_touches_the_original():
    c, principal, worker = signed_employment()
    contracts.sync(c, TODAY + timedelta(days=10))
    original = final_doc(c)
    before = (original.sha256, pdf_bytes(original))
    a = contracts.propose_amendment(c, principal, {"kind": "change", "changes": {"amount": "175000"}, "effective_date": (TODAY + timedelta(days=10)).isoformat(),
                                                   "reason": "Revalorisation convenue."}, today=TODAY + timedelta(days=10))
    contracts.respond_amendment(a, worker, True, today=TODAY + timedelta(days=10))
    c.refresh_from_db()
    amendment = c.documents.get(kind="amendment")
    text = "\n".join(pdf.page_texts(pdf_bytes(amendment)))
    for expected in ("AVENANT N° 1", f"Réf. {c.reference}-AV1", "Contrat d'origine (inchangé)", original.reference, "175 000 XOF", "Page 1/"):
        assert expected in text, expected
    original.refresh_from_db()
    assert (original.sha256, pdf_bytes(original)) == before                 # document historique scellé intact


def _render_preview(**over):
    """Rendu sans base (objets simples) : déterminisme et mise en page des cas extrêmes."""
    user = NS(first_name="Élodie", last_name="N'Guessan", phone="+2250101010101", address="Yopougon, Abidjan", handyman_profile=None, is_verified=True)
    template = NS(title="Modèle de test", version=1, status="validated", VALIDATED="validated", reviewed_at=datetime(2026, 10, 1, tzinfo=tz.utc), legal_references=[])
    contract = NS(work_relationship="independent", title="Maintenance du parc informatique", terms_version=1, terms_hash="f" * 64, template=template,
                  articles=[{"number": i, "title": f"Clause {i} — œuvre, réparations, échéances", "body": ("Texte accentué : é è ê à ç ô û « guillemets » — tiret. " * 30)}
                            for i in range(1, 16)],
                  category=NS(name="Maintenance informatique", parent=None), principal=user, worker=user, organization=None,
                  description="Diagnostic, réparation et maintenance des ordinateurs.", location_address="Plateau", location_city="Abidjan",
                  start_date=date(2026, 11, 2), end_date=None, auto_renew=False, renewal_term_months=None, schedule=[], hours_per_week=None,
                  amount=250000, currency="XOF", period="monthly", payment_day=10, proration_mode="none", overtime_hourly_rate=None,
                  notice_period_days=15, benefits="", conditions="")
    for k, v in over.items():
        setattr(contract, k, v)
    return contract_pdf.render_contract(contract, stage="for_signature", reference="TRT-CTR-2026-009999",
                                        issued_at=datetime(2026, 10, 25, 12, 0, tzinfo=tz.utc),
                                        url="https://tratra.net/verify/contract/" + "A" * 43, kid="ctr-test")


def test_long_contract_is_paginated_without_truncation_and_rendering_is_deterministic():
    data = _render_preview()
    assert data == _render_preview()                                        # mêmes données → même fichier → même empreinte
    pages = pdf.page_texts(data)
    n = len(pages)
    assert n >= 5 and all(f"Page {i}/{n}" in p for i, p in enumerate(pages, start=1))
    flat = compact(body_text(pages))
    for i in range(1, 16):
        assert compact(f"Clause {i} — œuvre, réparations, échéances") in flat
    assert flat.count(compact("Texte accentué : é è ê à ç ô û « guillemets » — tiret.")) == 15 * 30
    assert "?" not in "\n".join(pages)                                     # tous les caractères accentués sont encodés
    assert "https://tratra.net/verify/contract/" + "A" * 43 in "\n".join(pages)      # adresse de vérification entière, sur une ligne


def test_tables_never_split_a_row_across_pages():
    layout = pdf.Layout()
    rows = [(f"Libellé {i}", " ".join(["valeur"] * (8 + i % 5) + [f"fin{i}"])) for i in range(60)]
    layout.table(rows)
    data = layout.finish(lambda *_: None)
    pages = pdf.page_texts(data)
    assert len(pages) >= 2
    for i in range(60):
        holder = [p for p in pages if f"Libellé {i}\n" in p + "\n"]
        assert len(holder) == 1 and f"fin{i}" in holder[0], i                # libellé et fin de valeur sur la même page


def test_text_cleaning_and_wrapping():
    assert pdf.clean("réparations.. Puis ,, ensuite . . fin... et , virgule") == "réparations. Puis, ensuite. fin... et, virgule"
    assert pdf.clean("150 000 XOF → total ≥ 2") == "150 000 XOF -> total >= 2"
    lines = pdf.wrap("a" * 64 + " suite", 9, 120)
    assert all(pdf.width(line, 9) <= 120 for line in lines) and "".join(lines).replace(" suite", "") == "a" * 64


def test_mission_and_trade_coherence_is_checked_before_proposal():
    nounou = category("nounou", "Nounou")
    ServiceCategory.objects.create(name="Garde d'enfants", slug="garde-enfants-test", parent=nounou, keywords="enfants, baby-sitting, sortie d'école")
    principal, worker = person("parent_q"), pro("nounou_q")
    wrong = contracts.create_draft(principal, contract_data(worker, start=TODAY, cat=nounou, description="Nettoyage des locaux et petites réparations."), today=TODAY)
    right = contracts.create_draft(principal, contract_data(worker, start=TODAY, cat=nounou, description="Garde des enfants après l'école."), today=TODAY)
    assert len(coherence_warnings(wrong)) == 1 and "Nounou" in coherence_warnings(wrong)[0]
    assert coherence_warnings(right) == []
    body = APIClient()
    body.force_authenticate(principal)
    assert body.get(f"/handy/engagements/contracts/{wrong.pk}/").json()["quality_warnings"]
    body.force_authenticate(worker)
    assert body.get(f"/handy/engagements/contracts/{wrong.pk}/").json().get("quality_warnings", []) == []   # réservé à l'auteur
