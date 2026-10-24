"""Module Contrats — modèles juridiques et ANTI-FALSIFICATION : modèles « À valider juridiquement » (jamais utilisables sans revue
humaine), parcours BROUILLON → PROPOSÉ → ACCEPTÉ → SIGNÉ → ACTIF, document scellé (référence TRT-CTR, QR, jeton, SHA-256, signature
Ed25519), vérification publique sans donnée personnelle, PDF modifié, QR falsifié, jeton invalide, révocation, avenant sans
modification de l'original, rotation et révocation des clés, immuabilité en base, permissions."""
import base64
import re
import threading
from datetime import date, timedelta

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, connection, transaction
from rest_framework.test import APIClient

from backoffice import rbac
from engagements import documents, legal, signing
from engagements.models import ContractDocument, ContractSignature, ContractTemplate, EngagementContract, SigningKey
from engagements.services import contracts, templates as tpl
from engagements.services.common import EngagementError
from engagements.testing import category, contract_data, person, pro

pytestmark = pytest.mark.django_db
TODAY = date(2027, 3, 1)


def api(user=None):
    c = APIClient()
    if user is not None:
        c.force_authenticate(user)
    return c


def staff(name, role):
    rbac.ensure_roles()
    u = person(name, is_staff=True)
    u.groups.add(Group.objects.get(name=rbac.role_group_name(role)))
    return u


def complete(articles):
    """Le texte d'un modèle livré, après la revue juridique (emplacements complétés) — simulation de test, pas un avis juridique."""
    return [{**a, "body": a["body"].replace(legal.TO_COMPLETE, "[clause complétée par la revue]")} for a in articles]


def validated_template(relationship="independent", code="prestation-test", categories=()):
    reviewer = staff(f"juriste_{code}", "legal")
    articles = legal.independent_articles() if relationship == "independent" else legal.employment_articles()
    t = tpl.create(reviewer, {"code": code, "title": "Contrat de prestation (test)", "relationship": relationship, "articles": complete(articles),
                              "legal_references": [{"label": "Référence", "citation": "Texte vérifié", "status": "confirmée"}],
                              "categories": [c.pk for c in categories]})
    tpl.submit(t, reviewer)
    return tpl.validate(t, reviewer, reviewed_by_name="Cabinet de test", note="Revue effectuée sur le texte exact.")


def signed_contract(*, start=TODAY + timedelta(days=10)):
    validated_template()
    principal, worker = person("employeur"), pro("prestataire")
    worker.first_name, worker.last_name = "Aminata", "Kouassi"
    worker.save(update_fields=["first_name", "last_name"])
    c = contracts.create_draft(principal, contract_data(worker, start=start), today=TODAY)
    contracts.propose(c, principal, today=TODAY)
    c.refresh_from_db()
    contracts.accept(c, worker, c.terms_hash, today=TODAY)
    c.refresh_from_db()
    contracts.sign(c, worker, consent=True, today=TODAY)
    contracts.sign(c, principal, consent=True, today=TODAY)
    c.refresh_from_db()
    return c, principal, worker


def final_doc(c):
    return c.documents.get(kind="contract", stage="final")


def pdf_bytes(doc):
    with doc.file.open("rb") as fh:
        return fh.read()


def token_of(doc):
    """Le jeton n'existe en clair QUE dans le PDF (QR code et adresse imprimée) ; la base n'en garde que l'empreinte."""
    m = re.search(rb"/verify/contract/([A-Za-z0-9_-]{32,64})", pdf_bytes(doc))
    return m.group(1).decode() if m else None


# ── Modèles juridiques ────────────────────────────────────────────────────────────────────────────────────────────────

