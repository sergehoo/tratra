"""Onboarding progressif : PUBLICATION, COMMANDES et badge « VÉRIFIÉ » sont trois niveaux séparés, tenus côté serveur.

Complète handy/test_onboarding.py (parcours et étapes), test_eligibility*.py (règle et copies), test_kyc_flow.py (pièces, refus et
reprise), trust/test_trust.py (badges) et flash/test_flash.py (Tratra Flash) : ici, les garde-fous traversant plusieurs modules."""
from datetime import timedelta
from importlib import import_module

import pytest
from django.apps import apps as django_apps
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backoffice import rbac
from django.contrib.auth.models import Group
from handy import eligibility, messaging
from handy.eligibility import IDENTITE_VERIFIEE, NON_VERIFIE, ORDERS_REFUSED, VERIFIE
from handy.models import Booking, HandymanDocument, Notification, Service, ServiceCategory, User
from handy.testing import make_face_verified
from intelligence.models import RiskCase
from trust.models import AuditEvent

pytestmark = pytest.mark.django_db
BO = "/handy/backoffice"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def api(user=None):
    c = APIClient()
    if user is not None:
        c.force_authenticate(user)
    return c


def staff(name="po_staff", role="ops"):
    rbac.ensure_roles()
    u = User.objects.create_user(name, f"{name}@x.test", "pass1234", is_staff=True, first_name="Equipe", last_name="Tratra")
    u.groups.add(Group.objects.get(name=rbac.role_group_name(role)))
    return u


def trade(slug="plomberie", **kw):
    return ServiceCategory.objects.get_or_create(slug=slug, defaults={"name": slug.title(), **kw})[0]


def publisher(name, category=None):
    """Compte unifié qui vient de PUBLIER : téléphone confirmé, commune, métier et un service — aucune pièce d'identité."""
    user = User.objects.create_user(name, f"{name}@x.test", "pass1234", user_type="handyman", is_verified=True,
                                    first_name="Yao", last_name="Kouame")
    profile = user.handyman_profile
    category = category or trade()
    profile.commune = "Cocody"
    profile.save()
    profile.skills.add(category)
    Service.objects.create(handyman=user, category=category, title=f"Service {name}", description="d", price_type="fixed", price=5000)
    profile.refresh_from_db()
    return user, profile


def id_card(profile, status="pending"):
    return HandymanDocument.objects.create(handyman=profile, document_type="id_card", file="kyc/x.jpg", status=status)


def levels(profile):
    profile.refresh_from_db()
    assert profile.published == eligibility.is_publishable(profile) and profile.orders_enabled == eligibility.is_orderable(profile)
    assert profile.verification == eligibility.verification_level(profile)                 # les copies suivent toujours la règle
    return profile.published, profile.orders_enabled, profile.verification


def book(client, svc):
    return api(client).post("/handy/bookings/", {
        "service": svc.id, "handyman": svc.handyman_id, "booking_date": (timezone.now() + timedelta(days=2)).isoformat(),
        "address": "Rue 12", "city": "Abidjan", "postal_code": "00225", "type": "scheduled"}, format="json")


# ═══ Publication sans KYC, commandes bloquées partout ═════════════════════════════════════════════════════════════════

