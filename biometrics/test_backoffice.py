"""Back-Office KYC biométrique : séparation des droits (statut vs données biométriques), accès journalisé aux captures, décisions motivées,
approbation seulement après les contrôles requis, aucun badge sans KYC."""
import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model

from backoffice.test_people import api as bo_api, staff
from biometrics import services
from biometrics.models import BiometricCapture, BiometricVerification
from biometrics.providers import ProviderResult
from biometrics.test_biometrics import give_consent, jpeg, member, provider_run, start, capture, full_session  # noqa: F401
from handy.models import HandymanDocument, Notification
from intelligence import risk
from intelligence.models import RiskCase
from trust.models import AuditEvent, BadgeAward

pytestmark = pytest.mark.django_db
BO = "/handy/backoffice"


@pytest.fixture(autouse=True)
def configured(settings):
    settings.BIOMETRIC_ENABLED, settings.BIOMETRIC_PROVIDER = True, "none"
    settings.BIOMETRIC_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.BIOMETRIC_LIVENESS_THRESHOLD, settings.BIOMETRIC_MATCH_THRESHOLD = 0.9, 0.8
    settings.BIOMETRIC_MAX_ATTEMPTS_PER_DAY, settings.BIOMETRIC_MAX_ATTEMPTS_PER_WEEK = 3, 6
    settings.KYC_BIOMETRIC_REQUIRED = False


def verified_session(name="bo_bio"):
    u, c = member(name)
    out, _, s = provider_run(c, u, ProviderResult(True, 0.97, 0.91))
    return u, c, s


def test_kyc_reviewers_see_status_and_anomalies_but_never_scores_or_captures():
    u, c, s = verified_session()
    ops, admin = bo_api(staff("bo_ops", "ops")), bo_api(staff("bo_adm", "super_admin"))
    pid = u.handyman_profile.pk
    low = ops.get(f"{BO}/kyc/{pid}/biometric/").json()
    assert low["status"] == "passed" and low["can_view_captures"] is False and low["sessions"][0]["outcome"] == "passed"
    assert "liveness_score" not in str(low) and "match_score" not in str(low) and "captures" not in low["sessions"][0] and "thresholds" not in str(low)
    full = admin.get(f"{BO}/kyc/{pid}/biometric/").json()
    sess = full["sessions"][0]
    assert full["can_view_captures"] and sess["liveness_score"] == 0.97 and sess["match_score"] == 0.91 and len(sess["captures"]) == 6 and sess["thresholds"]["match"] == 0.8
    assert bo_api(staff("bo_sup", "support")).get(f"{BO}/kyc/{pid}/biometric/").status_code == 403          # sans droit KYC : rien


def test_capture_images_need_the_biometric_right_are_no_store_and_every_view_is_audited():
    u, c, s = verified_session("bo_cap")
    cap = BiometricCapture.objects.filter(session_id=s["session_id"]).first()
    ops, admin = bo_api(staff("bo_ops2", "ops")), bo_api(staff("bo_adm2", "super_admin"))
    assert ops.get(f"{BO}/kyc/biometric/captures/{cap.pk}/").status_code == 403
    r = admin.get(f"{BO}/kyc/biometric/captures/{cap.pk}/")
    assert r.status_code == 200 and r["Content-Type"] == "image/jpeg" and "no-store" in r["Cache-Control"] and r.content.startswith(b"\xff\xd8\xff")
    assert AuditEvent.objects.filter(action="backoffice.kyc.biometric_capture_viewed").count() == 1
    BiometricCapture.objects.filter(pk=cap.pk).update(deleted_at=cap.created_at)
    assert admin.get(f"{BO}/kyc/biometric/captures/{cap.pk}/").status_code == 404                           # supprimée : introuvable


