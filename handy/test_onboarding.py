"""« Inscription accompagnée » : questions par métier (configurables), sauvegarde et reprise, annonce rédigée à partir des réponses,
application aux modèles EXISTANTS sans rien écraser, aucune publication avant éligibilité, droits, préremplissage KYC par la lecture."""
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from backoffice.services import approve_profile
from handy import onboarding
from handy.eligibility import is_publishable
from handy.models import HandymanDocument, HandymanProfile, OnboardingQuestion, ProOnboarding, Service, ServiceCategory, User
from handy.test_kyc_flow import photo

pytestmark = pytest.mark.django_db


def trade(name, slug, **kw):
    return ServiceCategory.objects.create(name=name, slug=slug, is_active=True, **kw)


@pytest.fixture
def nanny():
    t = trade("Nousnou", "nousnou")                       # nom réel (faute de frappe) de la production : retrouvé par mots-clés
    trade("Garde de nuit", "garde-de-nuit", parent=t)
    trade("Sortie d'école", "sortie-ecole", parent=t)
    return t


def member(username="awa", **kw):
    return User.objects.create_user(username=username, email=f"{username}@x.test", password="pass1234", first_name="Awa", last_name="Koné",
                                    phone="+2250700000777" if username == "awa" else None, **kw)


def api(user=None):
    c = APIClient()
    if user is not None:
        c.force_authenticate(user)
    return c


ANSWERS = {"experience": "4", "nanny_skills": ["babies", "school"], "nanny_live_in": "no", "nanny_price": "m60000",
           "days": ["monday", "tuesday", "wednesday", "thursday", "friday"], "slots": ["morning", "afternoon"]}


def fill(c, t, **extra):
    prestations = list(ServiceCategory.objects.filter(parent=t).values_list("pk", flat=True))[:1]
    r = c.put("/handy/me/onboarding/", {"trade": t.pk, "prestations": prestations, "commune": "Cocody", "quartier": "Riviera 2",
                                        "answers": ANSWERS, "step": "preview", **extra}, format="json")
    assert r.status_code == 200, r.content
    return r.json()


# ═══ Configuration (publique) ═════════════════════════════════════════════════════════════════════════════════════════

def test_public_config_adapts_questions_to_the_trade_and_hides_internal_fields(nanny):
    d = api().get(f"/handy/onboarding/config/?trade={nanny.pk}").json()
    keys = [q["key"] for q in d["questions"]]
    assert keys == ["experience", "nanny_skills", "nanny_live_in", "nanny_price", "days", "slots"]
    assert "price_general" not in keys                              # la question de métier remplace la question commune
    assert [p["name"] for p in d["prestations"]] == ["Garde de nuit", "Sortie d'école"]
    assert "Cocody" in d["communes"]
    price = next(q for q in d["questions"] if q["key"] == "nanny_price")
    assert set(price["options"][0]) == {"value", "label", "emoji", "amount", "unit"}   # de quoi rédiger l'aperçu hors ligne, rien d'autre
    OnboardingQuestion.objects.filter(key="nanny_price").update(
        options=[{"value": "m1", "label": "1 FCFA", "amount": 1, "unit": "month", "note_interne": "à ne pas publier"}])
    price = next(q for q in api().get(f"/handy/onboarding/config/?trade={nanny.pk}").json()["questions"] if q["key"] == "nanny_price")
    assert "note_interne" not in price["options"][0]                  # liste blanche : un champ ajouté dans l'admin ne fuit pas
    gardener = trade("Jardinage", "jardinage")
    assert "garden_skills" in [q["key"] for q in api().get(f"/handy/onboarding/config/?trade={gardener.pk}").json()["questions"]]
    plumber = trade("Plomberie", "plomberie-x")
    keys = [q["key"] for q in api().get(f"/handy/onboarding/config/?trade={plumber.pk}").json()["questions"]]
    assert keys == ["experience", "price_general", "days", "slots"]   # métier sans questions dédiées : questions communes
    assert api().get("/handy/onboarding/config/?trade=999999").status_code == 404


def test_questions_are_configurable_in_django(nanny):
    q = OnboardingQuestion.objects.create(key="nanny_languages", text="Quelles langues parlez-vous ?", target="info", kind="multi",
                                          position=50, options=[{"value": "fr", "label": "Français", "phrase": "parle français"}])
    q.trades.add(nanny)
    keys = [x["key"] for x in api().get(f"/handy/onboarding/config/?trade={nanny.pk}").json()["questions"]]
    assert keys.index("nanny_languages") == keys.index("nanny_live_in") + 1
    OnboardingQuestion.objects.filter(key="nanny_live_in").update(is_active=False)
    assert "nanny_live_in" not in [x["key"] for x in api().get(f"/handy/onboarding/config/?trade={nanny.pk}").json()["questions"]]