def test_published_without_kyc_is_public_as_unverified_and_every_order_path_is_refused():
    from engagements.services.common import require_eligible_worker

    user, profile = publisher("po_new")
    client = User.objects.create_user("po_cli", "po_cli@x.test", "pass1234", user_type="client", is_verified=True)
    assert levels(profile) == (True, False, NON_VERIFIE)
    card = api().get("/handy/services/").json()["results"][0]["artisan"]
    assert (card["is_verified"], card["can_order"], card["online"], card["verification"]) == (
        False, False, False, {"level": NON_VERIFIE, "label": "Non vérifié", "badge": False})

    svc = Service.objects.get(handyman=user)
    refused = book(client, svc)                                                             # réservation
    assert refused.status_code == 400 and refused.json()["handyman"] == [ORDERS_REFUSED]
    assert not Booking.objects.exists()
    online = api(user).post(reverse("handymen-presence"), {"online": True}, format="json")         # disponibilité (donc Tratra Flash)
    assert online.status_code == 403 and online.json()["code"] == "orders_not_enabled"
    with pytest.raises(messaging.MessagingError) as e:                                      # prise de contact directe
        messaging.open_direct(client, user.pk)
    assert e.value.code == "not_verified"
    with pytest.raises(Exception) as e:                                                     # contrats longue durée
        require_eligible_worker(user)
    assert getattr(e.value, "code", "") == "worker_not_verified"
    summary = eligibility.eligibility_summary(profile)
    assert summary["publication"]["authorized"] and not summary["orders"]["authorized"]
    assert [b["code"] for b in summary["orders"]["blockers"]] == ["kyc_draft"]
    assert summary["next_action"] == {"code": "verify_identity", "label": "Activer mes commandes"}


# ═══ Approbation de la pièce : activation automatique, journalisée, une seule notification ═════════════════════════

def test_id_approval_activates_orders_once_with_audit_and_never_awards_the_verified_badge(django_capture_on_commit_callbacks):
    user, profile = publisher("po_act")
    client = User.objects.create_user("po_cli2", "po_cli2@x.test", "pass1234", user_type="client", is_verified=True)
    reviewer = staff()
    doc = id_card(profile)
    assert levels(profile) == (True, False, NON_VERIFIE)                                    # en revue : rien n'est encore accordé
    with django_capture_on_commit_callbacks(execute=True):
        doc.approve(by=reviewer)
    assert levels(profile) == (True, True, IDENTITE_VERIFIEE)
    stage = eligibility.eligibility_summary(profile)["stages"][0]                              # le texte suit le niveau réel
    assert stage["key"] == "publication" and "Non vérifié" not in stage["benefit"] and "Identité vérifiée" in stage["benefit"]
    event = AuditEvent.objects.get(action="kyc.orders_activated")
    assert (event.actor_id, event.target_id, event.data["document_id"]) == (reviewer.pk, profile.pk, doc.pk)
    assert Notification.objects.filter(user=user, notification_type="kyc_approved").count() == 1
    with django_capture_on_commit_callbacks(execute=True):
        doc.approve(by=reviewer)                                                            # rejeu : ni seconde activation ni second audit
    assert AuditEvent.objects.filter(action="kyc.orders_activated").count() == 1
    assert book(client, Service.objects.get(handyman=user)).status_code == 201             # la commande passe enfin
    card = api().get("/handy/services/").json()["results"][0]["artisan"]
    assert (card["is_verified"], card["can_order"], card["verification"]["label"]) == (False, True, "Identité vérifiée")
    assert "VERIFIE" not in profile.trust_badges


def test_an_open_high_priority_risk_case_holds_the_activation_for_a_team_decision():
    from backoffice.services import approve_profile

    user, profile = publisher("po_risk")
    reviewer = staff("po_staff_r")
    case = RiskCase.objects.create(subject=user, kind="duplicate_account", priority=3, explanation="Même pièce qu'un autre compte")
    id_card(profile).approve(by=reviewer)
    assert levels(profile) == (True, False, IDENTITE_VERIFIEE)                              # pièce approuvée, commandes retenues
    assert AuditEvent.objects.filter(action="kyc.orders_activation_held", target_id=profile.pk).count() == 1
    assert not AuditEvent.objects.filter(action="kyc.orders_activated").exists()
    assert [b["code"] for b in eligibility.eligibility_summary(profile)["orders"]["blockers"]] == ["approval_pending"]
    case.status = "dismissed"
    case.save()
    approve_profile(profile, by=reviewer)                                                   # recours manuel de l'équipe
    assert levels(profile) == (True, True, IDENTITE_VERIFIEE)


