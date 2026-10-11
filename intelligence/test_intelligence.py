"""Contrôle intelligent : repli DeepSeek → Anthropic, garde-fous KYC (rien ne sort sans activation explicite + base légale), analyse de documents
explicable, doublons par identifiants forts uniquement, dossiers de risque PROPOSÉS puis tranchés par un humain, aucun effet automatique."""
from datetime import date, timedelta
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.utils import timezone

from backoffice.test_people import api as bo_api, staff
from handy.models import Booking, HandymanDocument
from handy.test_eligibility import artisan
from intelligence import ai, documents, risk
from intelligence.models import AIRun, DocumentAnalysis, RiskCase
from trust.models import AuditEvent, BadgeAward

User = get_user_model()
pytestmark = pytest.mark.django_db
BO = "/handy/backoffice"


@pytest.fixture(autouse=True)
def no_keys(settings):
    settings.AI_PROVIDERS, settings.AI_DEEPSEEK_API_KEY, settings.AI_ANTHROPIC_API_KEY = "deepseek,anthropic", "", ""
    settings.AI_KYC_EXTERNAL_ENABLED, settings.AI_KYC_LEGAL_BASIS = False, ""


def reply(payload):
    r = mock.Mock()
    r.raise_for_status.return_value = None
    r.json.return_value = payload
    return r


DEEPSEEK_OK = {"choices": [{"message": {"content": '{"ok": true}'}}]}
ANTHROPIC_OK = {"content": [{"type": "text", "text": '```json\n{"surname": "KONE", "given_names": "Awa", "detected_type": "id_card"}\n```'}]}


# ═══ Routeur d'IA ═══════════════════════════════════════════════════════════════════════════════════════════════════

def test_no_provider_configured_means_no_call_and_a_clear_error():
    with mock.patch("intelligence.ai.requests.post") as post, pytest.raises(ai.AIUnavailable) as e:
        ai.complete("t", "s", "u")
    assert e.value.code == "not_configured" and not post.called


def test_deepseek_is_primary_and_anthropic_takes_over_on_failure(settings):
    settings.AI_DEEPSEEK_API_KEY, settings.AI_ANTHROPIC_API_KEY = "sk-deepseek-secret", "sk-anthropic-secret"
    with mock.patch("intelligence.ai.requests.post", return_value=reply(DEEPSEEK_OK)) as post:
        out = ai.complete("t", "s", "u")
    assert out["provider"] == "deepseek" and out["data"] == {"ok": True} and post.call_count == 1
    assert "deepseek.com" in post.call_args.args[0] and post.call_args.kwargs["headers"]["Authorization"].startswith("Bearer ")
    seq = [TimeoutError("boom"), reply(ANTHROPIC_OK)]
    with mock.patch("intelligence.ai.requests.post", side_effect=seq) as post:
        out = ai.complete("t", "s", "u")
    assert out["provider"] == "anthropic" and post.call_count == 2
    assert AIRun.objects.filter(provider="deepseek", ok=False).count() == 1 and AIRun.objects.filter(provider="anthropic", ok=True).count() == 1
    with mock.patch("intelligence.ai.requests.post", side_effect=TimeoutError("x")), pytest.raises(ai.AIUnavailable) as e:
        ai.complete("t", "s", "u")
    assert e.value.code == "all_failed"
    blob = str(list(AIRun.objects.values())) + e.value.detail
    assert "secret" not in blob and "boom" not in blob                                              # ni clé ni contenu dans les journaux


def test_images_only_reach_a_provider_that_reads_them_and_kyc_needs_explicit_enable_and_legal_basis(settings):
    settings.AI_DEEPSEEK_API_KEY, settings.AI_ANTHROPIC_API_KEY = "k1", "k2"
    with mock.patch("intelligence.ai.requests.post", return_value=reply(ANTHROPIC_OK)) as post:
        with pytest.raises(ai.AIUnavailable) as e:
            ai.complete("kyc", "s", "u", images=[("image/png", b"x")], sensitive=True)             # clés présentes mais pas d'activation
        assert e.value.code == "external_not_allowed" and not post.called
        settings.AI_KYC_EXTERNAL_ENABLED = True
        with pytest.raises(ai.AIUnavailable):
            ai.complete("kyc", "s", "u", images=[("image/png", b"x")], sensitive=True)             # activé mais sans base légale
        assert not post.called
        settings.AI_KYC_LEGAL_BASIS = "Consentement explicite du titulaire ; accord de traitement signé"
        out = ai.complete("kyc", "s", "u", images=[("image/png", b"x")], sensitive=True)
    assert out["provider"] == "anthropic" and post.call_count == 1 and "anthropic.com" in post.call_args.args[0]     # DeepSeek ne reçoit jamais d'image
    assert ai.status()["kyc_external_allowed"] is True
    assert "k1" not in str(ai.status()) and "k2" not in str(ai.status()) and "Consentement" not in str(ai.status())


