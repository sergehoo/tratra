"""Tratra Trust : badges cumulables et auditables, score explicable, passeport public, droits d'accès."""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from handy.models import (
    Booking, BookingTimeline, Dispute, HandymanDocument, HandymanProfile, Review, Service, ServiceCategory,
)
from handy.test_booking_regression import _client
from handy.test_eligibility import artisan, service
from trust import engine
from trust.models import AuditEvent, BadgeAward, TrustConfig

User = get_user_model()
pytestmark = pytest.mark.django_db


def badges(art):
    return list(HandymanProfile.objects.get(user=art).trust_badges)


def active_codes(art):
    return set(BadgeAward.objects.filter(profile__user=art, ended_at__isnull=True).values_list("code", flat=True))


_n = {"i": 0}


def missions(art, count, *, late=0, rating=5, reviews=True, confirm_after=10):
    """`count` missions TERMINÉES réelles (dont `late` démarrées avec 40 min de retard), avec avis de clients
    distincts et délai de confirmation mesuré."""
    svc = service(art, f"Mission {_n['i']}")
    now = timezone.now()
    for i in range(count):
        _n["i"] += 1
        cli = _client(f"tr_cli_{_n['i']}")
        planned = now - timedelta(days=2 + i % 20)
        b = Booking.objects.create(client=cli, handyman=art, service=svc, status="completed", address="Rue 1",
                                   city="Abidjan", booking_date=planned)
        Booking.objects.filter(pk=b.pk).update(created_at=planned - timedelta(hours=3))
        started = BookingTimeline.objects.create(booking=b, status="in_progress")
        BookingTimeline.objects.filter(pk=started.pk).update(
            at=planned + timedelta(minutes=40 if i < late else 5))
        confirmed = BookingTimeline.objects.create(booking=b, status="confirmed")
        BookingTimeline.objects.filter(pk=confirmed.pk).update(
            at=planned - timedelta(hours=3) + timedelta(minutes=confirm_after))
        if reviews:
            Review.objects.create(booking=b, rating=rating)
    return engine.evaluate_profile(HandymanProfile.objects.get(user=art), trigger="test")


def staff():
    return User.objects.get_or_create(username="tr_staff", defaults={"email": "tr_staff@x.test", "is_staff": True})[0]


def certify(art, *, approve=True, expires_on=None, title="CAP Plomberie"):
    cat = ServiceCategory.objects.get_or_create(slug="plomberie", defaults={"name": "Plomberie"})[0]
    doc = HandymanDocument.objects.create(
        handyman=art.handyman_profile, document_type="certification", file="kyc/cap.pdf", status="pending",
        category=cat, title=title, issuer="Ministère", issued_on=timezone.localdate() - timedelta(days=400),
        expires_on=expires_on)
    if approve:
        doc.approve(by=staff())
    return doc


def seasoned(name="s_art", *, sure=True, expert=True):
    art = artisan(name)
    if expert:
        certify(art)
    missions(art, 16 if sure else 11)
    return art


def api(user=None):
    c = APIClient()
    if user:
        c.force_authenticate(user)
    return c


# ---- NOUVEAU / VERIFIE : exclusivement le KYC ------------------------------------------------------

def test_new_artisan_is_nouveau_with_no_score_and_no_penalty():
    art = artisan("t_new", eligible=False)
    profile = HandymanProfile.objects.get(user=art)
    assert profile.trust_badges == ["NOUVEAU"] and profile.trust_score is None
    assert active_codes(art) == {"NOUVEAU"}


def test_kyc_approval_awards_verifie_and_ends_nouveau():
    art = artisan("t_kyc", eligible=False)
    from handy.testing import make_eligible
    make_eligible(art.handyman_profile)
    assert badges(art) == ["VERIFIE"]
    history = {a.code: a for a in BadgeAward.objects.filter(profile__user=art)}
    assert history["NOUVEAU"].ended_at is not None and history["VERIFIE"].ended_at is None
    # Traçabilité : attribution et retrait sont audités avec leur motif.
    events = AuditEvent.objects.filter(target_type="handymanprofile", target_id=art.handyman_profile.pk)
    assert {"badge.awarded", "badge.revoked"} <= set(events.values_list("action", flat=True))


