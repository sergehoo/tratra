"""Back-Office : socle (identité, droits, tableau de bord, export sûr) et garde-fou « aucune vue sans droit déclaré »."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APIClient

from backoffice import common, rbac
from handy.models import Booking, Dispute, HandymanDocument, Payment, Payout
from handy.test_eligibility import artisan, service

User = get_user_model()
pytestmark = pytest.mark.django_db


def user(name, kind="client", **kw):
    return User.objects.create_user(name, f"{name}@x.test", "pass1234", user_type=kind, is_verified=True, **kw)


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


# ── Identité et droits ─────────────────────────────────────────────────────────────────────────────────────────────

def test_me_refuses_everyone_without_a_role_and_lists_only_the_modules_of_the_role():
    assert api().get("/handy/backoffice/me/").status_code in (401, 403)
    assert api(user("c_plain")).get("/handy/backoffice/me/").status_code == 403
    assert api(staff("c_norole")).get("/handy/backoffice/me/").status_code == 403            # personnel sans rôle
    ok = api(staff("c_mkt", "marketing")).get("/handy/backoffice/me/").json()
    assert ok["roles"] == ["marketing"] and {m["id"] for m in ok["modules"]} == {"dashboard", "announcements", "campaigns", "notifications", "analytics"}
    assert "finance.manage" not in ok["permissions"] and ok["user"]["name"] == "C_Mkt A."
    root = api(staff("c_root", superuser=True)).get("/handy/backoffice/me/").json()
    assert len(root["modules"]) == 22 and root["roles"] == ["super_admin"]   # 18 modules du cahier des charges + Engagements + Messagerie + Tratra Flash + Engagement automatisé
    for module in root["modules"]:
        assert set(module) == {"id", "label", "permission", "icon", "path"} and module["path"].startswith("/backoffice")


def test_an_inactive_staff_member_loses_all_rights():
    u = staff("c_off", "ops")
    assert api(u).get("/handy/backoffice/me/").status_code == 200
    u.is_active = False
    u.save()
    assert rbac.user_roles(u) == set() and api(u).get("/handy/backoffice/me/").status_code in (401, 403)


def test_every_backoffice_endpoint_declares_the_right_it_requires():
    """Garde-fou : une vue ajoutée sans `bo_permission` serait refusée à tous (jamais ouverte par oubli) ; ce test le signale."""
    from django.urls import URLPattern, URLResolver

    from backoffice import urls

    missing = []

    def walk(patterns, prefix=""):
        for p in patterns:
            if isinstance(p, URLResolver):
                walk(p.url_patterns, prefix + str(p.pattern))
                continue
            assert isinstance(p, URLPattern)
            cb = p.callback
            cls = getattr(cb, "cls", None) or getattr(cb, "view_class", None)
            # `me` : identité, ouverte à tout connecté (403 sans rôle) ; racine du routeur : simple index des routes.
            if cls is None or cls.__name__ in ("me", "APIRootView"):
                continue
            # Routes de double authentification : accessibles AVANT vérification (sinon l'activation serait impossible), mais
            # réservées aux comptes d'administration par `IsStaffAccount`, limitées et journalisées (voir test_mfa.py).
            if cls.__name__.startswith("MFA"):
                assert [pc.__name__ for pc in cls.permission_classes] == ["IsStaffAccount"], prefix + str(p.pattern)
                continue
            if not getattr(cls, "bo_permission", None):
                missing.append(prefix + str(p.pattern))

    walk(urls.urlpatterns)
    assert missing == []


# ── Tableau de bord ────────────────────────────────────────────────────────────────────────────────────────────────

def seed_activity():
    c, a = user("d_cli"), artisan("d_art")
    svc = service(a)
    b = Booking.objects.create(client=c, handyman=a, service=svc, status="completed", address="x", city="x", booking_date=timezone.now() - timedelta(days=1))
    Booking.objects.create(client=c, handyman=a, service=svc, status="pending", address="x", city="x", booking_date=timezone.now() + timedelta(days=2))
    Payment.objects.create(booking=b, amount=Decimal("10000"), platform_fee=Decimal("1000"), method="om", status="released", is_paid=True)
    Payout.objects.create(handyman=a, amount=Decimal("4000"), status="pending")
    Dispute.objects.create(booking=b, reporter=c, reason="Retard", status="open")
    HandymanDocument.objects.create(handyman=a.handyman_profile, document_type="license", file="kyc/x.pdf", status="pending")
    return c, a, b


def test_dashboard_shows_real_numbers_and_hides_what_the_role_may_not_see():
    seed_activity()
    root = api(staff("d_root", superuser=True)).get("/handy/backoffice/dashboard/").json()
    assert root["kpis"]["bookings"]["total"] == 2 and root["kpis"]["bookings"]["by_status"]["pending"] == 1
    assert root["kpis"]["bookings"]["active"] == 1
    fin = root["kpis"]["finance"]
    assert (fin["gmv_30d"], fin["commission_30d"], fin["payouts_pending"], fin["payouts_pending_amount"]) == ("10000.00", "1000.00", 1, "4000.00")
    assert root["kpis"]["users"]["artisans"] >= 1 and len(root["series"]["bookings"]) == 30 and len(root["series"]["signups"]) == 30
    keys = {a["key"] for a in root["alerts"]}
    assert {"kyc_pending", "disputes_open", "payouts_pending"} <= keys
    assert sum(p["count"] for p in root["series"]["bookings"]) == 2                              # la courbe reprend les vraies réservations

    ops = api(staff("d_ops", "ops")).get("/handy/backoffice/dashboard/").json()
    assert "finance" not in ops["kpis"] and "payouts_pending" not in {a["key"] for a in ops["alerts"]}
    analyst = api(staff("d_ana", "analyst")).get("/handy/backoffice/dashboard/").json()
    assert set(analyst["kpis"]) == {"users", "bookings"} and analyst["alerts"] == []             # agrégats seulement, rien à traiter
    fin_role = api(staff("d_fin", "finance")).get("/handy/backoffice/dashboard/").json()
    assert "finance" in fin_role["kpis"] and "payouts_pending" in {a["key"] for a in fin_role["alerts"]}


def test_dashboard_is_refused_without_the_right_and_exposes_no_personal_or_gps_data():
    seed_activity()
    assert api().get("/handy/backoffice/dashboard/").status_code in (401, 403)
    assert api(user("d_plain")).get("/handy/backoffice/dashboard/").status_code == 403
    assert api(staff("d_none")).get("/handy/backoffice/dashboard/").status_code == 403
    text = api(staff("d_root2", superuser=True)).get("/handy/backoffice/dashboard/").content.decode()
    for forbidden in ("@x.test", "phone", "lat", "lng", "token", "password"):
        assert forbidden not in text, forbidden


# ── Utilitaires ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_csv_export_neutralizes_spreadsheet_formulas_and_masks_are_stable():
    r = common.csv_response("x.csv", ["nom", "valeur"], [["=HYPERLINK(\"http://evil\")", "+1"], ["-2", "@cmd"], ["normal", None]])
    text = r.content.decode("utf-8-sig")
    assert r["Content-Disposition"] == 'attachment; filename="x.csv"' and r["Cache-Control"] == "private, no-store"
    for cell in ("'=HYPERLINK", "'+1", "'-2", "'@cmd"):
        assert cell in text
    assert common.mask_phone("+2250701234567") == "+22507••••4567" and common.mask_phone(None) is None
    assert common.mask_email("serge@kaydan.com") == "s•••@kaydan.com" and common.mask_email("bad") is None
    assert common.day_bounds("2026-10-10").hour == 0 and common.day_bounds("2026-10-10", end=True).hour == 23
    assert common.day_bounds("pas-une-date") is None and common.day_bounds("") is None