# ═══ Analyse de documents ═══════════════════════════════════════════════════════════════════════════════════════════

def _pro(name, first="Awa", last="Kone"):
    u = artisan(name)
    u.first_name, u.last_name = first, last
    u.save()
    return u


def _doc(user, data=b"fichier-1", doc_type="id_card", **kw):
    return HandymanDocument.objects.create(handyman=user.handyman_profile, document_type=doc_type, file=ContentFile(data, name="cni.png"), **kw)


def _text(name="KONE", given="AWA", expiry="12/03/2031", number="CI0123456"):
    return f"CARTE NATIONALE D'IDENTITE\nNOM: {name}\nPRÉNOMS: {given}\nNÉ LE 04/05/1990\nVALABLE JUSQU'AU {expiry}\nN° {number}\n"


def run(doc, text, by=None):
    with mock.patch("intelligence.documents.local_ocr", return_value=text):
        return documents.analyze(doc, by=by)


def test_a_consistent_document_is_low_risk_but_still_needs_a_human_and_changes_nothing():
    u = _pro("an_ok")
    doc, badges = _doc(u), list(BadgeAward.objects.filter(profile=u.handyman_profile).values_list("pk", "code", "ended_at"))
    approved_before = u.handyman_profile.is_approved
    a = run(doc, _text())
    by = {c["code"]: c["status"] for c in a.checks}
    assert a.risk_level == "low" and by["name_match"] == "ok" and by["expiry"] == "ok" and by["type_match"] == "ok" and a.ocr_engine == "tesseract" and not a.external_used
    assert "décision reste celle de l'équipe" in a.summary and "preuve d'authenticité" in a.ocr_disclaimer
    doc.refresh_from_db()
    u.handyman_profile.refresh_from_db()
    assert doc.status == "pending" and u.handyman_profile.is_approved == approved_before                      # jamais d'approbation automatique
    assert list(BadgeAward.objects.filter(profile=u.handyman_profile).values_list("pk", "code", "ended_at")) == badges   # ni de badge
    assert a.fields["document_number"] == "•••456" and "CI0123456" not in str(a.fields)                      # numéro jamais en clair
    assert len(a.id_fingerprint) == 64 and a.id_fingerprint != documents.fingerprint("CI0123457")


def test_expired_or_mismatching_documents_raise_explained_checks_and_proposed_cases():
    u = _pro("an_bad")
    a = run(_doc(u), _text(name="TRAORE", given="MOUSSA", expiry="01/02/2020"))
    by = {c["code"]: c for c in a.checks}
    assert a.risk_level == "high" and by["expiry"]["status"] == "fail" and "Expiré" in by["expiry"]["detail"] and by["name_match"]["status"] == "fail"
    kinds = set(RiskCase.objects.filter(subject=u).values_list("kind", flat=True))
    assert {"kyc_expired", "document_inconsistent"} <= kinds
    assert all(c.status == "open" for c in RiskCase.objects.filter(subject=u))                              # proposés, jamais tranchés
    u.refresh_from_db()
    assert u.is_active


def test_without_any_ocr_the_check_is_unknown_and_manual():
    u = _pro("an_none")
    with mock.patch("intelligence.documents.local_ocr", return_value=None):
        a = documents.analyze(_doc(u), by=None)
    assert a.ocr_engine == "none" and a.risk_level in ("unknown", "medium") and any(c["code"] == "ocr" and c["status"] == "unknown" for c in a.checks)
    assert "manuel" in a.summary.lower() or "manuel" in str(a.checks).lower()