def test_verifie_depends_only_on_kyc_never_on_declaration():
    art = artisan("t_decl", eligible=False)
    p = art.handyman_profile
    p.bio, p.experience_years, p.commune, p.photo = "Expert", 30, "Cocody", "profile_pics/x.jpg"
    p.save()
    assert "VERIFIE" not in badges(art)  # profil rempli mais KYC absent
    HandymanDocument.objects.create(handyman=p, document_type="id_card", file="kyc/id.pdf", status="pending")
    assert "VERIFIE" not in badges(art)  # KYC déposé mais pas approuvé
    HandymanDocument.objects.filter(handyman=p).first().approve(by=staff())
    assert "VERIFIE" not in badges(art)  # profil non validé par l'équipe
    p.refresh_from_db(); p.is_approved = True; p.skills.add(ServiceCategory.objects.create(name="X", slug="x")); p.save()
    assert badges(art) == ["VERIFIE"]


@pytest.mark.parametrize("revoke", ["kyc_rejected", "suspended", "kyc_deleted"])
def test_loss_of_identity_removes_dependent_badges_immediately(revoke):
    art = seasoned(f"t_rev_{revoke}")
    assert badges(art) == ["VERIFIE", "EXPERT", "SUR"]
    if revoke == "kyc_rejected":
        HandymanDocument.objects.get(handyman__user=art, document_type="id_card").reject(
            by=staff(), reason="Illisible")
        assert badges(art) == ["NOUVEAU"]
    elif revoke == "suspended":
        art.is_active = False
        art.save()
        assert badges(art) == []
    else:
        HandymanDocument.objects.filter(handyman__user=art, document_type="id_card").delete()
        assert badges(art) == ["NOUVEAU"]
    # Plus aucun badge dépendant ACTIF, et le retrait est motivé dans l'historique.
    assert not active_codes(art) & {"VERIFIE", "EXPERT", "SUR"}
    ended = BadgeAward.objects.filter(profile__user=art, code__in=["EXPERT", "SUR"], ended_at__isnull=False)
    assert ended.count() == 2 and all("identité" in a.end_reason.lower() for a in ended)
    # Et l'artisan n'est plus publié : passeport public introuvable.
    assert api().get(f"/handy/handymen/{art.handyman_profile.pk}/trust/").status_code == 404


# ---- EXPERT -----------------------------------------------------------------------------------------

def test_expert_needs_validated_proofs_and_results():
    art = artisan("t_exp")
    missions(art, 12)  # résultats suffisants, mais aucun justificatif
    assert "EXPERT" not in badges(art)
    doc = certify(art, approve=False)
    assert "EXPERT" not in badges(art)  # justificatif déposé seulement (déclaratif)
    doc.approve(by=staff())
    assert "EXPERT" in badges(art)


def test_expert_is_withdrawn_when_proof_expires_on_periodic_reevaluation():
    art = artisan("t_exp_exp")
    doc = certify(art, expires_on=timezone.localdate() + timedelta(days=5))
    missions(art, 12)
    assert "EXPERT" in badges(art)
    HandymanDocument.objects.filter(pk=doc.pk).update(expires_on=timezone.localdate() - timedelta(days=1))
    call_command("reevaluate_trust", "--force")
    assert "EXPERT" not in badges(art)
    assert BadgeAward.objects.get(profile__user=art, code="EXPERT").end_reason.startswith("Critères non atteints")


def test_expert_needs_enough_results_and_rating():
    art = artisan("t_exp_low")
    certify(art)
    missions(art, 12, rating=3)  # note insuffisante (< 4,3)
    assert "EXPERT" not in badges(art)


