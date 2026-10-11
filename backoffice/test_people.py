"""Back-Office « personnes » : utilisateurs, KYC, Tratra Trust, Tratra ID. Droits serveur, effets métier réels,
aucune donnée sensible exposée (pièces, jetons d'appareil), journal d'audit, workflows jamais contournés."""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from backoffice import rbac
from handy import eligibility
from handy.models import Booking, Device, HandymanDocument, MarketingConsent, Notification
from handy.test_eligibility import artisan, service
from trust import identity
from trust.models import AuditEvent, BadgeAward, BookingPass, ProfessionalId

User = get_user_model()
pytestmark = pytest.mark.django_db
BO = "/handy/backoffice"


def person(name, **kw):
    return User.objects.create_user(name, f"{name}@x.test", "pass1234", user_type="client", is_verified=True, phone=kw.pop("phone", None), **kw)


def staff(name, role=None, superuser=False):
    rbac.ensure_roles()
    u = User.objects.create_user(name, f"{name}@x.test", "pass1234", is_staff=True, is_superuser=superuser, first_name=name.title(), last_name="Admin")
    if role:
        u.groups.add(Group.objects.get(name=rbac.role_group_name(role)))
    return u


def api(u=None):
    c = APIClient()
    if u:
        c.force_authenticate(u)
    return c


def audited(action, **target):
    return AuditEvent.objects.filter(action=f"backoffice.{action}", **target)


# ═══ Utilisateurs ═══════════════════════════════════════════════════════════════════════════════════════════════════

def test_users_list_masks_contact_details_excludes_staff_and_filters():
    c = person("u_cli", first_name="Awa", last_name="Kone", phone="+2250701234567", city="Abidjan")
    a = artisan("u_art")
    Booking.objects.create(client=c, handyman=a, address="x", city="x", booking_date=timezone.now())
    staff("u_staff", "ops")
    support = api(staff("u_support", "support"))
    r = support.get(f"{BO}/users/").json()
    names = {row["name"] for row in r["results"]}
    assert "Awa K." in names and not any("u_staff" in str(row) for row in r["results"])          # le personnel n'est pas listé ici
    row = next(x for x in r["results"] if x["name"] == "Awa K.")
    assert row["phone"] == "+22507••••4567" and row["email"] == "u•••@x.test" and row["bookings"] == 1
    assert "0701234567" not in str(r)                                                              # jamais le numéro complet en liste
    assert [x["id"] for x in support.get(f"{BO}/users/?type=artisan").json()["results"]] == [a.id]
    assert support.get(f"{BO}/users/?q=0701234").json()["count"] == 1                              # recherche par fragment de numéro
    assert support.get(f"{BO}/users/?active=false").json()["count"] == 0
    assert support.get(f"{BO}/users/?ordering=hack").status_code == 200                           # tri hors liste blanche : ignoré
    assert api(staff("u_ana", "analyst")).get(f"{BO}/users/").status_code == 403                  # pas de droit users.view
    assert api(person("u_plain")).get(f"{BO}/users/").status_code == 403


def test_users_list_is_one_list_with_offer_missions_kyc_and_badges_filters():
    """Compte unique : pas de classe client/artisan, mais des faits (services proposés, missions, KYC, badges) et un filtre « propose des services »."""
    req = person("u_req")
    pro = artisan("u_pro")
    service(pro)
    Booking.objects.create(client=req, handyman=pro, address="x", city="x", booking_date=timezone.now(), status="completed")
    ended = BadgeAward.objects.create(profile=pro.handyman_profile, code=BadgeAward.EXPERT, ended_at=timezone.now())
    active = sorted(BadgeAward.objects.filter(profile=pro.handyman_profile, ended_at__isnull=True).values_list("code", flat=True))
    ops = api(staff("u_ops_people", "ops"))
    rows = {r["id"]: r for r in ops.get(f"{BO}/users/").json()["results"]}
    assert rows[pro.pk]["offers_services"] is True and rows[pro.pk]["services"] == 1 and rows[pro.pk]["missions_done"] == 1
    assert sorted(rows[pro.pk]["badges"]) == active and ended.code not in rows[pro.pk]["badges"]              # seuls les badges actifs
    assert rows[req.pk]["offers_services"] is False and rows[req.pk]["services"] == 0 and rows[req.pk]["kyc_state"] is None
    assert [r["id"] for r in ops.get(f"{BO}/users/?offers=true").json()["results"]] == [pro.pk]
    assert req.pk in [r["id"] for r in ops.get(f"{BO}/users/?offers=false").json()["results"]]
    approved = [r["id"] for r in ops.get(f"{BO}/users/?kyc=approved").json()["results"]]
    assert approved == ([pro.pk] if pro.handyman_profile.is_approved else [])
    assert rows[pro.pk]["kyc_state"] == ("approved" if pro.handyman_profile.is_approved else rows[pro.pk]["kyc_state"])