def test_delivered_templates_are_to_be_legally_validated_and_never_used_before():
    seeds = ContractTemplate.objects.filter(code__in=["emploi-domestique-salarie", "prestation-independante"])
    assert seeds.count() == 2 and set(seeds.values_list("status", flat=True)) == {ContractTemplate.TO_REVIEW}
    assert all("Conforme" not in label for _, label in ContractTemplate.STATUSES)
    employment = seeds.get(relationship="employment")
    keys = [a["key"] for a in employment.articles]
    assert keys[:3] == ["objet", "obligations_employeur", "obligations_salarie"]
    assert {"duree", "lieu_horaires", "remuneration", "repos_conges", "rupture", "litiges", "signatures"} <= set(keys)
    assert all(r["status"].startswith(("à confirmer", "texte réglementaire", "applicable SEULEMENT")) for r in employment.legal_references)
    # Aucun modèle validé : le contrat suit l'ancien parcours (acceptation simple), sans signature ni document.
    principal, worker = person("p_legacy"), pro("w_legacy")
    c = contracts.create_draft(principal, contract_data(worker, start=TODAY), today=TODAY)
    assert c.template is None and c.signature_required is False


def test_legal_validation_is_human_permissioned_and_refuses_unfinished_text():
    seed = ContractTemplate.objects.get(code="prestation-independante")
    ops, juriste = staff("ops1", "ops"), staff("jur1", "legal")
    url = f"/handy/backoffice/engagements/templates/{seed.pk}/validate/"
    payload = {"reviewed_by_name": "Me Exemple", "note": "Revue complète du modèle."}
    assert api(ops).post(url, payload, format="json").status_code == 403                 # rédiger n'est pas valider
    r = api(juriste).post(url, payload, format="json")
    assert r.status_code == 409 and r.json()["code"] == "incomplete"                       # emplacements « À compléter » restants
    with pytest.raises(EngagementError):
        tpl.check_usable(seed, "independent", None)


def test_articles_are_frozen_per_trade_and_part_of_the_accepted_terms():
    nounou = category("nounou", "Nounou")
    from engagements.testing import allow_employment

    allow_employment(nounou)
    validated_template("employment", code="domestique-test")
    principal, worker = person("famille"), pro("nounou_pro")
    c = contracts.create_draft(principal, contract_data(worker, start=TODAY, cat=nounou, work_relationship="employment", legal_notice_ack=True,
                                                         notice_period_days=30), today=TODAY)
    contracts.propose(c, principal, today=TODAY)
    c.refresh_from_db()
    assert c.template.code == "domestique-test" and c.signature_required and re.fullmatch(r"TRT-CTR-\d{4}-\d{6}", c.reference)
    titles = [a["title"] for a in c.articles]
    assert "Garde d'enfants" in titles and c.articles[0]["number"] == 1
    assert "{{" not in str(c.articles) and "Famille Test" in c.articles[0]["body"]
    assert contracts.snapshot(c)["articles"] == c.articles and contracts.terms_hash(c) == c.terms_hash


# ── Parcours et signature ─────────────────────────────────────────────────────────────────────────────────────────────

def test_draft_proposed_accepted_signed_active_with_a_sealed_document():
    c, principal, worker = signed_contract(start=TODAY + timedelta(days=10))
    assert c.status == "signed"
    docs = list(c.documents.order_by("issued_at"))
    assert [(d.kind, d.stage) for d in docs] == [("contract", "for_signature"), ("contract", "final")]
    final = docs[1]
    assert final.reference == c.reference and final.parent_id == docs[0].pk
    data = pdf_bytes(final)
    assert data.startswith(b"%PDF-") and documents.pdf.sha256(data) == final.sha256 and final.size == len(data)
    assert signing.verify(documents._payload({"reference": final.reference, "kind": "contract", "stage": "final", "version": final.version,
                                              "sha256": final.sha256, "terms_hash": final.terms_hash,
                                              "issued_at": final.issued_at.isoformat()}), final.signature, final.signing_key_id)["valid"]
    assert set(ContractSignature.objects.filter(contract=c).values_list("role", flat=True)) == {"principal", "worker"}
    assert c.installments.exists()                           # contrat conclu : échéances prévues (comme un contrat accepté jusqu'ici)
    contracts.sync(c, TODAY + timedelta(days=9))
    c.refresh_from_db()
    assert c.status == "signed"                              # rien ne commence avant la date de début
    contracts.sync(c, TODAY + timedelta(days=10))
    c.refresh_from_db()
    assert c.status == "active"


