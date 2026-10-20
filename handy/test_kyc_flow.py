"""Parcours guidé « Vérifier mon identité » : progression enregistrée et reprise, contrôles des photos, transmission dans la file KYC existante,
transitions (revue, refus puis nouvelle pièce, validation), vérification faciale seulement si activée, droits, et éligibilité structurée
(profil complet / identité / autorisation de publication / offres) toujours alignée sur `is_publishable`."""
import io
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from backoffice.services import approve_profile
from handy import kyc_flow
from handy.eligibility import eligibility_summary, is_publishable
from handy.models import HandymanDocument, KycDossier, Notification, User
from handy.test_eligibility import BREAKERS, artisan, service

pytestmark = pytest.mark.django_db
URL = "/handy/me/kyc/"


@pytest.fixture(autouse=True)
def _settings(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    settings.KYC_FLOW_OCR = False            # lecture automatique testée à part (Tesseract absent ou présent selon la machine)
    settings.BIOMETRIC_ENABLED = False


def photo(size=(1200, 800), *, blur=0, dark=False, fmt="JPEG") -> bytes:
    """Photo de pièce plausible : contrastée (netteté mesurable), assez claire, assez grande."""
    from PIL import Image, ImageDraw, ImageFilter

    img = Image.new("RGB", size, (20, 20, 20) if dark else (235, 235, 230))
    d = ImageDraw.Draw(img)
    for y in range(40, size[1] - 40, 28):
        for x in range(40, size[0] - 120, 90):
            d.rectangle([x, y, x + 60, y + 10], fill=(30, 30, 30) if not dark else (45, 45, 45))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


def upload(data=None, name="scan.jpg"):
    return SimpleUploadedFile(name, data if data is not None else photo(), content_type="application/octet-stream")


def pro(username="kyc_pro", **kw):
    u = artisan(username, eligible=False, **kw)
    u.first_name, u.last_name = "Awa", "Koné"
    u.save()
    return u


def api(user=None):
    c = APIClient()
    if user is not None:
        c.force_authenticate(user)
    return c


def fill(c, kind="cni"):
    assert c.patch(URL, {"personal": {"first_name": "Awa Marie", "last_name": "Koné", "birth_date": "1990-04-12"}}, format="json").status_code == 200
    assert c.patch(URL, {"document_kind": kind}, format="json").status_code == 200
    for side in kyc_flow.SIDES[kind]:
        r = c.post(URL + "capture/", {"side": side, "file": upload()}, format="multipart")
        assert r.status_code == 200, r.content


def steps(d):
    return {s["key"]: s["state"] for s in d["steps"]}


# ═══ Accès ═══════════════════════════════════════════════════════════════════════════════════════════════════════════

def test_authentication_and_professional_profile_are_required():
    assert api().get(URL).status_code == 401
    client = User.objects.create_user(username="cli", email="cli@x.test", password="pass1234", user_type="client")
    r = api(client).get(URL)
    assert r.status_code == 409 and r.json()["code"] == "no_profile"


# ═══ Parcours complet, progression enregistrée ══════════════════════════════════════════════════════════════════════

def test_initial_state_seven_steps_prefilled_names_face_skipped_without_biometrics():
    d = api(pro()).get(URL).json()
    assert [s["key"] for s in d["steps"]] == ["personal", "document", "capture", "quality", "face", "review", "activation"]
    assert d["status"] == "draft" and d["current_step"] == "personal"
    assert d["personal"]["first_name"] == "Awa" and d["personal"]["last_name"] == "Koné" and d["personal"]["complete"] is False
    assert steps(d)["face"] == "skipped" and d["face"]["enabled"] is False and "équipe" in d["face"]["note"]
    assert {k["value"]: k["sides"] for k in d["document"]["kinds"]} == {"cni": 2, "passport": 1}


def test_personal_information_is_validated_and_saved_for_resuming_later():
    u = pro()
    c = api(u)
    r = c.patch(URL, {"personal": {"first_name": "A", "last_name": "", "birth_date": "2015-01-01"}}, format="json")
    assert r.status_code == 400 and set(r.json()["fields"]) == {"first_name", "last_name", "birth_date"}
    assert "18 ans" in r.json()["fields"]["birth_date"]
    assert c.patch(URL, {"personal": {"first_name": "Awa", "last_name": "Koné", "birth_date": "2999-01-01"}}, format="json").status_code == 400
    c.patch(URL, {"personal": {"first_name": "Awa Marie", "last_name": "Koné", "birth_date": "1990-04-12"}}, format="json")
    # l'application est fermée puis rouverte : nouveau client, même progression
    d = api(u).get(URL).json()
    assert d["personal"] == {"first_name": "Awa Marie", "last_name": "Koné", "birth_date": "1990-04-12", "complete": True}
    assert d["current_step"] == "document"
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Awa", "Koné")        # le nom public du compte n'est pas modifié


def test_cni_needs_front_and_back_then_is_sent_to_the_existing_kyc_queue(django_capture_on_commit_callbacks):
    u = pro()
    c = api(u)
    c.patch(URL, {"personal": {"first_name": "Awa", "last_name": "Koné", "birth_date": "1990-04-12"}}, format="json")
    d = c.patch(URL, {"document_kind": "cni"}, format="json").json()
    assert [x["side"] for x in d["document"]["captures"]] == ["front", "back"] and d["current_step"] == "capture"
    r = c.post(URL + "capture/", {"side": "front", "file": upload()}, format="multipart").json()
    assert r["check"]["quality"] == "ok" and r["check"]["problems"] == []
    assert r["document"]["ready_to_send"] is False
    early = c.post(URL + "send/")
    assert early.status_code == 409 and early.json()["code"] == "capture_missing" and "verso" in early.json()["detail"]
    d = c.post(URL + "capture/", {"side": "back", "file": upload()}, format="multipart").json()
    assert d["document"]["ready_to_send"] is True and d["current_step"] == "quality"
    with mock.patch("intelligence.tasks.analyze_document.delay") as delay, django_capture_on_commit_callbacks(execute=True):
        d = c.post(URL + "send/").json()
    assert d["status"] == "in_review" and d["current_step"] == "review" and steps(d)["review"] == "waiting"
    docs = HandymanDocument.objects.filter(handyman=u.handyman_profile).order_by("id")
    assert [(x.document_type, x.status, x.title) for x in docs] == [
        ("id_card", "pending", "Carte nationale d’identité — recto"), ("id_card", "pending", "Carte nationale d’identité — verso")]
    dossier = KycDossier.objects.get(profile=u.handyman_profile)
    assert docs[0].file.name == dossier.front.name and dossier.attempts == 1        # même fichier privé, aucune copie
    assert sorted(call.args[0] for call in delay.call_args_list) == [x.pk for x in docs]     # analyse assistée pour l'examinateur
    assert "kyc/" not in str(d) and "url" not in str(d["document"]).lower()             # aucun chemin ni lien de fichier exposé
    # en revue : plus rien ne se modifie, aucune pièce en double
    for call in (lambda: c.patch(URL, {"document_kind": "passport"}, format="json"),
                 lambda: c.post(URL + "capture/", {"side": "front", "file": upload()}, format="multipart"), lambda: c.post(URL + "send/")):
        r = call()
        assert r.status_code == 409 and r.json()["code"] == "in_review"
    assert HandymanDocument.objects.filter(handyman=u.handyman_profile).count() == 2


def test_passport_needs_only_the_photo_page_and_changing_the_kind_resets_the_photos():
    u = pro()
    c = api(u)
    fill(c, "cni")
    d = c.patch(URL, {"document_kind": "passport"}, format="json").json()
    assert [(x["side"], x["present"]) for x in d["document"]["captures"]] == [("front", False)]
    assert c.post(URL + "capture/", {"side": "back", "file": upload()}, format="multipart").json()["code"] == "invalid_side"
    c.post(URL + "capture/", {"side": "front", "file": upload()}, format="multipart")
    with mock.patch("intelligence.tasks.analyze_document.delay"):
        c.post(URL + "send/")
    assert list(HandymanDocument.objects.filter(handyman=u.handyman_profile).values_list("title", flat=True)) == ["Passeport — page photo"]


# ═══ Contrôle qualité ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_quality_warnings_are_explained_and_blocking_defects_prevent_sending():
    u = pro()
    c = api(u)
    c.patch(URL, {"personal": {"first_name": "Awa", "last_name": "Koné", "birth_date": "1990-04-12"}}, format="json")
    c.patch(URL, {"document_kind": "passport"}, format="json")
    blurry = c.post(URL + "capture/", {"side": "front", "file": upload(photo(blur=12))}, format="multipart").json()["check"]
    assert blurry["quality"] == "warn" and [p["code"] for p in blurry["problems"]] == ["blurry"] and blurry["problems"][0]["blocking"] is False
    dark = c.post(URL + "capture/", {"side": "front", "file": upload(photo(dark=True))}, format="multipart").json()["check"]
    assert "too_dark" in [p["code"] for p in dark["problems"]]
    small = c.post(URL + "capture/", {"side": "front", "file": upload(photo((500, 320)))}, format="multipart").json()
    assert small["check"]["quality"] == "fail" and small["check"]["problems"][0]["code"] == "low_resolution"
    refused = c.post(URL + "send/")
    assert refused.status_code == 409 and refused.json()["code"] == "quality_failed"
    assert not HandymanDocument.objects.filter(handyman=u.handyman_profile).exists()
    r = c.post(URL + "capture/", {"side": "front", "file": upload(b"%PDF-1.4 pas une photo")}, format="multipart")
    assert r.status_code == 400 and r.json()["code"] == "unsupported_type"
    png = c.post(URL + "capture/", {"side": "front", "file": upload(photo(fmt="PNG"), "scan.png")}, format="multipart").json()
    assert png["check"]["quality"] == "ok"


def test_automatic_reading_gives_hints_only_and_never_keeps_the_text(settings):
    settings.KYC_FLOW_OCR = True
    u = pro()
    c = api(u)
    c.patch(URL, {"personal": {"first_name": "Awa", "last_name": "Koné", "birth_date": "1990-04-12"}}, format="json")
    c.patch(URL, {"document_kind": "cni"}, format="json")
    text = "PASSPORT\nP<CIVKOUASSI<<JEAN<<<<<<<<<<<<<<<<<<<<<<<<<<<<\nAB1234567<CIV8001019M2001019<<<<<<<<<<<<<<04\n"
    with mock.patch("intelligence.documents.local_ocr_available", return_value=True), mock.patch("intelligence.documents.local_ocr", return_value=text):
        check = c.post(URL + "capture/", {"side": "front", "file": upload()}, format="multipart").json()["check"]
    notes = " ".join(check["reading"]["notes"])
    assert check["reading"]["status"] == "read"
    assert "passeport" in notes and "expiration" in notes and "nom lu" in notes
    stored = KycDossier.objects.get(profile=u.handyman_profile).front_check
    assert "AB1234567" not in str(stored) and "KOUASSI" not in str(stored) and stored["quality"] == "ok"   # indicateurs seulement


# ═══ Revue humaine : transitions ════════════════════════════════════════════════════════════════════════════════════

def _send(c):
    with mock.patch("intelligence.tasks.analyze_document.delay"):
        assert c.post(URL + "send/").status_code == 200


def test_rejection_then_new_photos_then_approval_keeps_the_whole_history():
    staff = User.objects.create_user(username="kyc_staff", email="s@x.test", password="pass1234", is_staff=True)
    u = pro()
    c = api(u)
    fill(c)
    _send(c)
    front, back = HandymanDocument.objects.filter(handyman=u.handyman_profile).order_by("id")
    back.reject(by=staff, reason="Verso illisible : reflet sur la date.")
    d = c.get(URL).json()
    assert d["status"] == "changes_requested" and d["review"]["reason"] == "Verso illisible : reflet sur la date."
    assert steps(d)["capture"] == "error" and d["current_step"] == "capture" and d["editable"] is True
    # les photos refusées ne s'affichent plus comme « nettes et lisibles » : les deux faces sont à reprendre
    assert [(x["present"], x["quality"]) for x in d["document"]["captures"]] == [(False, None), (False, None)]
    assert d["document"]["ready_to_send"] is False
    # nouvelle photo : le dossier repart en brouillon, le motif reste affiché, rien n'est supprimé
    d = c.post(URL + "capture/", {"side": "front", "file": upload()}, format="multipart").json()
    assert d["status"] == "draft" and d["review"]["previous_reason"] == "Verso illisible : reflet sur la date."
    assert [x["present"] for x in d["document"]["captures"]] == [True, False]
    c.post(URL + "capture/", {"side": "back", "file": upload()}, format="multipart")
    _send(c)
    assert HandymanDocument.objects.filter(handyman=u.handyman_profile).count() == 4
    assert KycDossier.objects.get(profile=u.handyman_profile).attempts == 2
    assert c.get(URL).json()["status"] == "in_review"
    new_front = HandymanDocument.objects.filter(handyman=u.handyman_profile).order_by("-id")[1]
    new_front.approve(by=staff)
    d = c.get(URL).json()
    assert d["status"] == "verified" and steps(d)["review"] == "done" and d["current_step"] == "activation"
    assert c.post(URL + "restart/").json()["code"] == "not_rejected"
    assert c.patch(URL, {"document_kind": "passport"}, format="json").json()["code"] == "already_verified"
    front.refresh_from_db()
    # l'ancienne face encore « en attente » a quitté la file de l'examinateur (motif explicite), sans être supprimée ni notifiée
    assert front.status == "rejected" and front.rejection_reason == kyc_flow.SUPERSEDED_REASON and front.reviewed_by_id is None
    assert Notification.objects.filter(user=u, notification_type="kyc_rejected").count() == 1      # le seul refus notifié : celui de l'équipe


def test_restart_is_only_possible_after_a_refusal():
    staff = User.objects.create_user(username="kyc_staff2", email="s2@x.test", password="pass1234", is_staff=True)
    u = pro()
    c = api(u)
    assert c.post(URL + "restart/").json()["code"] == "not_rejected"
    fill(c, "passport")
    _send(c)
    HandymanDocument.objects.get(handyman=u.handyman_profile).reject(by=staff, reason="Pièce expirée.")
    d = c.post(URL + "restart/").json()
    assert d["status"] == "draft" and d["document"]["kind"] == "passport" and d["personal"]["complete"] is True
    assert d["document"]["captures"][0]["present"] is False and d["review"]["previous_reason"] == "Pièce expirée."


def test_identity_documents_sent_before_the_guided_flow_are_taken_into_account():
    approved = artisan("legacy_ok")                      # pièce approuvée déposée avec l'ancien écran
    assert api(approved).get(URL).json()["status"] == "verified"
    waiting = pro("legacy_wait")
    HandymanDocument.objects.create(handyman=waiting.handyman_profile, document_type="id_card", file="kyc/x.jpg", status="pending")
    d = api(waiting).get(URL).json()
    assert d["status"] == "in_review" and d["editable"] is False


def test_the_flow_never_approves_anything_by_itself():
    u = pro()
    c = api(u)
    fill(c)
    _send(c)
    profile = u.handyman_profile
    profile.refresh_from_db()
    assert not profile.is_approved and not profile.has_required_kyc()
    assert not HandymanDocument.objects.filter(handyman=profile, status="approved").exists()


# ═══ Vérification faciale (si activée) ══════════════════════════════════════════════════════════════════════════════

def test_face_step_appears_only_when_biometrics_are_enabled_and_human_review_remains_possible(settings):
    from biometrics import services as bio

    settings.BIOMETRIC_ENABLED = True
    u = pro()
    c = api(u)
    fill(c)
    _send(c)
    d = c.get(URL).json()
    assert steps(d)["face"] == "current" and d["current_step"] == "face" and d["face"]["required"] is False
    assert d["face"]["satisfied"] is False                       # aucune validation faciale automatique
    bio.request_human_review(u, "other")                          # alternative humaine (module biométrique existant)
    c.patch(URL, {"face_choice": "human"}, format="json")
    d = c.get(URL).json()
    assert steps(d)["face"] == "done" and d["face"]["human_review_requested"] is True and d["face"]["choice"] == "human"
    assert d["current_step"] == "review"
    assert c.patch(URL, {"face_choice": "robot"}, format="json").status_code == 400


# ═══ Éligibilité structurée (source unique) ═════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("breaker", sorted(BREAKERS))
def test_publication_authorization_always_equals_is_publishable(breaker):
    u = artisan(f"elig_{breaker}")
    profile = u.handyman_profile
    BREAKERS[breaker](profile)
    profile.save()
    profile.refresh_from_db()
    s = eligibility_summary(profile)
    assert s["publication"]["authorized"] is is_publishable(profile)
    assert (s["publication"]["blockers"] == []) is s["publication"]["authorized"]


def test_four_distinct_notions_with_real_blockers_and_corrective_actions():
    u = pro("elig_new")
    s = eligibility_summary(u.handyman_profile)
    assert s["profile"]["total"] == 5 and s["profile"]["complete"] is False
    assert s["kyc"]["status"] == "draft" and s["approval"]["approved"] is False
    codes = {b["code"]: b["action"] and b["action"]["code"] for b in s["publication"]["blockers"]}
    assert codes == {"profile_incomplete": "edit_profile", "kyc_draft": "verify_identity"}
    assert s["offers"] == {"total": 0, "active": 0, "published": 0, "inactive": 0, "label": "Aucune offre créée",
                           "action": {"code": "add_service", "label": "Ajouter une offre"}}
    assert s["next_action"]["code"] == "edit_profile"
    # identité vérifiée, profil complet, mais validation finale pas encore donnée : un seul blocage, sans action à faire
    ok = artisan("elig_wait")
    profile = ok.handyman_profile
    profile.is_approved = False
    profile.save()
    service(ok)
    s = eligibility_summary(profile)
    assert [b["code"] for b in s["publication"]["blockers"]] == ["approval_pending"] and s["publication"]["blockers"][0]["action"] is None
    assert s["offers"]["published"] == 0 and s["offers"]["active"] == 1 and "en attente" in s["offers"]["label"]
    approve_profile(profile, by=None)
    s = eligibility_summary(profile)
    assert s["publication"]["authorized"] is True and s["offers"]["published"] == 1 and s["offers"]["label"] == "1 offre publiée"


def test_dashboard_identity_state_ignores_pending_professional_documents():
    """Cause du « 7/7 » contradictoire : un justificatif professionnel en attente faisait afficher « vérification en cours »."""
    u = artisan("elig_cert")
    HandymanDocument.objects.create(handyman=u.handyman_profile, document_type="certification", file="kyc/c.pdf", status="pending", title="CAP")
    p = api(u).get("/handy/me/dashboard/").json()["provider"]
    assert p["completion"]["done"] == p["completion"]["total"] == 7
    assert p["kyc"]["status"] == "approved" and p["eligibility"]["kyc"]["approved"] is True and p["publishable"] is True
    assert p["eligibility"]["publication"]["authorized"] is True


def test_my_services_show_a_clear_publication_state_per_offer():
    u = pro("svc_state")
    service(u, "Fuite d'eau")
    service(u, "Ancienne offre", active=False)
    d = api(u).get("/handy/me/services/").json()
    states = {s["title"]: s["publication"]["state"] for s in d["results"]}
    assert states == {"Fuite d'eau": "waiting", "Ancienne offre": "inactive"}
    assert d["eligibility"]["publication"]["authorized"] is False and d["publishable"] is False
    ok = artisan("svc_ok")
    service(ok)
    assert api(ok).get("/handy/me/services/").json()["results"][0]["publication"] == {
        "state": "published", "label": "Publiée", "hint": "Visible des clients dans le catalogue et la recherche."}


def test_a_dossier_belongs_to_its_owner_only():
    a, b = pro("own_a"), pro("own_b")
    fill(api(a))
    _send(api(a))
    d = api(b).get(URL).json()
    assert d["status"] == "draft" and d["document"]["kind"] is None
    assert not HandymanDocument.objects.filter(handyman=b.handyman_profile).exists()


def test_the_reviewer_sees_the_declared_identity_next_to_the_documents():
    from backoffice.api_people import _identity

    u = pro("bo_ident")
    assert _identity(u.handyman_profile) is None                 # parcours jamais ouvert : rien de déclaré
    fill(api(u))
    _send(api(u))
    ident = _identity(u.handyman_profile)
    assert ident["first_name"] == "Awa Marie" and str(ident["birth_date"]) == "1990-04-12"
    assert ident["document_label"] == "Carte nationale d’identité" and ident["attempts"] == 1 and ident["sent_at"]