def test_user_detail_shows_full_contact_but_never_device_tokens_or_staff_accounts():
    c = person("ud_cli", first_name="Awa", last_name="Kone", phone="+2250701234567")
    Device.objects.create(user=c, device_token="SECRET-FCM-TOKEN-123", device_type="android")
    MarketingConsent.objects.create(user=c, granted=True, granted_at=timezone.now(), source="app")
    support = api(staff("ud_support", "support"))
    r = support.get(f"{BO}/users/{c.id}/")
    body = r.json()
    assert body["phone_full"] == "+2250701234567" and body["marketing_consent"]["granted"] is True
    assert body["devices"] == [{"platform": "android", "last_active": body["devices"][0]["last_active"]}]
    assert "SECRET-FCM-TOKEN" not in r.content.decode() and "password" not in r.content.decode().lower()
    assert support.get(f"{BO}/users/{staff('ud_other', 'ops').id}/").status_code == 404           # un compte d'administration n'est pas un « utilisateur »
    assert support.get(f"{BO}/users/999999/").status_code == 404


def test_only_users_manage_can_suspend_and_suspension_has_real_effects():
    cli, art = person("s_cli"), artisan("s_art")
    b = Booking.objects.create(client=cli, handyman=art, status="in_progress", address="x", city="x", booking_date=timezone.now())
    Device.objects.create(user=art, device_token="tok-s", device_type="android")
    refresh = RefreshToken.for_user(art)
    root = api(staff("s_root", superuser=True))
    assert api(staff("s_support", "support")).post(f"{BO}/users/{art.id}/suspend/", {"reason": "Fraude avérée"}, format="json").status_code == 403
    assert root.post(f"{BO}/users/{art.id}/suspend/", {}, format="json").status_code == 400      # motif obligatoire
    ok = root.post(f"{BO}/users/{art.id}/suspend/", {"reason": "Fraude avérée"}, format="json")
    assert ok.status_code == 200 and ok.json()["active_bookings"] == 1 and ok.json()["sessions_revoked"] >= 1
    art.refresh_from_db()
    assert art.is_active is False and not Device.objects.filter(user=art).exists()
    assert Booking.objects.get(pk=b.pk).status == "in_progress"                                  # jamais d'annulation automatique
    assert APIClient().post("/handy/auth/refresh/", {"refresh": str(refresh)}, format="json").status_code == 401
    assert not eligibility.is_publishable(art.handyman_profile)                                  # retrait immédiat par la règle
    event = audited("user.suspended", target_id=art.id).get()
    assert event.data["reason"] == "Fraude avérée" and event.actor.username == "s_root"
    assert root.post(f"{BO}/users/{art.id}/suspend/", {"reason": "Encore une fois"}, format="json").status_code == 409
    back = root.post(f"{BO}/users/{art.id}/reactivate/", {"reason": "Erreur de modération"}, format="json")
    art.refresh_from_db()
    assert back.status_code == 200 and art.is_active and audited("user.reactivated", target_id=art.id).exists()


def test_suspension_refuses_self_and_staff_accounts():
    root_user = staff("sf_root", superuser=True)
    other = staff("sf_other", "ops")
    root = api(root_user)
    assert root.post(f"{BO}/users/{root_user.id}/suspend/", {"reason": "Test de soi"}, format="json").status_code == 400
    assert root.post(f"{BO}/users/{other.id}/suspend/", {"reason": "Test personnel"}, format="json").status_code == 400
    other.refresh_from_db()
    assert other.is_active


# ═══ KYC ════════════════════════════════════════════════════════════════════════════════════════════════════════════

def pro(name, *, docs=(), approved=False):
    u = User.objects.create_user(name, f"{name}@x.test", "pass1234", user_type="handyman", is_verified=True, first_name=name, last_name="Pro")
    profile = u.handyman_profile
    profile.is_approved = approved
    profile.commune = "Cocody"
    profile.save()
    for doc_type, status in docs:
        HandymanDocument.objects.create(handyman=profile, document_type=doc_type, status=status, file="kyc/x.pdf")
    return profile