def test_same_file_or_same_document_number_on_two_accounts_is_a_strong_signal_but_a_shared_name_alone_is_not():
    a, b, c = _pro("dup_a"), _pro("dup_b"), _pro("dup_c")                                                   # a, b, c portent le MÊME nom
    run(_doc(a, b"meme-fichier"), _text(number="CI111111"))
    second = run(_doc(b, b"meme-fichier"), _text(number="CI111111"))
    by = {x["code"]: x["status"] for x in second.checks}
    assert by["duplicate_file"] == "fail" and by["duplicate_identifier"] == "fail"
    cases = RiskCase.objects.filter(kind="duplicate_account", subject=b)
    assert cases.exists() and a.pk in cases.first().related_users and cases.first().priority == 3
    third = run(_doc(c, b"autre-fichier"), _text(number="CI999999"))
    assert {x["code"]: x["status"] for x in third.checks}["duplicate_file"] == "ok"
    assert not RiskCase.objects.filter(subject=c).exists()                                                  # même nom, aucun identifiant fort : aucun dossier


def test_external_vision_only_when_explicitly_allowed(settings):
    u = _pro("an_ext")
    settings.AI_ANTHROPIC_API_KEY = "k-secret"
    with mock.patch("intelligence.documents.local_ocr", return_value=None), mock.patch("intelligence.ai.requests.post", return_value=reply(ANTHROPIC_OK)) as post:
        documents.analyze(_doc(u, b"x1"), by=None)
        assert not post.called                                                                              # par défaut : rien ne sort
        settings.AI_KYC_EXTERNAL_ENABLED = True
        documents.analyze(_doc(u, b"x2"), by=None)
        assert not post.called                                                                              # activé sans base légale : rien ne sort
        settings.AI_KYC_LEGAL_BASIS = "Consentement explicite ; accord de traitement"
        a = documents.analyze(_doc(u, b"x3"), by=None)
    assert post.call_count == 1 and a.external_used and a.ocr_engine == "anthropic" and a.legal_basis.startswith("Consentement")
    assert a.fields["surname"] == "KONE" and "k-secret" not in str(a.__dict__)


# ═══ Détection ══════════════════════════════════════════════════════════════════════════════════════════════════════

def test_scan_proposes_cases_from_strong_signals_only_and_is_replayable():
    p1 = User.objects.create_user("sc_p1", "sc1@x.test", "pass1234", phone="+2250701020304")
    p2 = User.objects.create_user("sc_p2", "sc2@x.test", "pass1234", phone="0701020304")                    # même numéro, autre format
    User.objects.create_user("sc_p3", "sc3@x.test", "pass1234", phone="+2250799999999", first_name="Awa", last_name="Kone", city="Abidjan")
    User.objects.create_user("sc_p4", "sc4@x.test", "pass1234", phone="+2250788888888", first_name="Awa", last_name="Kone", city="Abidjan")        # même nom et ville
    first = risk.scan()
    assert first["created"] >= 2
    dup = RiskCase.objects.filter(kind="duplicate_account")
    assert set(dup.values_list("subject_id", flat=True)) == {p1.pk, p2.pk} and "preuve" in dup.first().explanation
    again = risk.scan()
    assert again.get("created", 0) == 0 and RiskCase.objects.filter(kind="duplicate_account").count() == 2


def test_scan_flags_expired_kyc_missing_identity_bursts_and_artificial_pairs():
    ok, expired, noid = _pro("sc_ok"), _pro("sc_exp"), _pro("sc_noid")
    HandymanDocument.objects.filter(handyman__user__in=[ok, expired, noid]).delete()                         # on part de dossiers vides (l'aide de test en crée)
    _doc(ok, b"a", status="approved", expires_on=date.today() + timedelta(days=400))
    _doc(expired, b"b", status="approved", expires_on=date.today() - timedelta(days=3))
    client = User.objects.create_user("sc_cli", "scc@x.test", "pass1234")
    for _ in range(10):
        Booking.objects.create(client=client, handyman=ok, address="x", city="x", booking_date=timezone.now(), status="pending")
    for _ in range(5):
        Booking.objects.create(client=client, handyman=expired, address="x", city="x", booking_date=timezone.now(), status="completed")
    risk.scan()
    kinds = lambda u: set(RiskCase.objects.filter(subject=u).values_list("kind", flat=True))
    assert "kyc_expired" in kinds(expired) and "identity_incomplete" in kinds(noid) and "identity_incomplete" not in kinds(ok) and "kyc_expired" not in kinds(ok)
    assert "abnormal_activity" in kinds(client) and "artificial_bookings" in kinds(client) and "artificial_bookings" in kinds(expired)


