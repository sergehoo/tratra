"""Back-Office « pilotage » : Notifications, Continuité, Statistiques et exports, Réglages, Sécurité. Aucun secret dans les
réponses, réglages validés et journalisés, exports sûrs et audités, gestion des rôles sans verrouillage ni escalade."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from backoffice import rbac
from continuity.models import IdempotencyRecord
from handy.models import (
    Booking, CancellationPolicy, Coupon, Device, Notification, OTPCode, Payment, Payout, PricingRule, Review, ServiceCategory,
)
from handy.test_eligibility import artisan, service
from trust.models import AuditEvent, TrustConfig

User = get_user_model()
pytestmark = pytest.mark.django_db
BO = "/handy/backoffice"


def person(name, **kw):
    return User.objects.create_user(name, f"{name}@x.test", "pass1234", user_type="client", is_verified=True, **kw)


def staff(name, role=None, superuser=False):
    rbac.ensure_roles()
    u = User.objects.create_user(name, f"{name}@x.test", "pass1234", is_staff=True, is_superuser=superuser, first_name=name.title(), last_name="Admin", is_verified=True)
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


def make_booking(c, a, status="pending", **kw):
    return Booking.objects.create(client=c, handyman=a, status=status, address="Rue 1", city=kw.pop("city", "Abidjan"), booking_date=kw.pop("booking_date", timezone.now() + timedelta(days=1)), **kw)


# ═══ Notifications ══════════════════════════════════════════════════════════════════════════════════════════════════

def test_notification_monitoring_counts_real_statuses_and_exposes_no_message_body_token_or_code():
    c = person("n_cli")
    Device.objects.create(user=c, device_token="FCM-SECRET-TOKEN-XYZ", device_type="android")
    Notification.objects.create(user=c, notification_type="booking_confirmed", category="booking", title="Réservation confirmée", message="Corps privé : 12 rue des Lilas", push_status="sent")
    Notification.objects.create(user=c, notification_type="booking_confirmed", category="booking", title="Autre", message="m", push_status="failed")
    stuck = Notification.objects.create(user=c, notification_type="system", title="Bloquée", message="m", push_status="queued")
    Notification.objects.filter(pk=stuck.pk).update(created_at=timezone.now() - timedelta(minutes=40))
    OTPCode.issue(c, "login")
    used = OTPCode.issue(c, "phone")
    OTPCode.objects.filter(pk=used.pk).update(used=True)
    ops = api(staff("n_ops", "ops"))
    s = ops.get(f"{BO}/notifications/summary/")
    body = s.json()
    assert body["push"]["failed"] == 1 and body["push"]["sent"] == 1 and body["push"]["queued_stuck"] == 1
    assert body["devices"] == {"total": 1, "by_platform": {"android": 1}, "active_7d": 1} and body["otp"]["requested"] == 2 and body["otp"]["used"] == 1
    assert set(body["integrations"]) == {"push_fcm", "sms", "email"} and body["integrations"]["push_fcm"] == {"configured": False}
    text = s.content.decode() + ops.get(f"{BO}/notifications/").content.decode()
    for secret in ("FCM-SECRET-TOKEN-XYZ", "Corps privé", "rue des Lilas", OTPCode.objects.first().code + '"'):
        assert secret not in text, secret
    assert ops.get(f"{BO}/notifications/?push_status=failed").json()["count"] == 1
    assert ops.get(f"{BO}/notifications/?user={c.id}&category=booking").json()["count"] == 2
    assert ops.get(f"{BO}/notifications/?hours=abc").status_code == 200 and ops.get(f"{BO}/notifications/summary/?hours=99999").json()["window_hours"] == 720
    assert api(staff("n_fin", "finance")).get(f"{BO}/notifications/summary/").status_code == 403


# ═══ Continuité ═════════════════════════════════════════════════════════════════════════════════════════════════════

def test_continuity_overview_detects_stuck_activities_and_sync_signals_read_only():
    c, a = person("ct_cli"), artisan("ct_art")
    old_pending = make_booking(c, a, "pending")
    Booking.objects.filter(pk=old_pending.pk).update(created_at=timezone.now() - timedelta(hours=30))
    late = make_booking(c, a, "confirmed", booking_date=timezone.now() - timedelta(hours=9))
    long_run = make_booking(c, a, "in_progress", booking_date=timezone.now() - timedelta(hours=40))
    fresh = make_booking(c, a, "confirmed")
    IdempotencyRecord.objects.create(user=c, scope="booking.create", key="k" * 12, request_hash="h", status_code=201, response={})
    IdempotencyRecord.objects.create(user=c, scope="booking.transition:7", key="j" * 12, request_hash="h", status_code=200, response={})
    Payout.objects.create(handyman=a, amount=Decimal("1000"), status="failed")
    support = api(staff("ct_support", "support"))
    o = support.get(f"{BO}/continuity/overview/").json()
    assert o["active"] == {"pending": 1, "confirmed": 2, "in_progress": 1}
    assert o["stuck"] == {"pending_old": 1, "confirmed_late": 1, "in_progress_long": 1}                 # la mission future n'est pas bloquée
    assert o["idempotent_writes_24h"] == {"total": 2, "by_scope": {"booking.create": 1, "booking.transition": 1}} and o["sync"]["payouts_failed"] == 1
    rows = support.get(f"{BO}/continuity/stuck/").json()["results"]
    assert {r["id"] for r in rows} == {old_pending.id, late.id, long_run.id} and fresh.id not in {r["id"] for r in rows}
    assert all(r["reason"] and r["age_hours"] >= 6 for r in rows)
    assert [r["id"] for r in support.get(f"{BO}/continuity/stuck/?kind=confirmed_late").json()["results"]] == [late.id]
    assert Booking.objects.get(pk=late.pk).status == "confirmed" and Booking.objects.get(pk=late.pk).version == 1       # lecture seule : rien n'est forcé
    assert api(staff("ct_mkt", "marketing")).get(f"{BO}/continuity/overview/").status_code == 403


# ═══ Statistiques et exports ════════════════════════════════════════════════════════════════════════════════════════

def seed_stats():
    c, a = person("a_cli", city="Abidjan", phone="+2250701234567"), artisan("a_art")
    cat = ServiceCategory.objects.get_or_create(slug="plomberie", defaults={"name": "Plomberie"})[0]
    svc = service(a, "=HYPERLINK(\"http://evil\")")                   # titre piégé pour l'export CSV
    done = make_booking(c, a, "completed", service=svc)
    make_booking(c, a, "cancelled", service=svc, city="Bouaké")
    make_booking(c, a, "pending", service=svc)
    Payment.objects.create(booking=done, amount=Decimal("10000"), platform_fee=Decimal("1000"), method="om", status="released", is_paid=True, transaction_id="PROVIDER-REF-777")
    Review.objects.create(booking=done, rating=4, comment="Excellent travail confidentiel")
    return c, a


def test_analytics_overview_is_aggregated_and_money_needs_finance_view():
    seed_stats()
    analyst = api(staff("an_ana", "analyst"))
    r = analyst.get(f"{BO}/analytics/overview/")
    body = r.json()
    assert body["bookings"]["total"] == 3 and body["bookings"]["by_status"]["completed"] == 1
    assert body["bookings"]["completion_rate"] == pytest.approx(0.3333, abs=1e-3) and body["bookings"]["cancellation_rate"] == pytest.approx(0.3333, abs=1e-3)
    assert {"name": "Abidjan", "bookings": 2} in body["top_cities"] and body["reviews"] == {"count": 1, "average": 4.0} and body["active_artisans"] == 1
    assert "finance" not in body and sum(d["count"] for d in body["bookings"]["daily"]) == 3
    text = r.content.decode()
    for private in ("0701234567", "a_cli@x.test", "confidentiel", "PROVIDER-REF"):
        assert private not in text
    fin = api(staff("an_fin", "finance")).get(f"{BO}/analytics/overview/").json()["finance"]
    assert (fin["gmv"], fin["commission"], fin["paid_share"]) == ("10000.00", "1000.00", pytest.approx(0.3333, abs=1e-3))
    assert analyst.get(f"{BO}/analytics/overview/?from=2099-01-01&to=2099-02-01").json()["bookings"]["total"] == 0
    assert analyst.get(f"{BO}/analytics/overview/?from=pas-une-date").status_code == 200
    assert api(staff("an_support", "support")).get(f"{BO}/analytics/overview/").status_code == 403


def test_exports_are_permissioned_per_dataset_sanitized_capped_and_audited():
    seed_stats()
    root = api(staff("ex_root", superuser=True))
    analyst, finance, ops = api(staff("ex_ana", "analyst")), api(staff("ex_fin", "finance")), api(staff("ex_ops", "ops"))
    assert analyst.get(f"{BO}/analytics/export/users/").status_code == 403 and analyst.get(f"{BO}/analytics/export/payments/").status_code == 403
    assert analyst.get(f"{BO}/analytics/export/nimporte/").status_code == 404
    users = ops.get(f"{BO}/analytics/export/users/")
    assert users.status_code == 200 and users["Content-Type"].startswith("text/csv") and users["Cache-Control"] == "private, no-store"
    text = users.content.decode("utf-8-sig")
    assert text.splitlines()[0] == "id;inscrit_le;ville;actif;telephone_verifie;artisan;artisan_approuve"
    assert "0701234567" not in text and "@x.test" not in text                                       # aucun contact dans l'export
    bookings = finance.get(f"{BO}/analytics/export/bookings/").content.decode("utf-8-sig")
    assert "montant;commission" in bookings.splitlines()[0] and "'=HYPERLINK" in bookings and ";=HYPERLINK" not in bookings   # formule neutralisée
    assert "montant" not in ops.get(f"{BO}/analytics/export/bookings/").content.decode("utf-8-sig").splitlines()[0]            # ops : pas de montants
    pay = finance.get(f"{BO}/analytics/export/payments/").content.decode("utf-8-sig")
    assert "10000.00;1000.00;9000.00;om;released" in pay and "PROVIDER-REF" not in pay
    assert "confidentiel" not in root.get(f"{BO}/analytics/export/reviews/").content.decode("utf-8-sig")
    assert root.get(f"{BO}/analytics/export/audit/").status_code == 200 and ops.get(f"{BO}/analytics/export/audit/").status_code == 403
    event = audited("export.downloaded").filter(data__dataset="payments").get()
    assert event.data["rows"] == 1 and event.actor.username == "ex_fin"                              # chaque export est journalisé


# ═══ Réglages ═══════════════════════════════════════════════════════════════════════════════════════════════════════

def test_settings_overview_reports_integrations_honestly_and_never_a_secret():
    with override_settings(FCM_CREDENTIALS_JSON='{"private_key": "TOP-SECRET-KEY", "project_id": "tratra-prod"}', FCM_PROJECT_ID="tratra-prod", STRIPE_SECRET_KEY="sk_live_SECRET"):
        root = api(staff("st_root", superuser=True))
        r = root.get(f"{BO}/settings/")
    text = r.content.decode()
    for secret in ("TOP-SECRET-KEY", "tratra-prod", "sk_live", "private_key", "password", "SECRET"):
        assert secret not in text, secret
    integ = r.json()["integrations"]
    assert integ["payments"] == {"om": False, "mtn": False, "card": True, "cash": True}               # « disponible » = identifiants présents (la clé elle-même n'apparaît jamais)
    assert set(integ) >= {"push_fcm", "sms", "email", "payments", "routing_osrm", "object_storage"} and "configured" in integ["push_fcm"]
    assert api(staff("st_ops", "ops")).get(f"{BO}/settings/").status_code == 403


def test_pricing_rules_are_validated_updated_and_audited_with_old_and_new_values():
    root = api(staff("pr_root", superuser=True))
    cat = ServiceCategory.objects.create(name="Peinture", slug="peinture")
    bad = root.post(f"{BO}/settings/pricing-rules/", {"fee_percent": "80", "fee_min_xof": -3}, format="json")
    assert bad.status_code == 400 and set(bad.json()["fields"]) == {"fee_percent", "fee_min_xof"}
    ok = root.post(f"{BO}/settings/pricing-rules/", {"fee_percent": "12.5", "fee_min_xof": 700}, format="json")
    assert ok.status_code == 201 and ok.json()["fee_percent"] == "12.50"
    assert root.post(f"{BO}/settings/pricing-rules/", {"fee_percent": "10"}, format="json").json()["fields"]["category"]      # une seule règle générale active
    assert root.post(f"{BO}/settings/pricing-rules/", {"fee_percent": "9", "category": cat.pk}, format="json").status_code == 201
    rid = ok.json()["id"]
    assert root.patch(f"{BO}/settings/pricing-rules/{rid}/", {"fee_percent": "abc"}, format="json").status_code == 400
    upd = root.patch(f"{BO}/settings/pricing-rules/{rid}/", {"fee_percent": "11", "active": False}, format="json")
    assert upd.json()["fee_percent"] == "11.00" and upd.json()["active"] is False
    changes = audited("settings.pricing_rule_updated", target_id=rid).get().data["changes"]
    assert changes["fee_percent"] == {"old": "12.50", "new": "11.00"} and changes["active"] == {"old": "True", "new": "False"}
    assert root.patch(f"{BO}/settings/pricing-rules/99999/", {}, format="json").status_code == 404


def test_cancellation_policy_keeps_a_single_active_policy_and_trust_settings_are_bounded():
    root = api(staff("cp_root", superuser=True))
    first = root.post(f"{BO}/settings/cancellation-policies/", {"name": "Standard", "free_until_minutes": 120, "fee_percent": "15"}, format="json")
    assert first.status_code == 201
    second = root.post(f"{BO}/settings/cancellation-policies/", {"name": "Stricte", "free_until_minutes": 30, "fee_percent": "40"}, format="json")
    assert second.status_code == 201 and CancellationPolicy.objects.filter(active=True).count() == 1 and CancellationPolicy.objects.get(pk=second.json()["id"]).active
    assert root.post(f"{BO}/settings/cancellation-policies/", {"name": "", "free_until_minutes": -1, "fee_percent": "200"}, format="json").status_code == 400
    assert root.post(f"{BO}/settings/cancellation-policies/{first.json()['id']}/", {"fee_percent": "10"}, format="json").json()["fee_percent"] == "10.00"
    assert audited("settings.cancellation_policy_saved").count() == 3
    t = root.patch(f"{BO}/settings/trust/", {"expert_min_rating": "4.5", "weight_identity": 30, "sure_min_punctuality": "0.9"}, format="json")
    assert t.status_code == 200 and t.json()["trust"]["expert_min_rating"] == 4.5 and "réévaluation" in t.json()["applied_by"]
    assert TrustConfig.get_solo().weight_identity == 30
    bad = root.patch(f"{BO}/settings/trust/", {"expert_min_rating": "9", "weight_identity": 500, "inconnu": 1, "min_sample": 0}, format="json")
    assert bad.status_code == 400 and set(bad.json()["fields"]) == {"expert_min_rating", "weight_identity", "inconnu", "min_sample"}
    assert TrustConfig.get_solo().expert_min_rating == 4.5                                          # rien n'est appliqué si une valeur est invalide
    assert audited("settings.trust_updated").get().data["changes"]["weight_identity"]["new"] == "30"


def test_coupons_are_validated_unique_and_only_toggleable():
    root = api(staff("cu_root", superuser=True))
    now = timezone.now()
    good = {"code": "rentree-26", "percent_off": "10", "valid_from": now.isoformat(), "valid_to": (now + timedelta(days=30)).isoformat()}
    ok = root.post(f"{BO}/settings/coupons/", good, format="json")
    assert ok.status_code == 201 and ok.json()["code"] == "RENTREE-26" and ok.json()["valid_now"] is True
    assert root.post(f"{BO}/settings/coupons/", good, format="json").json()["fields"]["code"] == "Ce code existe déjà."
    assert root.post(f"{BO}/settings/coupons/", {**good, "code": "DEUX", "amount_off": "500"}, format="json").status_code == 400       # pourcentage OU montant
    assert root.post(f"{BO}/settings/coupons/", {**good, "code": "FIN-AVANT", "valid_to": (now - timedelta(days=1)).isoformat()}, format="json").json()["fields"]["valid_to"]
    assert root.post(f"{BO}/settings/coupons/", {**good, "code": "X!", "percent_off": "150"}, format="json").status_code == 400
    cid = ok.json()["id"]
    assert root.patch(f"{BO}/settings/coupons/{cid}/", {"percent_off": "90"}, format="json").status_code == 400                       # pas de modification de la valeur
    assert root.patch(f"{BO}/settings/coupons/{cid}/", {"active": False}, format="json").json()["valid_now"] is False
    assert Coupon.objects.get(pk=cid).percent_off == Decimal("10.00") and audited("settings.coupon_toggled", target_id=cid).exists()


# ═══ Sécurité ═══════════════════════════════════════════════════════════════════════════════════════════════════════

def test_staff_management_never_allows_lockout_self_edit_or_unverified_promotion():
    root_user = staff("sc_root", superuser=True)
    root = api(root_user)
    other_admin = staff("sc_other", "super_admin")
    ops_user = staff("sc_ops", "ops")
    listing = root.get(f"{BO}/security/staff/").json()["results"]
    assert {r["name"] for r in listing} >= {"Sc_Root A.", "Sc_Other A.", "Sc_Ops A."}
    # Vue réservée au Super Admin : e-mails COMPLETS (consultation journalisée) ; aucune donnée secrète n'y figure.
    assert {r["email"] for r in listing} >= {"sc_root@x.test", "sc_other@x.test", "sc_ops@x.test"} and "password" not in str(listing).lower()
    assert audited("contacts.unmasked_view", actor=root_user).exists()
    assert root.put(f"{BO}/security/staff/{root_user.id}/roles/", {"roles": ["ops"]}, format="json").json()["code"] == "self"             # pas d'auto-modification
    assert root.put(f"{BO}/security/staff/{ops_user.id}/roles/", {"roles": ["inconnu"]}, format="json").status_code == 400
    ok = root.put(f"{BO}/security/staff/{ops_user.id}/roles/", {"roles": ["support", "marketing"]}, format="json")
    assert ok.json()["roles"] == ["marketing", "support"] and audited("security.roles_changed", target_id=ops_user.id).get().data["before"] == ["ops"]
    assert rbac.has_permission(ops_user, "support.manage") and not rbac.has_permission(ops_user, "kyc.review")                            # effet réel
    # un super admin peut en retirer un autre (motif obligatoire), jamais lui-même : il en reste donc toujours un
    assert root.post(f"{BO}/security/staff/{other_admin.id}/remove/", {}, format="json").status_code == 400
    assert root.post(f"{BO}/security/staff/{other_admin.id}/remove/", {"reason": "Départ du collaborateur"}, format="json").status_code == 200
    other_admin.refresh_from_db()
    assert not other_admin.is_staff and rbac.user_roles(other_admin) == set() and audited("security.staff_removed", target_id=other_admin.id).exists()
    assert root.post(f"{BO}/security/staff/{root_user.id}/remove/", {"reason": "Auto-suppression"}, format="json").json()["code"] == "self"
    assert api(other_admin).get(f"{BO}/me/").status_code == 403                                      # l'accès est coupé immédiatement
    candidate, unverified = person("sc_cand"), User.objects.create_user("sc_unv", "u@x.test", "pass1234", is_verified=False)
    assert root.post(f"{BO}/security/staff/", {"user_id": unverified.id, "roles": ["analyst"]}, format="json").status_code == 400
    assert root.post(f"{BO}/security/staff/", {"user_id": candidate.id, "roles": []}, format="json").status_code == 400
    added = root.post(f"{BO}/security/staff/", {"user_id": candidate.id, "roles": ["analyst"]}, format="json")
    candidate.refresh_from_db()
    assert added.status_code == 201 and rbac.user_roles(candidate) == {"analyst"} and audited("security.staff_added", target_id=candidate.id).exists()
    assert api(staff("sc_ops2", "ops")).get(f"{BO}/security/staff/").status_code == 403


def test_sessions_never_expose_tokens_and_can_be_revoked_per_session_or_per_account():
    c = person("ss_cli")
    t1, t2 = RefreshToken.for_user(c), RefreshToken.for_user(c)
    root = api(staff("ss_root", superuser=True))
    r = root.get(f"{BO}/security/sessions/?user={c.id}")
    rows = r.json()["results"]
    assert len(rows) == 2 and all(x["fingerprint"].startswith("…") and x["revoked"] is False for x in rows)
    text = r.content.decode()
    assert str(t1) not in text and str(t2) not in text and "eyJ" not in text                          # aucun jeton dans la réponse
    one = root.post(f"{BO}/security/sessions/{rows[0]['id']}/revoke/", {}, format="json")
    assert one.status_code == 200 and root.get(f"{BO}/security/sessions/?user={c.id}&active=true").json()["count"] == 1
    n = root.post(f"{BO}/security/users/{c.id}/revoke-sessions/", {}, format="json")
    assert n.json()["sessions_revoked"] == 1 and root.get(f"{BO}/security/sessions/?user={c.id}&active=true").json()["count"] == 0
    assert APIClient().post("/handy/auth/refresh/", {"refresh": str(t2)}, format="json").status_code == 401        # la session révoquée ne se renouvelle plus
    assert audited("security.sessions_revoked", target_id=c.id).exists() and audited("security.session_revoked").exists()
    assert root.post(f"{BO}/security/sessions/999999/revoke/", {}, format="json").status_code == 404
    assert api(staff("ss_ops", "ops")).get(f"{BO}/security/sessions/").status_code == 403


def test_audit_log_is_filterable_exposes_who_did_what_and_roles_catalog_matches_rbac():
    root_user = staff("au_root", superuser=True)
    root = api(root_user)
    c = person("au_cli")
    root.post(f"{BO}/users/{c.id}/suspend/", {"reason": "Fraude avérée"}, format="json")
    root.post(f"{BO}/users/{c.id}/reactivate/", {"reason": "Erreur de modération"}, format="json")
    rows = root.get(f"{BO}/security/audit/?backoffice=true&target_type=user&target_id={c.id}").json()["results"]
    assert [r["action"] for r in rows] == ["backoffice.user.reactivated", "backoffice.user.suspended"]
    assert rows[0]["actor"] == "Au_Root A." and rows[1]["data"]["reason"] == "Fraude avérée"
    assert root.get(f"{BO}/security/audit/?action=backoffice.user.susp").json()["count"] == 1
    assert root.get(f"{BO}/security/audit/?actor={root_user.id}").json()["count"] >= 2 and root.get(f"{BO}/security/audit/?from=2099-01-01").json()["count"] == 0
    assert "backoffice.user.suspended" in root.get(f"{BO}/security/audit/actions/").json()["actions"]
    roles = root.get(f"{BO}/security/roles/").json()
    assert {r["id"] for r in roles["roles"]} == set(rbac.ROLES) and set(roles["permissions"]) == set(rbac.PERMISSIONS)
    ops = next(r for r in roles["roles"] if r["id"] == "ops")
    assert ops["permissions"] == sorted(rbac.ROLES["ops"])
    assert api(staff("au_support", "support")).get(f"{BO}/security/audit/").status_code == 403