def test_reviewers_can_ask_for_recapture_documents_or_manual_review_but_not_approve_or_refuse():
    u, c, s = verified_session("bo_dec")
    ops = bo_api(staff("bo_ops3", "ops"))
    url, pid = f"{BO}/kyc/{u.handyman_profile.pk}/biometric/decision/", u.handyman_profile.pk
    for decision in ("approve_manual", "approve_alternative", "reject"):
        assert ops.post(url, {"decision": decision, "reason": "Motif suffisamment long"}, format="json").status_code == 403
    assert ops.post(url, {"decision": "request_recapture", "reason": "court"}, format="json").json()["code"] == "reason_required"
    assert ops.post(url, {"decision": "n_importe_quoi", "reason": "Motif suffisamment long"}, format="json").json()["code"] == "decision"
    r = ops.post(url, {"decision": "request_recapture", "reason": "Photo de gauche trop sombre à refaire"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "recapture_requested"
    assert Notification.objects.filter(user=u, title="Nouvelle capture demandée").exists()
    assert ops.post(url, {"decision": "request_documents", "reason": "Un passeport en cours de validité est requis"}, format="json").json()["status"] == "documents_requested"
    assert ops.post(url, {"decision": "open_review", "reason": "Résultat technique à revoir manuellement"}, format="json").json()["status"] == "pending_review"
    assert AuditEvent.objects.filter(action__startswith="backoffice.kyc.biometric_").count() == 3


def test_approval_requires_the_checks_and_the_biometric_decision_alone_never_gives_the_badge(settings):
    settings.KYC_BIOMETRIC_REQUIRED = True
    u, c = member("bo_apr")
    out, _, s = provider_run(c, u, ProviderResult(True, 0.4, 0.4))                                      # résultat défavorable : revue humaine nécessaire
    admin = bo_api(staff("bo_adm3", "super_admin"))
    pid = u.handyman_profile.pk
    url = f"{BO}/kyc/{pid}/biometric/decision/"
    blocked = admin.post(url, {"decision": "approve_manual", "reason": "Visage conforme à la pièce après examen"}, format="json")
    assert blocked.status_code == 409 and blocked.json()["code"] == "checks_required" and "pièce d'identité non approuvée" in blocked.json()["detail"]
    HandymanDocument.objects.filter(handyman=u.handyman_profile).update(status="approved")                # le KYC documentaire est approuvé par un humain
    risk.propose(u.pk, "liveness_bypass", 3, "Indice technique", {}, dedupe_key="x", source="biometrics")
    assert admin.post(url, {"decision": "approve_manual", "reason": "Visage conforme à la pièce après examen"}, format="json").json()["code"] == "checks_required"
    RiskCase.objects.filter(subject=u).update(status="dismissed")
    ok = admin.post(url, {"decision": "approve_manual", "reason": "Visage conforme à la pièce après examen"}, format="json")
    assert ok.status_code == 200 and ok.json()["status"] == "manual_approved" and ok.json()["satisfied"] is True and ok.json()["decided_by"]
    from trust import engine

    engine.evaluate_profile(u.handyman_profile)
    assert not BadgeAward.objects.filter(profile=u.handyman_profile, code="VERIFIE", ended_at__isnull=True).exists()   # profil non approuvé/complet : jamais le badge sur la seule biométrie
    assert [d["decision"] for d in admin.get(f"{BO}/kyc/{pid}/biometric/").json()["decisions"]] == ["approve_manual"]


def test_the_alternative_procedure_approved_by_a_human_satisfies_the_requirement_and_a_refusal_blocks_new_sessions(settings):
    settings.KYC_BIOMETRIC_REQUIRED = True
    u, c = member("bo_alt")
    assert c.post("/handy/kyc/biometric/human-review/", {"reason": "accessibility"}, format="json").json()["status"] == "pending_review"
    HandymanDocument.objects.filter(handyman=u.handyman_profile).update(status="approved")
    admin = bo_api(staff("bo_adm4", "super_admin"))
    url = f"{BO}/kyc/{u.handyman_profile.pk}/biometric/decision/"
    assert admin.post(url, {"decision": "approve_alternative", "reason": "Identité vérifiée en agence avec la pièce originale"}, format="json").json()["status"] == "alternative_approved"
    assert BiometricVerification.objects.get(profile=u.handyman_profile).satisfied
    u2, c2 = member("bo_ref")
    give_consent(c2)
    HandymanDocument.objects.filter(handyman=u2.handyman_profile).update(status="approved")
    assert admin.post(f"{BO}/kyc/{u2.handyman_profile.pk}/biometric/decision/", {"decision": "reject", "reason": "Visage non conforme à la pièce après examen"}, format="json").json()["status"] == "rejected"
    r = start(c2)
    assert r.status_code == 409 and r.json()["code"] == "rejected" and "recours" in r.json()["detail"]        # recours : contact du support


def test_kyc_list_shows_the_biometric_status_only():
    u, c, s = verified_session("bo_list")
    ops = bo_api(staff("bo_ops4", "ops"))
    rows = ops.get(f"{BO}/kyc/").json()["results"]
    row = next(r for r in rows if r["profile_id"] == u.handyman_profile.pk)
    assert row["biometric_status"] == "passed" and "score" not in str(row)