# ═══ Métier sensible : la vérification faciale précède les commandes ═══════════════════════════════════════════════

def test_a_sensitive_trade_needs_the_face_check_before_orders_and_the_policy_is_inherited(settings):
    settings.BIOMETRIC_ENABLED = True
    family = trade("garde-enfants", face_required=True)
    child = ServiceCategory.objects.create(slug="garde-de-nuit-po", name="Garde de nuit", parent=family)
    user, profile = publisher("po_nanny", category=child)                                   # la prestation hérite de la famille
    id_card(profile).approve(by=staff("po_staff_s"))
    assert levels(profile) == (True, False, IDENTITE_VERIFIEE)
    summary = eligibility.eligibility_summary(profile)
    assert summary["orders"]["face_required"] is True
    assert [b["code"] for b in summary["orders"]["blockers"]] == ["face_required"]
    assert summary["next_action"]["step"] == "face"
    make_face_verified(profile)
    assert levels(profile) == (True, True, VERIFIE)
    ver = profile.biometric
    ver.status = "rejected"                                                                 # décision retirée : commandes et badge tombent
    ver.save()
    assert levels(profile) == (True, False, IDENTITE_VERIFIEE)


def test_the_face_check_alone_never_gives_orders_nor_the_badge(settings):
    settings.BIOMETRIC_ENABLED = True
    _, profile = publisher("po_face_first")
    make_face_verified(profile)                                                             # selfie validé AVANT la pièce d'identité
    assert levels(profile) == (True, False, NON_VERIFIE)
    id_card(profile).approve(by=staff("po_staff_f"))
    assert levels(profile) == (True, True, VERIFIE)


# ═══ Rejet et reprise ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_rejection_keeps_the_service_public_then_a_new_document_reactivates_orders():
    user, profile = publisher("po_rej")
    reviewer = staff("po_staff_j")
    first = id_card(profile)
    first.reject(by=reviewer, reason="Photo floue")
    assert levels(profile) == (True, False, NON_VERIFIE)
    summary = eligibility.eligibility_summary(profile)
    assert summary["kyc"]["status"] == "rejected" and summary["kyc"]["reason"] == "Photo floue"
    assert [b["code"] for b in summary["orders"]["blockers"]] == ["kyc_rejected"]
    id_card(profile).approve(by=reviewer)                                                   # nouvelle pièce, approuvée
    assert levels(profile) == (True, True, IDENTITE_VERIFIEE)
    HandymanDocument.objects.filter(handyman=profile, status="approved").first().reject(by=reviewer, reason="Pièce expirée")
    assert levels(profile) == (True, False, NON_VERIFIE)                                    # retrait immédiat, le service reste visible


# ═══ Modération : suspension et levée ═══════════════════════════════════════════════════════════════════════════════

def test_suspension_removes_every_level_and_its_lifting_gives_back_only_what_was_earned():
    _, unverified = publisher("po_susp_new")
    _, verified = publisher("po_susp_ok")
    ops = api(staff("po_ops"))
    id_card(verified).approve(by=User.objects.get(username="po_ops"))
    for p in (unverified, verified):
        assert ops.post(f"{BO}/kyc/{p.pk}/suspend/", {"reason": "Annonce frauduleuse"}, format="json").status_code == 200
        assert levels(p) == (False, False, NON_VERIFIE)
    assert api().get("/handy/services/").json()["results"] == []
    assert ops.post(f"{BO}/kyc/{unverified.pk}/restore/", {}, format="json").status_code == 400      # motif obligatoire
    r = ops.post(f"{BO}/kyc/{unverified.pk}/restore/", {"reason": "Erreur de modération"}, format="json")
    assert r.status_code == 200 and (r.json()["published"], r.json()["orders_enabled"]) == (True, False)
    assert levels(unverified) == (True, False, NON_VERIFIE)                                 # jamais d'activation sans pièce approuvée
    r = ops.post(f"{BO}/kyc/{verified.pk}/restore/", {"reason": "Vérification faite"}, format="json")
    assert (r.json()["published"], r.json()["orders_enabled"]) == (True, True)
    assert levels(verified) == (True, True, IDENTITE_VERIFIEE)
    assert AuditEvent.objects.filter(action="backoffice.kyc.profile_restored").count() == 2
    assert ops.post(f"{BO}/kyc/{verified.pk}/restore/", {"reason": "x"}, format="json").status_code in (400, 409)   # plus suspendu
    assert api(User.objects.create_user("po_sup", "po_sup@x.test", "x", is_staff=True)).post(
        f"{BO}/kyc/{verified.pk}/suspend/", {"reason": "x"}, format="json").status_code == 403    # sans droit : refusé


