"""Back-Office « argent et relation » : Business (supervision), Finances, Support. Pas de paiement fabriqué, retrait validé
avec référence, remboursement par l'escrow, séparation des rôles, aucune donnée sensible exposée."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APIClient

from backoffice import rbac
from backoffice.models import SupportNote
from business import rbac as business_rbac
from business import services as business
from business.models import Budget, ConsolidatedInvoice, InterventionRequest, Membership, Organization, Role, Site
from handy.models import Booking, Dispute, Invoice, Notification, Payment, Payout, Report, Review
from handy.test_eligibility import artisan, service
from trust.models import AuditEvent

User = get_user_model()
pytestmark = pytest.mark.django_db
BO = "/handy/backoffice"


def person(name, **kw):
    return User.objects.create_user(name, f"{name}@x.test", "pass1234", user_type="client", is_verified=True, **kw)


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


def make_booking(client, art, status="completed", **kw):
    return Booking.objects.create(client=client, handyman=art, status=status, address="Rue 1", city="Abidjan", booking_date=timezone.now() + timedelta(days=1), **kw)


def pay(booking, status="held", amount="10000", fee="1000"):
    return Payment.objects.create(booking=booking, amount=Decimal(amount), platform_fee=Decimal(fee), method="om", status=status, is_paid=status != "pending", transaction_id=f"SECRET-REF-{booking.pk}")


def make_org(owner_name="o_owner", name="Hôtel Ivoire"):
    owner = person(owner_name, first_name="Marie", last_name="Diallo", phone="+2250700000009")
    org = business.create_organization(owner, name=name, city="Abidjan", legal_name="Hôtel Ivoire SA", registration_number="CI-ABJ-2020-B-1234")
    site = Site.objects.create(organization=org, name="Siège", city="Abidjan")
    return owner, org, site


# ═══ Business ═══════════════════════════════════════════════════════════════════════════════════════════════════════

def test_business_supervision_lists_details_and_hides_coordinates_and_contacts():
    owner, org, site = make_org()
    m = Membership.objects.get(organization=org, user=owner)
    req = business.create_request(org, owner, m, site=site, title="Climatisation en panne", priority="urgent")
    InterventionRequest.objects.filter(pk=req.pk).update(due_response_at=timezone.now() - timedelta(hours=2), due_resolution_at=timezone.now() - timedelta(hours=1))
    Budget.objects.create(organization=org, name="Maintenance T4", period_start=date.today() - timedelta(days=10), period_end=date.today() + timedelta(days=60), amount=Decimal("500000"))
    ConsolidatedInvoice.objects.create(organization=org, number="FAC-2026-0001", period_start=date.today() - timedelta(days=30), period_end=date.today(), total=Decimal("120000"))
    finance = api(staff("bz_fin", "finance"))
    row = finance.get(f"{BO}/business/organizations/?q=ivoire").json()["results"][0]
    assert (row["name"], row["members"], row["sites"], row["open_requests"], row["owner"]) == ("Hôtel Ivoire", 1, 1, 1, "Marie D.")
    r = finance.get(f"{BO}/business/organizations/{org.id}/")
    d = r.json()
    assert d["requests"]["late_response"] == 1 and d["members_list"][0]["phone"] == "+22507••••0009" and d["budgets"][0]["level"] in ("ok", "warning", "exceeded")
    assert d["invoices"][0]["number"] == "FAC-2026-0001" and d["contracts"] == {"active": 0, "total": 0}
    text = r.content.decode()
    assert "0700000009" not in text and '"location"' not in text and '"lat"' not in text and '"lng"' not in text
    reqs = finance.get(f"{BO}/business/requests/?overdue=true").json()["results"]
    assert reqs[0]["number"] == req.number and reqs[0]["overdue"] is True
    assert finance.get(f"{BO}/business/requests/?status=completed").json()["count"] == 0
    assert finance.get(f"{BO}/business/invoices/").json()["results"][0]["lines"] == 0
    assert api(staff("bz_support", "support")).get(f"{BO}/business/organizations/").status_code == 403


def test_organization_suspension_cuts_member_access_with_reason_and_audit_without_deleting_anything():
    owner, org, _ = make_org("os_owner", "Banque Atlantique")
    ops = api(staff("os_ops", "ops"))
    assert business_rbac.membership_for(owner, org.id) is not None
    assert ops.post(f"{BO}/business/organizations/{org.id}/suspend/", {}, format="json").status_code == 400
    assert ops.post(f"{BO}/business/organizations/{org.id}/suspend/", {"reason": "Impayés répétés"}, format="json").json()["is_active"] is False
    assert business_rbac.membership_for(owner, org.id) is None                                       # accès Business coupé par la règle existante
    assert Membership.objects.filter(organization=org).exists() and Organization.objects.filter(pk=org.id).exists()
    assert ops.post(f"{BO}/business/organizations/{org.id}/suspend/", {"reason": "Encore une fois"}, format="json").status_code == 409
    assert ops.post(f"{BO}/business/organizations/{org.id}/reactivate/", {"reason": "Régularisé"}, format="json").json()["is_active"] is True
    assert business_rbac.membership_for(owner, org.id) is not None
    assert audited("organization.suspended", target_id=org.id).get().data["reason"] == "Impayés répétés"


# ═══ Finances ═══════════════════════════════════════════════════════════════════════════════════════════════════════

def test_finance_summary_lists_and_details_are_real_and_hide_provider_references():
    c, a = person("f_cli"), artisan("f_art")
    held, released = pay(make_booking(c, a)), pay(make_booking(c, a), status="released", amount="20000", fee="2000")
    finance = api(staff("f_fin", "finance"))
    s = finance.get(f"{BO}/finance/summary/").json()
    assert s["gmv"] == "30000.00" and s["escrow_held"] == "10000.00" and s["commission_earned"] == "2000.00" and s["commission_in_escrow"] == "1000.00"
    assert s["by_status"]["held"] == {"count": 1, "amount": "10000.00"} and s["payouts"] == {}
    listing = finance.get(f"{BO}/finance/payments/?status=held")
    row = listing.json()["results"][0]
    assert (row["amount"], row["platform_fee"], row["net"], row["status"]) == ("10000.00", "1000.00", "9000.00", "held")
    assert "SECRET-REF" not in listing.content.decode()                                              # référence fournisseur : jamais en liste
    detail = finance.get(f"{BO}/finance/payments/{held.id}/")
    assert detail.json()["can_refund"] is True and "SECRET-REF" not in detail.content.decode()
    assert finance.get(f"{BO}/finance/payments/?q={held.booking_id}").json()["count"] == 1
    assert finance.get(f"{BO}/finance/payments/?from=2099-01-01").json()["count"] == 0
    for denied in (api(staff("f_ops", "ops")), api(staff("f_mkt", "marketing")), api(person("f_user")), api()):
        assert denied.get(f"{BO}/finance/summary/").status_code in (401, 403)


def test_refund_goes_through_the_escrow_with_reason_amount_checks_and_audit_never_creating_a_payment():
    c, a = person("rf_cli"), artisan("rf_art")
    p = pay(make_booking(c, a))
    fin_view_only = api(staff("rf_ana", "analyst"))
    assert fin_view_only.post(f"{BO}/finance/payments/{p.id}/refund/", {"reason": "Pas mon rôle"}, format="json").status_code == 403
    finance = api(staff("rf_fin", "finance"))
    assert finance.post(f"{BO}/finance/payments/{p.id}/refund/", {}, format="json").status_code == 400
    assert finance.post(f"{BO}/finance/payments/{p.id}/refund/", {"reason": "Geste commercial", "amount": "999999"}, format="json").json()["code"] == "invalid_amount"
    assert finance.post(f"{BO}/finance/payments/{p.id}/refund/", {"reason": "Geste commercial", "amount": "-5"}, format="json").status_code == 400
    assert finance.post(f"{BO}/finance/payments/{p.id}/refund/", {"reason": "Geste commercial", "amount": "abc"}, format="json").status_code == 400
    ok = finance.post(f"{BO}/finance/payments/{p.id}/refund/", {"reason": "Geste commercial", "amount": "4000"}, format="json")
    assert ok.status_code == 200 and ok.json()["status"] == "refunded" and ok.json()["refunded_amount"] == "4000.00"
    assert finance.get(f"{BO}/finance/payments/{p.id}/").json()["logs"][-1]["notes"] == "Back-Office : Geste commercial"      # trace dans le journal du paiement
    assert Notification.objects.filter(user=c, notification_type="refund_issued").exists()
    again = finance.post(f"{BO}/finance/payments/{p.id}/refund/", {"reason": "Un second remboursement"}, format="json")
    assert again.status_code == 409 and again.json()["code"] == "invalid_transition"
    assert audited("payment.refunded", target_id=p.id).get().data["amount"] == "4000.00"
    count = Payment.objects.count()
    for forbidden in ("mark-paid", "create", "validate", "confirm"):
        assert finance.post(f"{BO}/finance/payments/{p.id}/{forbidden}/", {}, format="json").status_code == 404
    assert finance.post(f"{BO}/finance/payments/", {"amount": 1}, format="json").status_code == 405
    assert Payment.objects.count() == count                                                          # aucun paiement fabriqué


def test_payout_is_sent_only_with_a_reference_and_rejection_frees_the_earnings():
    c, a = person("po_cli"), artisan("po_art")
    pay(make_booking(c, a), status="released", amount="50000", fee="5000")
    payout = Payout.objects.create(handyman=a, amount=Decimal("30000"), status="pending")
    finance = api(staff("po_fin", "finance"))
    assert finance.get(f"{BO}/finance/payouts/?status=pending").json()["results"][0]["id"] == payout.id
    assert finance.post(f"{BO}/finance/payouts/{payout.id}/approve/", {}, format="json").status_code == 400           # référence obligatoire
    assert finance.post(f"{BO}/finance/payouts/{payout.id}/approve/", {"reference": "ab"}, format="json").status_code == 400
    assert finance.post(f"{BO}/finance/payouts/{payout.id}/bizarre/", {"reference": "OM-2026-77"}, format="json").status_code == 404
    ok = finance.post(f"{BO}/finance/payouts/{payout.id}/approve/", {"reference": "OM-2026-77"}, format="json")
    assert ok.status_code == 200 and ok.json()["status"] == "sent" and ok.json()["notes"] == "Réf. OM-2026-77" and ok.json()["available_after"] == "15000.00"
    assert Notification.objects.filter(user=a, title="Retrait envoyé").exists() and audited("payout.sent", target_id=payout.id).exists()
    assert finance.post(f"{BO}/finance/payouts/{payout.id}/reject/", {"reason": "Trop tard pour cela"}, format="json").json()["code"] == "not_pending"
    second = Payout.objects.create(handyman=a, amount=Decimal("15000"), status="pending")
    assert finance.post(f"{BO}/finance/payouts/{second.id}/reject/", {}, format="json").status_code == 400
    rej = finance.post(f"{BO}/finance/payouts/{second.id}/reject/", {"reason": "Numéro Mobile Money invalide"}, format="json")
    assert rej.json()["status"] == "failed" and rej.json()["available_after"] == "15000.00"          # les gains redeviennent disponibles
    assert api(staff("po_support", "support")).get(f"{BO}/finance/payouts/").status_code == 403
    assert finance.get(f"{BO}/finance/invoices/").status_code == 200


# ═══ Support ════════════════════════════════════════════════════════════════════════════════════════════════════════

def test_support_queue_orders_by_age_flags_overdue_and_overview_exposes_titles_only():
    c, a = person("sp_cli", first_name="Awa", last_name="Kone", phone="+2250701234567"), artisan("sp_art")
    b = make_booking(c, a)
    old = Dispute.objects.create(booking=b, reporter=c, reason="Travail non terminé", status="open")
    Dispute.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(hours=60))
    rv = Review.objects.create(booking=b, rating=1, comment="Nul")
    Report.objects.create(reporter=a, report_type="review", review=rv, reason="Insulte")
    Notification.objects.create(user=c, notification_type="system", title="Titre visible", message="Corps confidentiel du message")
    support = api(staff("sp_support", "support"))
    q = support.get(f"{BO}/support/queue/").json()
    assert q["count"] == 2 and q["overdue"] == 1 and q["results"][0]["kind"] == "dispute" and q["results"][0]["overdue"] is True and q["results"][0]["age_hours"] >= 60
    assert q["sla_hours"] == {"dispute": 48, "report": 72}
    r = support.get(f"{BO}/support/users/{c.id}/")
    o = r.json()
    assert o["user"]["phone"] == "+22507••••4567" and o["bookings"][0]["role"] == "client" and o["disputes"][0]["id"] == old.id
    assert o["notifications"][0]["title"] == "Titre visible" and "Corps confidentiel" not in r.content.decode()      # titres seulement
    assert support.get(f"{BO}/support/users/{staff('sp_other', 'ops').id}/").status_code == 404
    assert api(staff("sp_ops", "ops")).get(f"{BO}/support/queue/").status_code == 403


def test_support_notes_are_internal_validated_and_audited_without_their_content():
    c = person("sn_cli")
    support = api(staff("sn_support", "support"))
    assert support.post(f"{BO}/support/users/{c.id}/notes/", {"body": "a"}, format="json").json()["fields"]["body"]
    assert support.post(f"{BO}/support/users/{c.id}/notes/", {"body": "x" * 2001}, format="json").status_code == 400
    ok = support.post(f"{BO}/support/users/{c.id}/notes/", {"body": "Appelé le 10/10, remboursement promis sous 48 h."}, format="json")
    assert ok.status_code == 201 and ok.json()["author"] == "Sn_Support A."
    assert SupportNote.objects.filter(user=c).count() == 1
    assert support.get(f"{BO}/support/users/{c.id}/").json()["notes"][0]["body"].startswith("Appelé le 10/10")
    event = audited("support.note_added", target_id=c.id).get()
    assert "remboursement" not in str(event.data)                                                    # le journal ne duplique pas le contenu
    # l'utilisateur ne voit jamais ses notes : aucune route publique ne les expose
    assert "remboursement promis" not in api(c).get("/handy/me/dashboard/").content.decode()
    assert api(staff("sn_fin", "finance")).post(f"{BO}/support/users/{c.id}/notes/", {"body": "Pas mon rôle"}, format="json").status_code == 403