def test_decisions_are_human_reasoned_audited_and_have_no_automatic_effect():
    u = _pro("dc_u")
    risk.propose(u.pk, "duplicate_account", 3, "Signal fort à vérifier.", {"signal": "file_sha256"}, dedupe_key="x")
    case = RiskCase.objects.get()
    admin, analyst = bo_api(staff("dc_adm", "super_admin")), bo_api(staff("dc_an", "analyst"))
    assert analyst.get(f"{BO}/risk/cases/").status_code == 403
    url = f"{BO}/risk/cases/{case.pk}/decision/"
    assert admin.post(url, {"decision": "confirm", "reason": "court"}, format="json").status_code == 400
    assert admin.post(url, {"decision": "reopen", "reason": "Rouvrir sans raison valable"}, format="json").status_code == 400      # transition impossible
    assert admin.post(url, {"decision": "investigate", "reason": "Comparaison des pièces en cours"}, format="json").json()["status"] == "investigating"
    done = admin.post(url, {"decision": "confirm", "reason": "Même fichier déposé par deux comptes, vérifié visuellement"}, format="json")
    assert done.json()["status"] == "confirmed" and [h["decision"] for h in done.json()["history"]] == ["investigate", "confirm"]
    u.refresh_from_db()
    assert u.is_active and not HandymanDocument.objects.filter(status="rejected").exists()                  # confirmer n'active aucune sanction
    assert AuditEvent.objects.filter(action__startswith="backoffice.risk.case_").count() == 2
    risk.propose(u.pk, "duplicate_account", 3, "Signal fort à vérifier.", {"signal": "file_sha256"}, dedupe_key="x")
    assert RiskCase.objects.filter(status="open").count() == 0                                              # tranché : pas rouvert sans nouvel élément


def test_backoffice_analysis_endpoints_need_the_kyc_right_and_are_audited():
    u = _pro("bo_u")
    doc = _doc(u)
    adm, support, analyst = bo_api(staff("bo_adm", "super_admin")), bo_api(staff("bo_sup", "support")), bo_api(staff("bo_an", "analyst"))
    assert support.post(f"{BO}/kyc/documents/{doc.pk}/analyze/").status_code == 403 and analyst.get(f"{BO}/ai/status/").status_code == 403
    with mock.patch("intelligence.documents.local_ocr", return_value=_text()):
        r = adm.post(f"{BO}/kyc/documents/{doc.pk}/analyze/")
    assert r.status_code == 201 and r.json()["needs_human"] is True and "preuve d'authenticité" in r.json()["disclaimer"]
    assert "CI0123456" not in r.content.decode()
    assert AuditEvent.objects.filter(action="backoffice.kyc.document_analyzed").exists()
    last = adm.get(f"{BO}/kyc/documents/{doc.pk}/analysis/").json()
    assert last["analysis"]["id"] == r.json()["id"] and "keys" not in str(last["ai"]) and last["ai"]["kyc_external_allowed"] is False
    assert adm.get(f"{BO}/risk/summary/").status_code == 200 and adm.get(f"{BO}/ai/status/").status_code == 200
    alerts = adm.get(f"{BO}/dashboard/").json()["alerts"]
    assert isinstance(alerts, list)


# ═══ Recommandations ════════════════════════════════════════════════════════════════════════════════════════════════

def _svc(user, title="Dépannage plomberie", price=5000, **kw):
    from handy.test_eligibility import service

    s = service(user, title=title)
    s.price = price
    for k, v in kw.items():
        setattr(s, k, v)
    s.save()
    return s


def _located(user, lat, lng):
    from django.contrib.gis.geos import Point

    p = user.handyman_profile
    p.location = Point(lng, lat, srid=4326)
    p.save()


def test_recommendations_only_eligible_providers_ranked_and_explained():
    from rest_framework.test import APIClient

    me = User.objects.create_user("rc_me", "rcme@x.test", "pass1234", is_verified=True)
    near, far, ineligible = artisan("rc_near"), artisan("rc_far"), artisan("rc_bad", eligible=False)
    _located(near, 5.36, -4.0083)
    _located(far, 5.9, -4.5)
    _located(ineligible, 5.36, -4.0083)
    for u in (near, far, ineligible):
        _svc(u)
    api = APIClient()
    api.force_authenticate(me)
    r = api.post("/handy/recommendations/", {"q": "plomberie", "lat": 5.37, "lng": -4.0}, format="json").json()
    ids = [x["handyman_id"] for x in r["results"]]
    assert near.pk in ids and far.pk in ids and ineligible.pk not in ids                       # jamais un prestataire non éligible
    assert ids[0] == near.pk and r["results"][0]["score"] > r["results"][1]["score"]
    top = r["results"][0]
    assert top["distance_km"] is not None and top["distance_km"] < 3 and any("km" in x for x in top["reasons"]) and any("Peu d'avis" in x for x in top["reasons"])
    assert r["located"] is True and r["nearby"][0]["service_id"] == top["service_id"] and set(r["criteria"]) == {"relevance", "distance", "reputation", "availability", "history", "price"}
    assert "5.36" not in str(r) and "-4.0083" not in str(r)                                    # aucune coordonnée de prestataire exposée