def test_kyc_queue_states_filters_and_priority():
    pending = pro("k_pending", docs=[("id_card", "pending")])
    ready = pro("k_ready", docs=[("id_card", "approved")])
    approved = pro("k_approved", docs=[("id_card", "approved")], approved=True)
    rejected = pro("k_rejected", docs=[("id_card", "rejected")])
    incomplete = pro("k_incomplete")
    ops = api(staff("k_ops", "ops"))
    rows = ops.get(f"{BO}/kyc/?page_size=50").json()["results"]
    state = {r["profile_id"]: r["state"] for r in rows}
    assert state[pending.pk] == "pending" and state[ready.pk] == "ready" and state[approved.pk] == "approved"
    assert state[rejected.pk] == "rejected" and state[incomplete.pk] == "incomplete"
    assert rows[0]["profile_id"] == pending.pk                                                     # à examiner d'abord
    assert [r["profile_id"] for r in ops.get(f"{BO}/kyc/?state=ready").json()["results"]] == [ready.pk]
    assert api(staff("k_mkt", "marketing")).get(f"{BO}/kyc/").status_code == 403


def test_kyc_detail_never_exposes_the_storage_url_and_files_are_audited_and_not_cacheable():
    p = pro("kd_pro", docs=[("id_card", "pending")])
    doc = p.documents.get()
    doc.file.save("cni.pdf", ContentFile(b"%PDF-1.4 contenu confidentiel"), save=True)
    ops = api(staff("kd_ops", "ops"))
    detail = ops.get(f"{BO}/kyc/{p.pk}/")
    assert detail.status_code == 200
    body = detail.json()
    assert body["documents"][0]["file_path"] == f"/handy/backoffice/kyc/documents/{doc.pk}/file/"
    assert "kyc/" not in detail.content.decode().replace("/handy/backoffice/kyc/", "") and "cni.pdf" not in detail.content.decode()
    assert {c["key"] for c in body["checklist"]} >= {"kyc", "approval"} and body["publishable"] is False
    f = ops.get(body["documents"][0]["file_path"])
    assert f.status_code == 200 and b"".join(f.streaming_content).startswith(b"%PDF")
    assert f["Cache-Control"] == "private, no-store, max-age=0" and "cni" not in f["Content-Disposition"]
    assert audited("kyc.document_viewed", target_id=doc.pk).count() == 1                           # chaque ouverture est journalisée
    for forbidden in (api(staff("kd_mkt", "marketing")), api(staff("kd_none")), api(person("kd_user")), api()):
        assert forbidden.get(body["documents"][0]["file_path"]).status_code in (401, 403)


def test_kyc_document_review_notifies_requires_a_reason_to_reject_and_is_not_silently_overwritten():
    p = pro("kr_pro", docs=[("id_card", "pending"), ("license", "pending")])
    ids, lic = p.documents.get(document_type="id_card"), p.documents.get(document_type="license")
    ops = api(staff("kr_ops", "ops"))
    assert ops.post(f"{BO}/kyc/documents/{lic.pk}/review/", {"action": "reject"}, format="json").status_code == 400      # motif obligatoire
    assert ops.post(f"{BO}/kyc/documents/{lic.pk}/review/", {"action": "n'importe quoi"}, format="json").status_code == 400
    ok = ops.post(f"{BO}/kyc/documents/{ids.pk}/review/", {"action": "approve"}, format="json")
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["reviewed_by"] == "Kr_Ops A."
    rej = ops.post(f"{BO}/kyc/documents/{lic.pk}/review/", {"action": "reject", "reason": "Photo illisible"}, format="json")
    assert rej.status_code == 200 and rej.json()["rejection_reason"] == "Photo illisible"
    again = ops.post(f"{BO}/kyc/documents/{ids.pk}/review/", {"action": "reject", "reason": "Changement d'avis"}, format="json")
    assert again.status_code == 409 and again.json()["code"] == "not_pending"
    types = set(Notification.objects.filter(user=p.user).values_list("notification_type", flat=True))
    assert {"kyc_approved", "kyc_rejected"} <= types                                                # l'artisan est prévenu (service existant)
    assert audited("kyc.document_approved", target_id=ids.pk).exists() and audited("kyc.document_rejected", target_id=lic.pk).exists()