# ═══ Migration des profils existants ═══════════════════════════════════════════════════════════════════════════════

def test_migration_marks_team_suspensions_and_awards_no_badge_to_existing_profiles():
    from trust.models import audit

    migration = import_module("handy.migrations.0069_progressive_onboarding_levels")
    reviewer = staff("po_staff_m")
    _, suspended = publisher("po_m_susp")                 # dernière décision de l'équipe : suspension
    _, restored = publisher("po_m_back")                  # suspendu puis réapprouvé
    _, approved = publisher("po_m_ok")                    # validé avant la refonte (pièce approuvée)
    _, never = publisher("po_m_new")                      # jamais de KYC
    audit("backoffice.kyc.profile_approved", actor=reviewer, target=suspended)
    audit("backoffice.kyc.profile_suspended", actor=reviewer, target=suspended)
    audit("backoffice.kyc.profile_suspended", actor=reviewer, target=restored)
    audit("backoffice.kyc.profile_approved", actor=reviewer, target=restored)
    id_card(approved, status="approved")
    type(approved).objects.filter(pk__in=[approved.pk, restored.pk]).update(is_approved=True)
    migration.mark_suspended(django_apps, None)
    migration.compute(django_apps, None)
    assert levels(suspended) == (False, False, NON_VERIFIE)
    assert levels(restored)[0] is True and restored.suspended is False
    assert levels(approved) == (True, True, IDENTITE_VERIFIEE)                              # commandes conservées, pas de badge « Vérifié »
    assert levels(never) == (True, False, NON_VERIFIE)                                      # visible « Non vérifié », aucune commande
    assert not type(never).objects.filter(verification=VERIFIE).exists()


# ═══ Anti-spam à la publication ═════════════════════════════════════════════════════════════════════════════════════

def test_publication_controls_limit_duplicates_contact_leaks_and_free_prices(settings):
    settings.UNVERIFIED_MAX_ACTIVE_SERVICES = 2
    user, profile = publisher("po_spam")
    c = api(user)
    cat = trade()

    def post(**data):
        return c.post("/handy/services/", {"category": cat.pk, "title": "Débouchage", "description": "Intervention rapide",
                                              "price_type": "fixed", "price": "8000", **data}, format="json")

    assert post(title="Service po_spam").status_code == 400                                 # doublon de sa propre annonce
    assert post(description="Appelez le 07 08 09 10 11").status_code == 400                # numéro dans le texte
    assert post(description="Voir wa.me/2250708091011").status_code == 400                  # lien
    assert post(price="0").status_code == 400                                               # prix fixe nul
    assert post(price_type="quote", price=None).status_code == 201                          # deuxième annonce : acceptée
    over = post(title="Fuite d'eau")
    assert over.status_code == 400 and "avant la vérification de votre identité" in str(over.json())
    assert Service.objects.filter(handyman=user, is_active=True).count() == 2
    id_card(profile).approve(by=staff("po_staff_a"))                                        # identité vérifiée : plafond levé
    c = api(User.objects.get(pk=user.pk))                                                   # nouvelle requête : compte relu
    assert post(title="Fuite d'eau").status_code == 201