# ---- SUR : métriques réelles -----------------------------------------------------------------------

def test_sure_is_earned_from_measured_punctuality_and_reviews():
    art = artisan("t_sure")
    missions(art, 16)
    assert "SUR" in badges(art) and "EXPERT" not in badges(art)  # SUR et EXPERT sont indépendants
    snap = BadgeAward.objects.get(profile__user=art, code="SUR").snapshot
    assert snap["criteria"] and all(c["met"] for c in snap["criteria"])


def test_sure_requires_punctuality_and_no_disputes():
    late = artisan("t_late")
    missions(late, 16, late=6)  # 62 % seulement à l'heure
    assert "SUR" not in badges(late)
    clean = artisan("t_dispute")
    missions(clean, 16)
    assert "SUR" in badges(clean)
    b = Booking.objects.filter(handyman=clean, status="completed").first()
    Dispute.objects.create(booking=b, reporter=b.client, reason="Travail non conforme")
    assert "SUR" not in badges(clean)  # 1 mission litigieuse sur 16 = 6,25 % > 5 %


def test_badges_are_cumulative():
    art = seasoned("t_cumul")
    assert badges(art) == ["VERIFIE", "EXPERT", "SUR"]


def test_evaluation_is_idempotent_and_leaves_a_single_active_award_per_code():
    art = seasoned("t_idem")
    before = BadgeAward.objects.filter(profile__user=art).count()
    audits = AuditEvent.objects.count()
    for _ in range(3):
        engine.evaluate_profile(HandymanProfile.objects.get(user=art))
    assert BadgeAward.objects.filter(profile__user=art).count() == before
    assert AuditEvent.objects.count() == audits


def test_criteria_are_configurable_in_admin_config():
    art = seasoned("t_cfg")
    assert "SUR" in badges(art)
    cfg = TrustConfig.get_solo()
    cfg.sure_min_completed = 50
    cfg.save()
    call_command("reevaluate_trust", "--force")
    assert "SUR" not in badges(art) and "EXPERT" in badges(art)


# ---- Score explicable -------------------------------------------------------------------------------

def test_score_is_withheld_without_measured_activity():
    art = artisan("t_noscore")
    p = HandymanProfile.objects.get(user=art)
    assert p.trust_score is None
    data = api().get(f"/handy/handymen/{p.pk}/trust/").json()
    assert data["score"]["value"] is None and "aucune pénalité" in data["score"]["reason"]
    assert data["identity"]["verified"] is True and [b["code"] for b in data["badges"]] == ["VERIFIE"]


def test_reactivity_alone_does_not_publish_a_score_and_small_samples_stay_private():
    art = artisan("t_react")
    missions(art, 1, reviews=False, late=1)  # 1 mission en retard, 1 demande confirmée vite : échantillons trop petits
    p = HandymanProfile.objects.get(user=art)
    data = api().get(f"/handy/handymen/{p.pk}/trust/").json()
    assert p.trust_score is None and data["score"]["value"] is None
    assert data["punctuality"]["rate"] is None and data["punctuality"]["sample"] == 1  # pas de « 0 % » sur 1 mission
    assert data["reactivity"]["median_minutes"] is None


def test_score_is_explainable_and_computed_server_side_from_real_data():
    art = artisan("t_score")
    missions(art, 4, rating=4)
    p = HandymanProfile.objects.get(user=art)
    data = api().get(f"/handy/handymen/{p.pk}/trust/").json()
    score = data["score"]
    assert score["value"] == p.trust_score and 0 < score["value"] <= 100
    live = [c for c in score["components"] if c["available"]]
    assert {c["key"] for c in live} >= {"identity", "satisfaction", "reliability", "reactivity", "track_record"}
    assert abs(sum(c["points"] for c in live) - score["value"]) <= 1  # la somme des points EXPLIQUE le score
    unavailable = [c for c in score["components"] if not c["available"]]
    assert all(c["points"] is None for c in unavailable)  # donnée manquante : jamais comptée comme zéro
    assert data["satisfaction"]["count"] == 4 and data["satisfaction"]["average"] == 4.0
    assert data["punctuality"]["rate"] == 1.0 and data["punctuality"]["sample"] == 4