def test_profile_approval_never_bypasses_the_kyc_and_suspension_is_immediate():
    p = pro("ka_pro", docs=[("id_card", "pending")])
    p.bio, p.experience_years, p.photo = "Plombier", 5, "profile_pics/x.jpg"
    p.save()
    p.skills.add(__import__("handy.models", fromlist=["ServiceCategory"]).ServiceCategory.objects.get_or_create(slug="plomberie", defaults={"name": "Plomberie"})[0])
    ops = api(staff("ka_ops", "ops"))
    refused = ops.post(f"{BO}/kyc/{p.pk}/approve/", {}, format="json")
    assert refused.status_code == 409 and refused.json()["code"] == "kyc_incomplete"               # pièce d'identité non approuvée
    p.refresh_from_db()
    assert p.is_approved is False
    p.documents.update(status="approved")
    ok = ops.post(f"{BO}/kyc/{p.pk}/approve/", {}, format="json")
    assert ok.status_code == 200
    p.refresh_from_db()
    assert p.is_approved and eligibility.is_publishable(p) and audited("kyc.profile_approved", target_id=p.pk).exists()
    assert ops.post(f"{BO}/kyc/{p.pk}/approve/", {}, format="json").status_code == 409             # déjà approuvé
    assert ops.post(f"{BO}/kyc/{p.pk}/suspend/", {}, format="json").status_code == 400             # motif obligatoire
    assert ops.post(f"{BO}/kyc/{p.pk}/suspend/", {"reason": "Document falsifié"}, format="json").status_code == 200
    p.refresh_from_db()
    assert not p.is_approved and not eligibility.is_publishable(p) and not identity.is_valid(p)    # badge d'identité retiré par la règle
    assert audited("kyc.profile_suspended", target_id=p.pk).get().data["reason"] == "Document falsifié"


# ═══ Tratra Trust ═══════════════════════════════════════════════════════════════════════════════════════════════════

def test_trust_detail_is_read_only_and_reevaluation_goes_through_the_rule():
    a = artisan("t_art")
    profile = a.handyman_profile
    ops = api(staff("t_ops", "ops"))
    before = BadgeAward.objects.count()
    detail = ops.get(f"{BO}/trust/{profile.pk}/")
    assert detail.status_code == 200 and {"measured", "score", "criteria", "awards"} <= set(detail.json())
    assert BadgeAward.objects.count() == before                                                   # consulter n'écrit rien
    res = ops.post(f"{BO}/trust/{profile.pk}/reevaluate/", {}, format="json")
    assert res.status_code == 200 and set(res.json()) == {"awarded", "revoked", "badges", "score"}
    profile.refresh_from_db()
    assert profile.trust_evaluated_at is not None and "VERIFIE" in profile.trust_badges           # attribué PAR LA RÈGLE, pas à la main
    assert audited("trust.reevaluated", target_id=profile.pk).exists()
    listing = ops.get(f"{BO}/trust/?badge=VERIFIE").json()
    assert [r["profile_id"] for r in listing["results"]] == [profile.pk]
    assert ops.get(f"{BO}/trust/?badge=INVENTE").json()["count"] >= 1                              # code inconnu ignoré, jamais d'erreur
    assert "expert_min_rating" in ops.get(f"{BO}/trust/config/").json()
    assert api(staff("t_support", "support")).get(f"{BO}/trust/").status_code == 403
    assert not any(route for route in ("grant", "award") if ops.post(f"{BO}/trust/{profile.pk}/{route}/", {}, format="json").status_code != 404)


# ═══ Tratra ID ══════════════════════════════════════════════════════════════════════════════════════════════════════

def test_tratra_id_list_validity_stats_revocation_and_mission_qr():
    a = artisan("i_art")
    pid = identity.ensure_id(a.handyman_profile)
    ops = api(staff("i_ops", "ops"))
    listing = ops.get(f"{BO}/tratra-id/").json()["results"]
    assert listing[0]["code"] == pid.code and listing[0]["valid"] is True
    assert ops.get(f"{BO}/tratra-id/?valid=false").json()["count"] == 0
    assert ops.get(f"{BO}/tratra-id/?q={pid.code[:7]}").json()["count"] == 1
    stats = ops.get(f"{BO}/tratra-id/stats/").json()
    assert (stats["ids_issued"], stats["ids_valid"]) == (1, 1)
    assert ops.post(f"{BO}/tratra-id/{pid.pk}/suspend/", {}, format="json").status_code == 400
    assert ops.post(f"{BO}/tratra-id/{pid.pk}/suspend/", {"reason": "Usurpation signalée"}, format="json").json()["valid"] is False
    assert ops.get(f"{BO}/tratra-id/?valid=false").json()["count"] == 1
    assert audited("tratra_id.revoked").exists()

    c = person("i_cli")
    b = Booking.objects.create(client=c, handyman=a, status="confirmed", address="x", city="x", booking_date=timezone.now())
    BookingPass.objects.create(booking=b, token_hash="h" * 64, expires_at=timezone.now() + timedelta(minutes=10))
    assert ops.post(f"{BO}/tratra-id/passes/{b.id}/revoke/", {"reason": "QR divulgué"}, format="json").json()["revoked"] == 1
    assert BookingPass.objects.get(booking=b).revoked_at is not None
    assert "token" not in ops.get(f"{BO}/tratra-id/stats/").content.decode()                       # aucun jeton dans les réponses
    assert api(staff("i_fin", "finance")).get(f"{BO}/tratra-id/").status_code == 403