def test_signature_requires_consent_and_each_party_signs_once():
    validated_template()
    principal, worker = person("p_sig"), pro("w_sig")
    c = contracts.create_draft(principal, contract_data(worker, start=TODAY), today=TODAY)
    contracts.propose(c, principal, today=TODAY)
    c.refresh_from_db()
    with pytest.raises(EngagementError):
        contracts.sign(c, worker, consent=True, today=TODAY)                  # pas encore accepté par les deux parties
    contracts.accept(c, worker, c.terms_hash, today=TODAY)
    c.refresh_from_db()
    assert c.status == "accepted" and c.installments.count() == 0
    with pytest.raises(EngagementError) as e:
        contracts.sign(c, worker, consent=False, today=TODAY)
    assert e.value.code == "consent_required"
    r = api(worker).post(f"/handy/engagements/contracts/{c.pk}/sign/", {"consent": True}, format="json")
    assert r.status_code == 200 and r.json()["signatures"]["worker"] and not r.json()["signatures"]["principal"]
    api(worker).post(f"/handy/engagements/contracts/{c.pk}/sign/", {"consent": True}, format="json")    # rejeu : sans effet
    assert ContractSignature.objects.filter(contract=c).count() == 1
    stranger = person("curieux")
    assert api(stranger).post(f"/handy/engagements/contracts/{c.pk}/sign/", {"consent": True}, format="json").status_code == 404


# ── Vérification publique et falsifications ───────────────────────────────────────────────────────────────────────────

def test_public_verification_reveals_status_and_integrity_but_no_personal_data():
    c, principal, worker = signed_contract()
    final = final_doc(c)
    token = token_of(final)
    assert token and len(token) >= 40 and final.token_hash != token and token not in str(ContractDocument.objects.values())
    r = api().get(f"/handy/public/contracts/verify/{token}/")
    body = r.json()
    assert r.status_code == 200 and body["state"] == "authentic" and body["reference"] == c.reference and body["seal"]["valid"]
    text = str(body)
    assert b"Aminata Kouassi" in pdf_bytes(final)            # le PDF (parties seulement) porte les noms…
    for private in (principal.first_name, worker.first_name, worker.last_name, "Rue des Jardins", "150000", "150 000", "Abidjan"):
        assert private and private not in text                # … la vérification publique, jamais


@pytest.mark.parametrize("token", ["", "abc", "x" * 200, "abc'--;drop table", "A" * 43])
def test_forged_or_malformed_tokens_get_the_same_unknown_answer(token):
    signed_contract()
    r = api().get(f"/handy/public/contracts/verify/{token or 'vide'}/")
    assert r.status_code == 404 and r.json()["state"] == "unknown"


def test_the_exact_pdf_matches_and_a_modified_pdf_does_not():
    c, *_ = signed_contract()
    data = pdf_bytes(final_doc(c))
    ok = api().post("/handy/public/contracts/verify-file/", {"file": SimpleUploadedFile("c.pdf", data, "application/pdf")}, format="multipart")
    assert ok.json()["match"] is True and ok.json()["state"] == "authentic"
    forged = data.replace(b"150", b"950", 1) if b"150" in data else data[:-20] + b"%% retouche\n" + data[-20:]
    bad = api().post("/handy/public/contracts/verify-file/", {"file": SimpleUploadedFile("c.pdf", forged, "application/pdf")}, format="multipart")
    assert bad.status_code == 200 and bad.json()["match"] is False
    not_pdf = api().post("/handy/public/contracts/verify-file/", {"file": SimpleUploadedFile("c.pdf", b"hello", "application/pdf")}, format="multipart")
    assert not_pdf.status_code == 400


def test_the_document_to_sign_is_superseded_and_a_revoked_document_says_so():
    c, *_ = signed_contract()
    first = c.documents.get(stage="for_signature")
    assert documents.public_result(first)["state"] == "superseded"
    final = final_doc(c)
    rev = staff("ops_rev", "ops")
    r = api(rev).post(f"/handy/backoffice/engagements/documents/{final.pk}/revoke/", {"reason": "Émis par erreur (test)."}, format="json")
    assert r.status_code == 200
    body = api().get(f"/handy/public/contracts/verify/{token_of(final)}/").json()
    assert body["state"] == "revoked" and body["revoked_at"]
    support = staff("sup_rev", "support")
    assert api(support).post(f"/handy/backoffice/engagements/documents/{first.pk}/revoke/", {"reason": "Tentative non autorisée."},
                             format="json").status_code == 403