# ═══ Sauvegarde, reprise, annonce proposée ════════════════════════════════════════════════════════════════════════════

def test_answers_are_saved_cleaned_and_resumed(nanny):
    u = member()
    c = api(u)
    d = fill(c, nanny, answers={**ANSWERS, "experience": "999", "hack": "x", "nanny_skills": ["babies", "rm -rf"]})
    assert "experience" not in d["answers"] and "hack" not in d["answers"]          # seules les valeurs proposées sont gardées
    assert d["answers"]["nanny_skills"] == ["babies"]
    d = api(u).get("/handy/me/onboarding/").json()                                  # autre appareil : même progression
    assert (d["trade"]["name"], d["commune"], d["quartier"], d["step"]) == ("Nousnou", "Cocody", "Riviera 2", "preview")
    assert d["next_action"]["code"] == "resume" and d["next_action"]["step"] == "questions"


def test_offer_is_written_from_the_answers_without_ai(nanny):
    u = member()
    d = fill(api(u), nanny)
    offer = d["offer"]
    assert offer["title"] == "Garde de nuit à Cocody"
    assert offer["description"] == (
        "Je propose mes services de nousnou à Cocody (Riviera 2). Ce que je fais : soins des bébés et accompagnement à l’école. "
        "Sans hébergement. Disponible du lundi au vendredi le matin et l’après-midi. 4 ans d’expérience environ. "
        "Tarif souhaité : 60 000 FCFA par mois (à discuter).")
    assert offer["price_type"] == "quote" and offer["price"] is None                   # salaire mensuel : à discuter, jamais un faux forfait


def test_changing_trade_resets_trade_specific_answers(nanny):
    u = member()
    c = api(u)
    fill(c, nanny)
    cook = trade("Cuisine", "cuisine")
    d = c.put("/handy/me/onboarding/", {"trade": cook.pk}, format="json").json()
    assert d["answers"] == {} and d["prestations"] == []


# ═══ Application aux modèles existants ════════════════════════════════════════════════════════════════════════════════

def test_apply_fills_the_existing_profile_and_creates_one_offer_idempotently(nanny):
    u = member(is_verified=True)
    c = api(u)
    fill(c, nanny)
    d = c.post("/handy/me/onboarding/apply/").json()
    p = HandymanProfile.objects.get(user=u)
    assert (p.experience_years, p.commune, p.quartier) == (4, "Cocody", "Riviera 2")
    assert p.availability == {d: ["morning", "afternoon"] for d in ["monday", "tuesday", "wednesday", "thursday", "friday"]}
    assert p.monthly_rate == 60000 and p.bio.startswith("Nousnou à Cocody (Riviera 2).")
    assert set(p.skills.values_list("slug", flat=True)) == {"nousnou", "garde-de-nuit"}
    assert Service.objects.filter(handyman=u).count() == 1
    assert d["steps"][5] == {"key": "offer", "label": "Votre annonce", "state": "done"}
    c.post("/handy/me/onboarding/apply/")                                              # rejouée : aucun doublon
    assert Service.objects.filter(handyman=u).count() == 1 and HandymanProfile.objects.filter(user=u).count() == 1


def test_apply_never_overwrites_what_the_user_wrote_elsewhere(nanny):
    u = member()
    profile = HandymanProfile.objects.create(user=u, bio="Ma présentation à moi.", experience_years=7, commune="Yopougon")
    c = api(u)
    fill(c, nanny)
    c.post("/handy/me/onboarding/apply/")
    profile.refresh_from_db()
    assert (profile.bio, profile.experience_years, profile.commune) == ("Ma présentation à moi.", 7, "Yopougon")
    service = Service.objects.get(handyman=u)
    service.description = "Ma description retouchée."
    service.save()
    c.put("/handy/me/onboarding/", {"answers": {**ANSWERS, "experience": "12"}}, format="json")
    c.post("/handy/me/onboarding/apply/")
    service.refresh_from_db()
    assert service.description == "Ma description retouchée."                         # retouchée : jamais remplacée


def test_proposed_texts_are_updated_while_untouched(nanny):
    u = member()
    c = api(u)
    fill(c, nanny)
    c.post("/handy/me/onboarding/apply/")
    c.put("/handy/me/onboarding/", {"answers": {**ANSWERS, "nanny_live_in": "yes"}}, format="json")
    c.post("/handy/me/onboarding/apply/")
    assert "Logement sur place possible." in Service.objects.get(handyman=u).description