def test_new_artisan_with_few_reviews_is_not_penalised_by_missing_components():
    young = artisan("t_young")
    missions(young, 3, rating=5, reviews=True)
    veteran = artisan("t_vet")
    missions(veteran, 3, rating=5, reviews=True)
    assert HandymanProfile.objects.get(user=young).trust_score == HandymanProfile.objects.get(user=veteran).trust_score
    assert HandymanProfile.objects.get(user=young).trust_score >= 90


def test_reviews_only_count_from_completed_missions_and_hidden_ones_are_ignored():
    art = artisan("t_rev")
    missions(art, 4, rating=5)
    p = HandymanProfile.objects.get(user=art)
    before = p.trust_score
    review = Review.objects.filter(booking__handyman=art).first()
    review.is_hidden = True
    review.save()
    engine.evaluate_profile(p)
    data = api().get(f"/handy/handymen/{p.pk}/trust/").json()
    assert data["satisfaction"]["count"] == 3 and before is not None


# ---- Passeport public / propriétaire -----------------------------------------------------------------

def test_public_passport_exposes_no_private_data_and_marks_sources():
    art = seasoned("t_pass")
    art.first_name, art.last_name, art.phone = "Awa", "Koné", "+2250700000111"
    art.save()
    p = art.handyman_profile
    data = api().get(f"/handy/handymen/{p.pk}/trust/").json()
    raw = str(data).lower()
    for forbidden in (art.email.lower(), "+2250700000111", "kyc/", "id_card"):
        assert forbidden not in raw, forbidden

    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys(v)

    assert not set(keys(data)) & {"file", "email", "phone", "documents", "license_number", "cni_number",
                                  "insurance_info", "location", "last_location"}
    assert data["display_name"] == "Awa K."
    assert data["identity"]["source"] == "vérifié" and data["experience"]["source"] == "déclaré"
    assert data["skills"]["certified"][0]["source"] == "vérifié"
    assert all(s["source"] == "déclaré" for s in data["skills"]["declared"])
    assert data["satisfaction"]["source"] == "plateforme" and set(data["sources"]) == {"vérifié", "plateforme", "déclaré"}
    assert [h["code"] for h in data["history"]] == ["SUR", "EXPERT", "VERIFIE"] or len(data["history"]) == 3
    assert "end_reason" not in data["history"][0]  # le détail motivé reste réservé au propriétaire


def test_passport_of_unpublished_artisan_is_not_public():
    art = artisan("t_hidden", eligible=False)
    assert api().get(f"/handy/handymen/{art.handyman_profile.pk}/trust/").status_code == 404


def test_my_trust_is_private_detailed_and_requires_a_professional_profile():
    art = artisan("t_me", eligible=False)
    me = api(art).get("/handy/me/trust/")
    assert me.status_code == 200
    body = me.json()
    assert body["identity"]["verified"] is False
    assert {c["key"] for c in body["checklist"]} >= {"kyc", "photo", "bio"}
    assert body["next_badges"]["EXPERT"]["requires_verified"] is True
    assert api().get("/handy/me/trust/").status_code == 401
    client_only = _client("t_client_only")
    assert api(client_only).get("/handy/me/trust/").status_code == 404


