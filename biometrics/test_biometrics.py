"""KYC biométrique : parcours nominal, document absent, consentement, qualité, rejeu, expiration, tentatives, fournisseur indisponible, reprise,
suppression, et surtout : JAMAIS de validation automatique sans résultat réel d'un fournisseur ni sans humain."""
import io
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageDraw
from rest_framework.test import APIClient

from biometrics import consent, crypto, fraud, services
from biometrics.models import BiometricCapture, BiometricSession, BiometricVerification
from biometrics.providers import ProviderResult
from biometrics.testing import FakeProvider
from handy.models import HandymanDocument
from handy.test_eligibility import artisan
from intelligence.models import RiskCase
from trust.models import AuditEvent, BadgeAward

User = get_user_model()
pytestmark = pytest.mark.django_db
API = "/handy/kyc/biometric"


@pytest.fixture(autouse=True)
def configured(settings):
    settings.BIOMETRIC_ENABLED, settings.BIOMETRIC_PROVIDER = True, "none"
    settings.BIOMETRIC_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.BIOMETRIC_LIVENESS_THRESHOLD, settings.BIOMETRIC_MATCH_THRESHOLD = 0.9, 0.8
    settings.BIOMETRIC_MAX_ATTEMPTS_PER_DAY, settings.BIOMETRIC_MAX_ATTEMPTS_PER_WEEK = 3, 6
    settings.KYC_BIOMETRIC_REQUIRED = False


def jpeg(seed=0, bright=True, sharp=True, size=640) -> bytes:
    """Image synthétique exploitable : motifs contrastés (netteté) et luminosité moyenne contrôlée."""
    img = Image.new("RGB", (size, size), (130, 130, 130) if bright else (10, 10, 10))
    if sharp:
        d = ImageDraw.Draw(img)
        for i in range(0, size, 16):
            d.rectangle([i, (i * 7 + seed * 13) % size, i + 8, size], fill=(30 + (i + seed * 31) % 200, 90, 170 - (i + seed) % 90))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def member(name="bio_u", with_id=True):
    u = artisan(name, eligible=False)
    if with_id:
        HandymanDocument.objects.create(handyman=u.handyman_profile, document_type="id_card", file=ContentFile(jpeg(99), name="cni.jpg"))
    c = APIClient()
    c.force_authenticate(u)
    return u, c


def give_consent(c):
    return c.post(f"{API}/consent/", {"version": consent.version()}, format="json")


def start(c):
    return c.post(f"{API}/sessions/", {}, format="json")


def capture(c, s, i, data=None, token=None):
    kind = s["challenges"][i]["kind"]
    return c.post(f"{API}/sessions/{s['session_id']}/captures/", {"index": i, "kind": kind, "file": io.BytesIO(data or jpeg(i + 1))}, format="multipart",
                  HTTP_X_BIOMETRIC_TOKEN=token or s["token"])


def full_session(c, user=None, **kw):
    give_consent(c)
    s = start(c).json()
    for i in range(len(s["challenges"])):
        r = capture(c, s, i, jpeg(i + 1 + kw.get("seed", 0)))
        assert r.status_code == 201, r.content
    return s


def submit(c, s):
    return c.post(f"{API}/sessions/{s['session_id']}/submit/", {}, format="json", HTTP_X_BIOMETRIC_TOKEN=s["token"])


def test_consent_is_mandatory_traceable_and_versioned():
    u, c = member()
    assert start(c).json()["code"] == "consent_required"
    assert c.post(f"{API}/consent/", {"version": "1999"}, format="json").json()["code"] == "consent_version"
    st = c.get(f"{API}/").json()
    assert st["consent"]["granted"] is False and "Aucune décision n'est prise par la seule machine" in st["consent"]["text"] and "jamais à un service d'IA" in st["consent"]["text"]
    assert give_consent(c).status_code == 201
    from biometrics.models import BiometricConsent

    row = BiometricConsent.objects.get(user=u)
    assert row.text_sha256 == consent.text_sha256() and row.version == consent.version() and AuditEvent.objects.filter(action="biometric.consent_granted").exists()