def test_recommendations_use_real_signals_and_never_invent_missing_ones():
    from rest_framework.test import APIClient

    me = User.objects.create_user("rc_me2", "rcme2@x.test", "pass1234", is_verified=True)
    a, b = artisan("rc_a"), artisan("rc_b")
    _svc(a, price=4000)
    _svc(b, price=9000)
    Booking.objects.create(client=me, handyman=a, address="x", city="x", booking_date=timezone.now(), status="completed")
    api = APIClient()
    api.force_authenticate(me)
    r = api.post("/handy/recommendations/", {"category": "plomberie"}, format="json").json()
    first = r["results"][0]
    assert first["handyman_id"] == a.pk and "Déjà réservé avec succès" in first["reasons"]      # historique réel + prix plus bas
    assert all(x["distance_km"] is None for x in r["results"]) and r["located"] is False       # pas de lieu : distance inconnue, pas inventée
    assert all(x["transport"] is None for x in r["results"])
    assert api.post("/handy/recommendations/", {"category": "inconnue-xyz"}, format="json").status_code == 400
    from rest_framework.test import APIClient as Anon

    assert Anon().post("/handy/recommendations/", {}, format="json").status_code in (401, 403)


def test_recommendation_transport_estimate_is_real_and_availability_respects_time_off(settings):
    from rest_framework.test import APIClient

    from handy.models import TimeOff
    from transport.models import TransportBand, TransportConfig

    cfg = TransportConfig.current()
    cfg.enabled = True
    cfg.save()
    TransportBand.objects.create(name="Jour", start_time=timezone.datetime(2026, 1, 1, 0, 0).time(), end_time=timezone.datetime(2026, 1, 1, 23, 59).time(), rate_per_km=100)
    me = User.objects.create_user("rc_me3", "rcme3@x.test", "pass1234", is_verified=True)
    pro = artisan("rc_t")
    _located(pro, 5.36, -4.0083)
    _svc(pro)
    when = timezone.now() + timedelta(days=1)
    TimeOff.objects.create(handyman=pro.handyman_profile, start=when - timedelta(hours=1), end=when + timedelta(hours=1))
    api = APIClient()
    api.force_authenticate(me)
    with mock.patch("transport.pricing.road_distance_km", return_value=5.0):
        r = api.post("/handy/recommendations/", {"lat": 5.4, "lng": -4.0, "when": when.isoformat()}, format="json").json()
    item = r["results"][0]
    assert item["transport"]["amount"] == 1000 and item["available"] is False and "Absent à ce moment" in item["reasons"]     # 5 km × 2 × 100 FCFA


def test_primary_address_is_used_by_default_and_only_the_users_own():
    from decimal import Decimal

    from rest_framework.test import APIClient

    from handy.models import UserAddress

    me, other = User.objects.create_user("rc_me4", "rcme4@x.test", "pass1234"), User.objects.create_user("rc_o4", "rco4@x.test", "pass1234")
    UserAddress.objects.create(user=me, city="Abidjan", street="x", latitude=Decimal("5.36"), longitude=Decimal("-4.0083"), is_primary=True)
    theirs = UserAddress.objects.create(user=other, city="Abidjan", street="y", latitude=Decimal("5.30"), longitude=Decimal("-4.0"), is_primary=True)
    pro = artisan("rc_p4")
    _located(pro, 5.37, -4.0)
    _svc(pro)
    api = APIClient()
    api.force_authenticate(me)
    r = api.post("/handy/recommendations/", {}, format="json").json()
    assert r["located"] and r["used_primary_address"] and r["results"][0]["distance_km"] is not None
    assert api.post("/handy/recommendations/", {"address_id": theirs.pk}, format="json").status_code == 400