def test_no_public_offer_before_identity_and_professional_validation(nanny):
    u = member(is_verified=True)
    c = api(u)
    fill(c, nanny)
    c.post("/handy/me/onboarding/apply/")
    profile = HandymanProfile.objects.get(user=u)
    profile.photo = "profile_pics/x.jpg"
    profile.save()
    assert not is_publishable(profile)
    assert not api().get("/handy/services/").json().get("results")                    # rien dans le catalogue public
    d = c.get("/handy/me/onboarding/").json()
    assert d["next_action"]["code"] == "verify_identity" and d["published"] is False
    staff = User.objects.create_user(username="st", email="st@x.test", password="x", is_staff=True)
    HandymanDocument.objects.create(handyman=profile, document_type="id_card", file="kyc/x.jpg", status="pending")
    assert c.get("/handy/me/onboarding/").json()["next_action"] == {"code": "wait", "label": "Nous vérifions votre dossier", "step": "identity"}
    HandymanDocument.objects.filter(handyman=profile).update(status="approved", reviewed_by=staff)
    assert c.get("/handy/me/onboarding/").json()["next_action"]["step"] == "approval"
    approve_profile(profile, by=staff)
    d = c.get("/handy/me/onboarding/").json()
    assert d["published"] is True and d["next_action"]["code"] == "done" and d["done"] == d["total"]


def test_apply_requires_the_answers_and_authentication(nanny):
    u = member()
    c = api(u)
    assert c.post("/handy/me/onboarding/apply/").json()["code"] == "incomplete"
    assert api().get("/handy/me/onboarding/").status_code == 401
    assert api().put("/handy/me/onboarding/", {"trade": nanny.pk}, format="json").status_code == 401
    admin = member("adm", user_type="admin")
    fill(api(admin), nanny)
    assert api(admin).post("/handy/me/onboarding/apply/").status_code == 403


def test_each_account_sees_only_its_own_onboarding(nanny):
    a, b = member(), member("bob")
    fill(api(a), nanny)
    d = api(b).get("/handy/me/onboarding/").json()
    assert d["trade"] is None and d["answers"] == {}
    assert ProOnboarding.objects.count() == 2


def test_journey_steps_and_next_action_for_a_beginner(nanny):
    u = member()
    d = api(u).get("/handy/me/onboarding/").json()
    assert [s["key"] for s in d["steps"]] == ["trade", "zone", "questions", "account", "phone", "offer", "photo", "identity", "approval"]
    assert d["next_action"] == {"code": "resume", "label": "Choisir mon métier", "step": "trade"}
    fill(api(u), nanny)
    assert api(u).get("/handy/me/onboarding/").json()["next_action"]["code"] == "verify_phone"     # téléphone pas encore confirmé


# ═══ KYC simplifié : préremplissage par la lecture de la pièce ════════════════════════════════════════════════════════

def test_kyc_capture_proposes_identity_details_read_on_the_document_without_storing_them(settings):
    from handy.models import KycDossier

    settings.KYC_FLOW_OCR = True
    settings.BIOMETRIC_ENABLED = False
    u = member()
    HandymanProfile.objects.get_or_create(user=u)
    c = api(u)
    c.patch("/handy/me/kyc/", {"document_kind": "passport"}, format="json")
    text = "PASSPORT\nP<CIVKONE<<AWA<MARIE<<<<<<<<<<<<<<<<<<<<<<<<<<<\nAB1234567<CIV9004128F3001019<<<<<<<<<<<<<<04\n"
    with mock.patch("intelligence.documents.local_ocr_available", return_value=True), mock.patch("intelligence.documents.local_ocr", return_value=text):
        r = c.post("/handy/me/kyc/capture/", {"side": "front", "file": SimpleUploadedFile("p.jpg", photo())}, format="multipart").json()
    assert r["suggestions"] == {"first_name": "Awa Marie", "last_name": "KONE", "birth_date": "1990-04-12"}
    stored = KycDossier.objects.get(profile__user=u)
    assert "KONE" not in str(stored.front_check) and "1990" not in str(stored.front_check)   # proposé, jamais conservé
    assert stored.birth_date is None                                                      # l'utilisateur confirme lui-même
    assert onboarding  # module importé (lint)


@pytest.mark.django_db
def test_seeded_questions_use_typographic_apostrophes():
    from handy.models import OnboardingQuestion
    texts = []
    for q in OnboardingQuestion.objects.all():
        texts += [q.text, q.help_text] + [str(o.get(k, "")) for o in q.options for k in ("label", "phrase")]
    assert texts and not [t for t in texts if "'" in t]
    assert any("Moins d’un an" == str(o.get("label")) for q in OnboardingQuestion.objects.filter(key="experience") for o in q.options)