def test_a_document_is_required_before_any_capture():
    u, c = member("bio_nodoc", with_id=False)
    give_consent(c)
    r = start(c)
    assert r.status_code == 409 and r.json()["code"] == "document_required"
    assert c.get(f"{API}/").json()["document"]["present"] is False


def test_disabled_feature_or_missing_key_gives_a_clear_503_and_the_human_alternative_stays_available(settings):
    u, c = member("bio_off")
    give_consent(c)
    settings.BIOMETRIC_ENABLED = False
    assert start(c).status_code == 503 and start(c).json()["code"] == "disabled"
    settings.BIOMETRIC_ENABLED, settings.BIOMETRIC_ENCRYPTION_KEY = True, ""
    assert start(c).json()["code"] == "not_configured"                                       # pas de capture sans clé de chiffrement
    r = c.post(f"{API}/human-review/", {"reason": "accessibility"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "pending_review"


def test_challenges_are_random_per_session_and_cover_every_requested_pose():
    u, c = member("bio_ch")
    give_consent(c)
    orders = set()
    for _ in range(12):
        BiometricSession.objects.filter(user=u).delete()
        kinds = tuple(x["kind"] for x in start(c).json()["challenges"])
        assert kinds[0] == "front" and kinds[-1] == "smile" and sorted(kinds[1:-1]) == ["down", "left", "right", "up"]
        orders.add(kinds)
    assert len(orders) > 1                                                                    # l'ordre change d'une session à l'autre


def test_nominal_flow_without_any_real_provider_ends_pending_human_review_never_validated():
    u, c = member()
    s = full_session(c)
    assert s["token"] and len(s["token"]) > 30
    r = submit(c, s)
    assert r.status_code == 200 and r.json()["outcome"] == "pending_review" and r.json()["human_review"] is True
    ver = BiometricVerification.objects.get(profile=u.handyman_profile)
    assert ver.status == "pending_review" and not ver.satisfied and ver.human_review_reason == "no_provider"
    assert not BadgeAward.objects.filter(profile=u.handyman_profile, code="VERIFIE").exists()      # aucun badge Vérifié sans KYC approuvé par un humain
    assert "score" not in str(r.json()).lower()                                               # aucun score côté utilisateur


def test_captures_are_encrypted_private_and_unreadable_without_the_key(settings):
    u, c = member("bio_enc")
    give_consent(c)
    s = start(c).json()
    data = jpeg(5)
    assert capture(c, s, 0, data).status_code == 201
    cap = BiometricCapture.objects.get(session_id=s["session_id"], index=0)
    with cap.file.open("rb") as fh:
        stored = fh.read()
    assert stored != data and not stored.startswith(b"\xff\xd8\xff") and services.read_capture(cap) == data
    settings.BIOMETRIC_ENCRYPTION_KEY = Fernet.generate_key().decode()                        # autre clé : illisible
    with pytest.raises(crypto.BiometricUnavailable):
        services.read_capture(cap)


def test_bad_quality_captures_are_refused_with_actionable_messages():
    u, c = member("bio_q")
    give_consent(c)
    s = start(c).json()
    dark = capture(c, s, 0, jpeg(1, bright=False, sharp=False))
    assert dark.status_code == 422 and dark.json()["code"] == "poor_quality" and "too_dark" in dark.json()["problems"] and "Éclairage" in dark.json()["detail"]
    blurry = capture(c, s, 0, jpeg(2, sharp=False))
    assert blurry.status_code == 422 and "blurry" in blurry.json()["problems"] and "floue" in blurry.json()["detail"]
    small = capture(c, s, 0, jpeg(3, size=200))
    assert small.status_code == 422 and "too_small" in small.json()["problems"]
    assert capture(c, s, 0, b"GIF89a not a jpeg").json()["code"] == "not_jpeg"
    assert capture(c, s, 0, b"\xff\xd8\xff garbage").json()["code"] == "unreadable"
    assert BiometricCapture.objects.count() == 0                                              # rien n'est conservé tant que la capture n'est pas exploitable
    assert capture(c, s, 0, jpeg(4)).status_code == 201


def test_replay_wrong_step_wrong_token_and_duplicate_frames_are_refused():
    u, c = member("bio_rp")
    give_consent(c)
    s = start(c).json()
    first = jpeg(7)
    assert capture(c, s, 0, first).status_code == 201
    assert capture(c, s, 0, jpeg(8)).json()["code"] == "replayed"                             # même rang : refusé
    assert capture(c, s, 1, first).json()["code"] == "duplicate_frame"                        # même image pour deux étapes
    assert "identical_frames" in BiometricSession.objects.get(pk=s["session_id"]).anomalies
    wrong = c.post(f"{API}/sessions/{s['session_id']}/captures/", {"index": 1, "kind": "smile", "file": io.BytesIO(jpeg(9))}, format="multipart", HTTP_X_BIOMETRIC_TOKEN=s["token"])
    assert wrong.json()["code"] == "wrong_challenge"
    assert capture(c, s, 1, jpeg(10), token="faux-jeton").status_code == 403
    other, oc = member("bio_other")
    assert capture(oc, s, 1, jpeg(11)).status_code == 403                                     # la session d'un autre compte est inaccessible
    assert c.post(f"{API}/sessions/{s['session_id']}/submit/", {}, format="json").status_code == 403    # pas de jeton : refusé


def test_incomplete_session_cannot_be_submitted_and_double_submit_is_refused():
    u, c = member("bio_inc")
    give_consent(c)
    s = start(c).json()
    capture(c, s, 0, jpeg(1))
    r = submit(c, s)
    assert r.status_code == 409 and r.json()["code"] == "incomplete" and r.json()["remaining"] == len(s["challenges"]) - 1
    u2, c2 = member("bio_dbl")
    s2 = full_session(c2, u2)
    assert submit(c2, s2).status_code == 200
    again = submit(c2, s2)
    assert again.status_code == 409 and again.json()["code"] == "already_submitted"


def test_session_expires_and_a_new_one_can_be_started_after_expiry():
    u, c = member("bio_exp")
    give_consent(c)
    s = start(c).json()
    BiometricSession.objects.filter(pk=s["session_id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
    r = capture(c, s, 0, jpeg(1))
    assert r.status_code == 410 and r.json()["code"] == "expired"
    assert BiometricSession.objects.get(pk=s["session_id"]).status == "expired"               # l'expiration est conservée même si l'appel est refusé
    assert start(c).status_code == 201


def test_resume_after_interruption_rotates_the_token_and_keeps_received_captures():
    u, c = member("bio_res")
    give_consent(c)
    s = start(c).json()
    assert capture(c, s, 0, jpeg(1)).status_code == 201 and capture(c, s, 1, jpeg(2)).status_code == 201
    again = start(c).json()                                                                    # l'application a été fermée puis rouverte
    assert again["session_id"] == s["session_id"] and again["captured"] == [0, 1] and again["token"] != s["token"]
    assert capture(c, s, 2, jpeg(3)).status_code == 403                                       # l'ancien jeton ne sert plus
    assert capture(c, again, 2, jpeg(3)).status_code == 201
    assert BiometricSession.objects.filter(user=u).count() == 1


def test_attempts_are_limited_per_day_and_the_alternative_is_offered(settings):
    u, c = member("bio_lim")
    give_consent(c)
    for _ in range(3):
        BiometricSession.objects.filter(user=u).update(status="cancelled")
        assert start(c).status_code == 201
    BiometricSession.objects.filter(user=u).update(status="cancelled")
    r = start(c)
    assert r.status_code == 429 and r.json()["code"] == "too_many_attempts" and "équipe Tratra" in r.json()["detail"]
    st = c.get(f"{API}/").json()
    assert st["attempts"]["day"] == 3 and st["alternative"]["available"] is True


def provider_run(c, user, result=None, error=False, **kw):
    fake = FakeProvider(result, error)
    s = full_session(c, user, **kw)
    import biometrics.services as svc

    original = svc.get_provider
    svc.get_provider = lambda: fake
    try:
        out = submit(c, s)
    finally:
        svc.get_provider = original
    return out, fake, s


def test_server_decides_from_real_provider_results_and_thresholds():
    ok_user, ok_client = member("bio_ok")
    r, fake, _ = provider_run(ok_client, ok_user, ProviderResult(True, 0.97, 0.91))
    assert r.json()["outcome"] == "passed" and fake.calls and len(fake.calls[0]["frames"]) == 6 and fake.calls[0]["document"]
    ver = BiometricVerification.objects.get(profile=ok_user.handyman_profile)
    assert ver.status == "passed" and ver.satisfied
    for name, res, expected in (("bio_lv", ProviderResult(False, 0.2, 0.9), "failed"), ("bio_lw", ProviderResult(True, 0.5, 0.95), "failed"),
                                ("bio_mt", ProviderResult(True, 0.97, 0.4), "inconclusive"), ("bio_ms", ProviderResult(True, 0.97, None), "inconclusive"),
                                ("bio_sp", ProviderResult(True, 0.99, 0.99, ["screen_replay"]), "failed")):
        u, c = member(name)
        out, _, s = provider_run(c, u, res)
        assert out.json()["outcome"] == expected, name
        assert not BiometricVerification.objects.get(profile=u.handyman_profile).satisfied
    sess = BiometricSession.objects.get(user=ok_user)
    assert sess.liveness_score == 0.97 and sess.match_score == 0.91 and sess.thresholds == {"liveness": 0.9, "match": 0.8}


def test_a_non_comparable_document_never_gives_a_favorable_result():
    u = artisan("bio_pdf", eligible=False)
    HandymanDocument.objects.create(handyman=u.handyman_profile, document_type="id_card", file=ContentFile(b"%PDF-1.4 x", name="cni.pdf"))
    c = APIClient()
    c.force_authenticate(u)
    out, _, s = provider_run(c, u, ProviderResult(True, 0.99, 0.99))
    assert out.json()["outcome"] == "inconclusive" and "document_not_comparable" in BiometricSession.objects.get(pk=s["session_id"]).anomalies


def test_provider_outage_leaves_the_file_pending_human_review():
    u, c = member("bio_down")
    out, _, s = provider_run(c, u, error=True)
    assert out.json()["outcome"] == "provider_error" and out.json()["human_review"] is True
    ver = BiometricVerification.objects.get(profile=u.handyman_profile)
    assert ver.status == "pending_review" and ver.human_review_reason == "provider_unavailable" and not ver.satisfied
    assert RiskCase.objects.filter(subject=u, kind="biometric_technical").exists()


def test_fraud_signals_repeated_attempts_and_replayed_images_without_any_face_similarity():
    u, c = member("bio_fr")
    for i in range(3):
        BiometricSession.objects.filter(user=u).update(status="cancelled")
        out, _, s = provider_run(c, u, ProviderResult(False, 0.1, 0.9), seed=i * 20)
    case = RiskCase.objects.get(subject=u, kind="biometric_attempts")
    assert case.status == "open" and "difficultés techniques ou tentatives répétées" in case.explanation and case.evidence["attempts_24h"] >= 3
    a, ca = member("bio_ra")
    full_session(ca, a, seed=40)
    b, cb = member("bio_rb")
    give_consent(cb)
    sb = start(cb).json()
    dup = BiometricCapture.objects.filter(session__user=a).first()
    assert capture(cb, sb, 0, services.read_capture(dup)).status_code == 201                  # accepté mais signalé
    assert "capture_reused_elsewhere" in BiometricSession.objects.get(pk=sb["session_id"]).anomalies
    fraud.after_session(BiometricSession.objects.get(pk=sb["session_id"]))
    lb = RiskCase.objects.get(subject=b, kind="liveness_bypass")
    assert lb.priority == 3 and "jamais une preuve" in lb.explanation
    assert not [f for f in dir(fraud) if "similar" in f.lower() or "face_match" in f.lower()]    # aucune comparaison de visages entre comptes


def test_withdrawing_consent_deletes_all_captures_and_revokes_the_biometric_status():
    u, c = member("bio_wd")
    out, _, s = provider_run(c, u, ProviderResult(True, 0.97, 0.91))
    assert BiometricCapture.objects.filter(session__user=u, deleted_at__isnull=True).count() == 6
    r = c.delete(f"{API}/consent/")
    assert r.status_code == 200 and r.json()["captures_deleted"] == 6
    assert not BiometricCapture.objects.filter(session__user=u, deleted_at__isnull=True).exists()
    ver = BiometricVerification.objects.get(profile=u.handyman_profile)
    assert ver.status == "not_started" and AuditEvent.objects.filter(action="biometric.consent_withdrawn").exists()
    assert c.get(f"{API}/").json()["consent"]["granted"] is False


def test_retention_task_expires_abandoned_sessions_and_purges_old_captures():
    u, c = member("bio_ret")
    out, _, s = provider_run(c, u, ProviderResult(True, 0.97, 0.91))
    BiometricSession.objects.filter(pk=s["session_id"]).update(completed_at=timezone.now() - timedelta(days=31))
    u2, c2 = member("bio_ret2")
    give_consent(c2)
    s2 = start(c2).json()
    capture(c2, s2, 0, jpeg(60))
    BiometricSession.objects.filter(pk=s2["session_id"]).update(expires_at=timezone.now() - timedelta(days=3))
    stats = services.expire_and_purge()
    assert stats["expired"] == 1 and stats["captures_deleted"] == 7
    assert services.expire_and_purge() == {"expired": 0, "captures_deleted": 0}               # rejouable
    assert not BiometricCapture.objects.filter(deleted_at__isnull=True).exists()


def test_state_never_exposes_scores_thresholds_or_the_session_token_twice():
    u, c = member("bio_st")
    give_consent(c)
    s = start(c).json()
    st = c.get(f"{API}/").json()
    assert "token" not in st["active_session"] and "token" not in str(st)
    assert "score" not in str(st).lower() and "threshold" not in str(st).lower() and "seuil" not in str(st).lower()
    assert st["active_session"]["session_id"] == s["session_id"] and st["provider_configured"] is False


def test_failed_attempts_still_count_against_the_token_usage_limit(settings):
    u, c = member("bio_tok")
    give_consent(c)
    s = start(c).json()
    for _ in range(services.MAX_TOKEN_USES):
        capture(c, s, 0, b"GIF89a not a jpeg")                                                # chaque échec compte, même annulé
    r = capture(c, s, 0, jpeg(1))
    assert r.status_code == 410 and r.json()["code"] == "token_exhausted"


# ═══ Badge Vérifié ═══════════════════════════════════════════════════════════════════════════════════════════════════

def verified_badge(profile):
    from trust import engine

    engine.evaluate_profile(profile, trigger="test")
    return BadgeAward.objects.filter(profile=profile, code="VERIFIE", ended_at__isnull=True).exists()


def test_verified_badge_requires_the_biometric_check_or_an_approved_alternative_only_when_the_policy_is_on(settings):
    u = artisan("bio_bdg")                                                                      # KYC approuvé et dossier complet (éligible)
    profile = u.handyman_profile
    assert verified_badge(profile)                                                              # politique désactivée : comportement historique inchangé
    settings.KYC_BIOMETRIC_REQUIRED = True
    assert not verified_badge(profile)                                                          # aucune vérification faciale : plus de badge
    ver = services.verification_for(profile)
    for status in ("pending_review", "failed", "inconclusive", "in_progress", "rejected", "recapture_requested"):
        BiometricVerification.objects.filter(pk=ver.pk).update(status=status)
        assert not verified_badge(profile), status                                              # ni attente, ni échec, ni refus ne donnent le badge
    for status in ("passed", "manual_approved", "alternative_approved"):
        BiometricVerification.objects.filter(pk=ver.pk).update(status=status)
        assert verified_badge(profile), status                                                  # résultat satisfaisant, revue humaine ou alternative approuvée
    BiometricVerification.objects.filter(pk=ver.pk).update(status="alternative_approved")
    u.is_active = False
    u.save()
    assert not verified_badge(profile)                                                          # le KYC/compte reste une condition : jamais le badge sur la seule biométrie


def test_a_biometric_pass_alone_never_grants_the_badge_without_an_approved_kyc(settings):
    settings.KYC_BIOMETRIC_REQUIRED = True
    u, c = member("bio_nokyc")                                                                  # pièce d'identité en attente : KYC NON approuvé
    out, _, s = provider_run(c, u, ProviderResult(True, 0.99, 0.99))
    assert out.json()["outcome"] == "passed"
    assert not verified_badge(u.handyman_profile)