def test_documents_signatures_and_history_are_immutable_in_the_database():
    c, *_ = signed_contract()
    final = final_doc(c)
    for statement in ("UPDATE engagements_contractdocument SET sha256 = repeat('0', 64) WHERE id = %s",
                      "DELETE FROM engagements_contractdocument WHERE id = %s"):
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cur:
            cur.execute(statement, [final.pk])
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cur:
        cur.execute("UPDATE engagements_contractsignature SET role = 'worker' WHERE contract_id = %s", [c.pk])
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cur:
        cur.execute("DELETE FROM engagements_contractevent WHERE contract_id = %s", [c.pk])
    documents.revoke(final, actor=None, reason="Révocation de test unique.")
    with pytest.raises(DatabaseError), transaction.atomic():
        ContractDocument.objects.filter(pk=final.pk).update(revoked_at=None)                     # une révocation est définitive


def test_an_amendment_gets_its_own_sealed_document_and_the_original_is_untouched():
    c, principal, worker = signed_contract(start=TODAY)
    contracts.sync(c, TODAY)
    original = final_doc(c)
    before = (original.sha256, pdf_bytes(original))
    a = contracts.propose_amendment(c, principal, {"kind": "change", "changes": {"amount": "175000"}, "effective_date": TODAY.isoformat(),
                                                   "reason": "Revalorisation convenue."}, today=TODAY)
    contracts.respond_amendment(a, worker, True, today=TODAY)
    c.refresh_from_db()
    amendment_doc = c.documents.get(kind="amendment")
    assert amendment_doc.reference == f"{c.reference}-AV1" and amendment_doc.parent_id == original.pk and amendment_doc.amendment_id == a.pk
    original.refresh_from_db()
    assert (original.sha256, pdf_bytes(original)) == before
    public = documents.public_result(original)
    assert public["state"] == "authentic" and [x["reference"] for x in public["amendments"]] == [amendment_doc.reference]
    assert "175 000" in str(c.articles)                       # texte consolidé à jour, l'original signé reste intact


# ── Clés de scellement ────────────────────────────────────────────────────────────────────────────────────────────────

def test_key_rotation_keeps_old_documents_valid_and_revocation_flags_them():
    c, *_ = signed_contract()
    final = final_doc(c)
    old_kid = final.signing_key_id
    keys_admin = staff("root_keys", "super_admin")
    r = api(keys_admin).post("/handy/backoffice/engagements/signing-keys/", {"action": "rotate"}, format="json")
    assert r.status_code == 201 and r.json()["kid"] != old_kid
    assert documents.public_result(final)["state"] == "authentic" and documents.public_result(final)["seal"]["key_status"] == "retired"
    r = api(keys_admin).post("/handy/backoffice/engagements/signing-keys/", {"action": "revoke", "kid": old_kid, "reason": "Compromission (test)."},
                             format="json")
    assert r.status_code == 200
    assert documents.public_result(final)["state"] == "key_revoked"
    listing = api(keys_admin).get("/handy/backoffice/engagements/signing-keys/").json()
    assert "private" not in str(listing).lower() or "jamais affichées" in str(listing)
    assert all("private_key" not in k for k in listing["results"])
    published = api().get("/handy/public/contracts/keys/").json()
    assert {k["kid"] for k in published["keys"]} == set(SigningKey.objects.values_list("kid", flat=True))
    assert api(staff("ops_keys", "ops")).get("/handy/backoffice/engagements/signing-keys/").status_code == 403


def test_the_signing_key_is_encrypted_at_rest_and_only_one_is_active():
    key = signing.active_key()
    assert key.private_key_encrypted and key.public_key not in key.private_key_encrypted
    signing.generate_key()
    assert SigningKey.objects.filter(status=SigningKey.ACTIVE).count() == 1


# ── Confidentialité des documents ─────────────────────────────────────────────────────────────────────────────────────

def test_only_the_parties_download_the_pdf():
    c, principal, worker = signed_contract()
    final = final_doc(c)
    url = f"/handy/engagements/documents/{final.pk}/pdf/"
    for user in (principal, worker):
        r = api(user).get(url)
        assert r.status_code == 200 and r["Content-Type"] == "application/pdf" and b"".join(r.streaming_content).startswith(b"%PDF-")
    assert api(person("intrus")).get(url).status_code == 404
    assert api().get(url).status_code in (401, 403)
    detail = api(worker).get(f"/handy/engagements/contracts/{c.pk}/").json()
    assert detail["reference"] == c.reference and [d["stage"] for d in detail["documents"]] == ["for_signature", "final"]
    assert all("token" not in d for d in detail["documents"])