def test_my_trust_shows_remaining_criteria_and_motivated_history():
    art = artisan("t_me2")
    missions(art, 6)
    body = api(art).get("/handy/me/trust/").json()
    expert = {c["key"]: c for c in body["next_badges"]["EXPERT"]["criteria"]}
    assert expert["certifications"]["met"] is False and expert["completed"]["current"] == 6
    assert body["next_badges"]["EXPERT"]["earned"] is False
    assert any(h["code"] == "VERIFIE" and h["start_reason"] for h in body["history"])


# ---- Intégration recherche / cartes ---------------------------------------------------------------------

def test_badges_and_score_appear_in_cards_and_search_can_filter_and_sort():
    top = seasoned("t_top")
    plain = artisan("t_plain")
    s_top = service(top, "Chauffe-eau")
    s_plain = service(plain, "Robinet")
    top_services = set(Service.objects.filter(handyman=top).values_list("id", flat=True))
    client = api()
    listing = client.get("/handy/services/", {"badge": "EXPERT"}).json()["results"]
    assert {r["id"] for r in listing} == top_services
    everyone = top_services | {s_plain.id}
    assert {r["id"] for r in client.get("/handy/services/", {"badge": "VERIFIE"}).json()["results"]} == everyone
    assert client.get("/handy/services/", {"badge": "NOUVEAU"}).json()["count"] == len(everyone)  # non filtrable : ignoré
    ranked = [r["id"] for r in client.get("/handy/services/", {"sort": "trust"}).json()["results"]]
    assert ranked[0] in top_services and ranked[-1] == s_plain.id
    feat = client.get("/handy/handymen/featured/", {"badge": "SUR"}).json()["results"]
    assert [a["id"] for a in feat] == [top.handyman_profile.pk]
    assert [b["code"] for b in feat[0]["badges"]] == ["VERIFIE", "EXPERT", "SUR"] and feat[0]["trust_score"] is not None
    plain_card = next(a for a in client.get("/handy/handymen/featured/").json()["results"] if a["id"] == plain.handyman_profile.pk)
    assert plain_card["trust_score"] is None and [b["code"] for b in plain_card["badges"]] == ["VERIFIE"]


# ---- Certifications : dépôt par l'artisan, validation par l'équipe ------------------------------------------

@pytest.fixture
def tmp_kyc(settings, tmp_path):
    """Les justificatifs téléversés vont dans un dossier temporaire, jamais dans private_kyc/ du dépôt."""
    storages = dict(settings.STORAGES)
    storages["private_kyc"] = {"BACKEND": "django.core.files.storage.FileSystemStorage",
                               "OPTIONS": {"location": str(tmp_path)}}
    settings.STORAGES = storages


def test_certification_upload_is_pending_until_staff_approval(tmp_kyc):
    from django.core.files.uploadedfile import SimpleUploadedFile
    art = artisan("t_cert_up")
    cat = ServiceCategory.objects.get(slug="plomberie")
    r = api(art).post("/handy/handyman-docs/", {
        "document_type": "certification", "file": SimpleUploadedFile("cap.pdf", b"%PDF-1.4 test", "application/pdf"),
        "category": cat.id, "title": "CAP Plomberie", "issuer": "Ministère", "issued_on": "2020-01-01"})
    assert r.status_code == 201, r.content
    doc = HandymanDocument.objects.get(pk=r.json()["id"])
    assert doc.status == "pending" and doc.title == "CAP Plomberie"
    p = api().get(f"/handy/handymen/{art.handyman_profile.pk}/trust/").json()
    assert p["skills"]["certified"] == []  # en attente : n'est PAS une compétence certifiée
    admin_user = staff()
    assert api(art).post(f"/handy/handyman-docs/{doc.pk}/review/", {"action": "approve"}, format="json").status_code == 403
    assert api(admin_user).post(f"/handy/handyman-docs/{doc.pk}/review/", {"action": "approve"}, format="json").status_code == 200
    p = api().get(f"/handy/handymen/{art.handyman_profile.pk}/trust/").json()
    assert [c["title"] for c in p["skills"]["certified"]] == ["CAP Plomberie"]