# ── Scellement vérifiable hors de Tratra, signatures distinctes, stockage altéré ─────────────────────────────────────

def test_anyone_can_verify_the_seal_with_the_published_public_key_and_party_signatures_are_separate():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    c, *_ = signed_contract()
    final = final_doc(c)
    body = api().get(f"/handy/public/contracts/verify/{token_of(final)}/").json()
    keys = {k["kid"]: k for k in api().get("/handy/public/contracts/keys/").json()["keys"]}
    seal = body["seal"]
    message = signing.canonical(seal["payload"])
    Ed25519PublicKey.from_public_bytes(base64.b64decode(keys[seal["kid"]]["public_key"])).verify(base64.b64decode(seal["signature"]), message)
    assert seal["payload"]["sha256"] == final.sha256 == body["sha256"]
    assert body["parties_signed"] is True                                   # signatures des parties : un fait, sans nom
    to_sign = c.documents.get(stage="for_signature")
    assert documents.public_result(to_sign)["parties_signed"] is False      # le scellement seul n'est pas une signature des parties


def test_an_altered_stored_file_is_never_served_and_is_reported(settings):
    c, principal, _ = signed_contract()
    final = final_doc(c)
    path = final.file.path
    with open(path, "r+b") as fh:                       # altération directe du stockage (hors application)
        fh.seek(-30, 2)
        fh.write(b"%% altere %%")
    assert documents.public_result(final)["state"] == "altered"
    r = api(principal).get(f"/handy/engagements/documents/{final.pk}/pdf/")
    assert r.status_code == 409 and r.json()["code"] == "document_altered"


def test_an_employment_template_never_serves_an_independent_contract():
    from engagements.testing import allow_employment

    validated_template("employment", code="salarie-seul")
    t = ContractTemplate.objects.get(code="salarie-seul")
    principal, worker = person("p_nature"), pro("w_nature")
    with pytest.raises(EngagementError) as e:
        contracts.create_draft(principal, contract_data(worker, start=TODAY, template=t.pk), today=TODAY)   # contrat indépendant
    assert e.value.code == "template_mismatch"
    c = contracts.create_draft(principal, contract_data(worker, start=TODAY), today=TODAY)
    assert c.template is None                                                   # aucun modèle indépendant validé : ancien parcours
    allow_employment()
    emp = contracts.create_draft(principal, contract_data(worker, start=TODAY, work_relationship="employment", legal_notice_ack=True,
                                                          notice_period_days=30), today=TODAY)
    assert emp.template_id == t.pk


# ── Concurrence ───────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_simultaneous_signatures_conclude_once_and_references_never_repeat():
    validated_template(code="concurrence")
    principal, worker = person("p_conc"), pro("w_conc")
    c = contracts.create_draft(principal, contract_data(worker, start=TODAY + timedelta(days=5)), today=TODAY)
    contracts.propose(c, principal, today=TODAY)
    c.refresh_from_db()
    contracts.accept(c, worker, c.terms_hash, today=TODAY)
    errors, barrier = [], threading.Barrier(2)

    def run(user):
        try:
            barrier.wait()
            contracts.sign(EngagementContract.objects.get(pk=c.pk), user, consent=True, today=TODAY)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(u,)) for u in (principal, worker)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    c.refresh_from_db()
    assert errors == [] and c.status == "signed"
    assert c.documents.filter(stage="final").count() == 1 and ContractSignature.objects.filter(contract=c).count() == 2

    refs, lock = [], threading.Lock()

    def allocate():
        try:
            ref = documents.allocate_reference(2027)
            with lock:
                refs.append(ref)
        finally:
            connection.close()

    workers = [threading.Thread(target=allocate) for _ in range(8)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()
    assert len(refs) == 8 and len(set(refs)) == 8 and all(re.fullmatch(r"TRT-CTR-2027-\d{6}", r) for r in refs)
