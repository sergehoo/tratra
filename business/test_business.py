"""Tratra Business : isolation entre organisations, RBAC, validation hiérarchique, affectation, SLA, budgets, facturation."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from business import services
from business.models import (ApprovalStep, Equipment, InterventionRequest, Invitation, Membership, Organization, PreventivePlan,
                             Role, Site)
from handy.models import Booking, CompanyProfile, Notification, ServiceCategory, TimeOff
from handy.test_booking_regression import _client
from handy.test_eligibility import artisan, service
from trust.models import AuditEvent

User = get_user_model()
pytestmark = pytest.mark.django_db
ABIDJAN = (5.36, -4.0083)


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


def api(user=None):
    c = APIClient()
    if user:
        c.force_authenticate(user)
    return c


def plomberie():
    return ServiceCategory.objects.get_or_create(slug="plomberie", defaults={"name": "Plomberie"})[0]


class Company:
    """Une organisation de test : propriétaire, un site avec équipement, et des membres par rôle."""

    def __init__(self, name="Acme", prefix="acme"):
        self.owner = _client(f"{prefix}_owner")
        r = api(self.owner).post("/handy/business/orgs/", {"name": name, "currency": "XOF"}, format="json")
        assert r.status_code == 201, r.content
        self.id = r.json()["id"]
        self.prefix = prefix
        site = self.post("sites/", {"name": "Siège", "address": "Rue 1", "city": "Abidjan", "lat": ABIDJAN[0], "lng": ABIDJAN[1]})
        self.site = site.json()["id"]
        eq = self.post("equipment/", {"name": "Climatiseur salle A", "site": self.site, "category": plomberie().id, "location_detail": "Étage 2"})
        assert eq.status_code == 201, eq.content
        self.equipment = eq.json()["id"]
        self.equipment_code = eq.json()["qr_code"]
        self.members = {}

    def url(self, path):
        return f"/handy/business/orgs/{self.id}/{path}"

    def post(self, path, data=None, user=None, **kw):
        return api(user or self.owner).post(self.url(path), data or {}, format="json", **kw)

    def get(self, path, user=None, **kw):
        return api(user or self.owner).get(self.url(path), **kw)

    def member(self, role, sites=()):
        name = f"{self.prefix}_{role}_{len(self.members)}"
        user = _client(name)
        code = self.post("invitations/", {"role": role, "sites": list(sites), "label": name}).json()["code"]
        assert api(user).post("/handy/business/join/", {"code": code}, format="json").status_code == 201
        self.members[name] = user
        return user

    def request(self, user=None, **extra):
        payload = {"site": self.site, "title": "Fuite au sous-sol", "category": plomberie().id, "priority": "normal", **extra}
        return self.post("requests/", payload, user=user)


def rule(company, steps, **kw):
    r = company.post("approval-rules/", {"name": "Règle", "steps": steps, **kw})
    assert r.status_code == 201, r.content
    return r.json()["id"]


# ---- Organisation, adhésions, invitations --------------------------------------------------------------------

def test_any_account_creates_an_organization_and_becomes_its_owner():
    c = Company()
    mine = api(c.owner).get("/handy/business/orgs/").json()
    assert [o["id"] for o in mine] == [c.id] and mine[0]["role"] == "owner" and "org.delete" in mine[0]["capabilities"]
    assert api().get("/handy/business/orgs/").status_code == 401
    assert api(_client("nobody")).get("/handy/business/orgs/").json() == []


def test_company_accounts_get_their_organization_without_duplicates():
    user = User.objects.create_user("biz_company", "bc@x.test", "pass1234", user_type="entreprise")
    cp = CompanyProfile.objects.get(user=user)
    org = Organization.objects.get(company_profile=cp)
    assert org.owner_id == user.id and org.name == cp.company_name
    assert Membership.objects.get(organization=org, user=user).role == "owner"
    cp.save()  # une nouvelle sauvegarde ne duplique rien
    assert Organization.objects.filter(company_profile=cp).count() == 1


def test_invitation_code_is_shown_once_single_use_and_stored_hashed():
    c = Company()
    inv = c.post("invitations/", {"role": "requester", "label": "Awa"})
    code = inv.json()["code"]
    assert inv["Cache-Control"] == "private, no-store"
    assert Invitation.objects.get().code_hash != code and code.count("-") == 2
    assert "code" not in str(c.get("invitations/").json())
    user = _client("biz_invited")
    assert api(user).post("/handy/business/join/", {"code": code}, format="json").status_code == 201
    assert Membership.objects.get(organization_id=c.id, user=user).role == "requester"
    assert api(_client("biz_late")).post("/handy/business/join/", {"code": code}, format="json").status_code == 404  # déjà utilisé
    assert api(user).post("/handy/business/join/", {"code": "ZZZZ-ZZZZ-ZZZZ"}, format="json").status_code == 404


def test_expired_and_revoked_invitations_are_refused_and_the_owner_role_is_not_invitable():
    c = Company()
    code = c.post("invitations/", {"role": "viewer"}).json()["code"]
    Invitation.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert api(_client("biz_exp")).post("/handy/business/join/", {"code": code}, format="json").status_code == 404
    inv = c.post("invitations/", {"role": "viewer"}).json()
    assert c.owner and api(c.owner).delete(c.url(f"invitations/{inv['id']}/")).status_code == 204
    assert api(_client("biz_rev")).post("/handy/business/join/", {"code": inv["code"]}, format="json").status_code == 404
    assert c.post("invitations/", {"role": "owner"}).status_code == 400


def test_member_management_protects_the_owner_and_keeps_history():
    c = Company()
    admin, req = c.member("admin"), c.member("requester")
    mid = Membership.objects.get(organization_id=c.id, user=req).id
    owner_mid = Membership.objects.get(organization_id=c.id, user=c.owner).id
    assert api(admin).patch(c.url(f"members/{mid}/"), {"role": "viewer"}, format="json").status_code == 200
    assert api(admin).patch(c.url(f"members/{owner_mid}/"), {"role": "viewer"}, format="json").status_code == 409
    assert api(admin).delete(c.url(f"members/{owner_mid}/")).status_code == 409
    assert api(admin).patch(c.url(f"members/{mid}/"), {"role": "owner"}, format="json").status_code == 400
    assert api(admin).delete(c.url(f"members/{mid}/")).status_code == 204
    assert Membership.objects.get(pk=mid).is_active is False
    assert api(req).get(c.url("sites/")).status_code == 404  # retiré : l'organisation n'existe plus pour lui
    assert AuditEvent.objects.filter(action="member.removed", organization_id=c.id).exists()


# ---- Isolation stricte entre organisations -----------------------------------------------------------------

LIST_ENDPOINTS = ["sites/", "buildings/", "equipment/", "members/", "requests/", "contracts/", "preventive-plans/", "budgets/",
                  "invoices/", "approval-rules/", "dashboard/", "audit/", "invitations/"]


def test_other_organizations_and_anonymous_see_nothing_at_all():
    a, b = Company("A", "orga"), Company("B", "orgb")
    r = a.request().json()
    stranger = _client("stranger")
    for path in LIST_ENDPOINTS:
        assert api().get(a.url(path)).status_code == 401, path
        assert api(b.owner).get(a.url(path)).status_code == 404, path          # propriétaire d'une AUTRE organisation
        assert api(stranger).get(a.url(path)).status_code == 404, path
    assert api(b.owner).get(a.url(f"requests/{r['id']}/")).status_code == 404
    assert api(b.owner).patch(a.url(f"sites/{a.site}/"), {"name": "Piraté"}, format="json").status_code == 404
    assert Site.objects.get(pk=a.site).name == "Siège"
    # la liste d'une organisation ne contient jamais les données d'une autre
    assert {s["id"] for s in b.get("sites/").json()} == {b.site}
    assert {x["id"] for x in b.get("requests/").json()["results"]} == set()


def test_cross_organization_references_are_rejected():
    a, b = Company("A", "orgc"), Company("B", "orgd")
    # un site / équipement d'une autre organisation ne peut être référencé nulle part
    assert a.request(site=b.site).status_code == 400
    assert a.request(equipment=b.equipment).status_code == 400
    assert a.post("equipment/", {"name": "X", "site": b.site}).status_code == 400
    assert a.post("buildings/", {"name": "Bât", "site": b.site}).status_code == 400
    assert a.post("budgets/", {"name": "B", "site": b.site, "period_start": "2026-01-01", "period_end": "2026-12-31", "amount": "1000"}).status_code == 400
    assert a.post("preventive-plans/", {"equipment": b.equipment, "title": "P", "frequency_days": 30, "next_due_on": "2026-12-01"}).status_code == 400
    assert a.post("approval-rules/", {"name": "R", "site": b.site, "steps": ["admin"]}).status_code == 400
    assert not InterventionRequest.objects.exists()


def test_equipment_qr_lookup_is_for_members_of_that_organization_only():
    a, b = Company("A", "orge"), Company("B", "orgf")
    assert api(a.owner).get(f"/handy/business/equipment/lookup/{a.equipment_code}/").status_code == 200
    for other in (b.owner, _client("rand")):
        assert api(other).get(f"/handy/business/equipment/lookup/{a.equipment_code}/").status_code == 404
    assert api().get(f"/handy/business/equipment/lookup/{a.equipment_code}/").status_code == 401
    assert api(a.owner).get("/handy/business/equipment/lookup/EQ-ZZZZ-ZZZZ/").status_code == 404
    png = a.get(f"equipment/{a.equipment}/qr.png")
    assert png.status_code == 200 and png["Content-Type"] == "image/png" and png.content.startswith(b"\x89PNG")
    assert api(b.owner).get(a.url(f"equipment/{a.equipment}/qr.png")).status_code == 404


# ---- RBAC ---------------------------------------------------------------------------------------------------------------

def test_role_capabilities_are_enforced_server_side():
    c = Company("Rbac", "rbac")
    roles = {r: c.member(r) for r in ("admin", "site_manager", "approver", "requester", "finance", "viewer")}
    site = {"name": "Annexe"}
    expected_site_create = {"admin": 201, "site_manager": 403, "approver": 403, "requester": 403, "finance": 403, "viewer": 403}
    for role, code in expected_site_create.items():
        assert c.post("sites/", {**site, "name": f"Annexe {role}"}, user=roles[role]).status_code == code, role
    # lecture de la structure : tous les rôles ; membres : administrateur seulement
    for role, user in roles.items():
        assert c.get("sites/", user=user).status_code == 200, role
    assert {r: c.get("members/", user=u).status_code for r, u in roles.items()} == {
        "admin": 200, "site_manager": 403, "approver": 403, "requester": 403, "finance": 403, "viewer": 403}
    # créer une demande : demandeur, responsable de site, administrateur — pas le lecteur ni la finance
    created = {r: c.request(user=u).status_code for r, u in roles.items()}
    assert created == {"admin": 201, "site_manager": 201, "approver": 403, "requester": 201, "finance": 403, "viewer": 403}
    # budgets : finance et administrateur
    budget = {"name": "Q1", "period_start": "2026-01-01", "period_end": "2026-03-31", "amount": "100000"}
    assert {r: c.post("budgets/", budget, user=u).status_code for r, u in roles.items()} == {
        "admin": 201, "site_manager": 403, "approver": 403, "requester": 403, "finance": 201, "viewer": 403}
    # règles de validation et journal : administrateur ; journal aussi pour la finance
    assert c.post("approval-rules/", {"name": "R", "steps": ["admin"]}, user=roles["site_manager"]).status_code == 403
    assert c.get("audit/", user=roles["finance"]).status_code == 200 and c.get("audit/", user=roles["requester"]).status_code == 403
    # tableau de bord : tous sauf demandeur
    assert {r: c.get("dashboard/", user=u).status_code for r, u in roles.items()} == {
        "admin": 200, "site_manager": 200, "approver": 200, "requester": 403, "finance": 200, "viewer": 200}


def test_requesters_only_see_their_own_requests_and_site_scope_is_enforced():
    c = Company("Scope", "scope")
    annex = c.post("sites/", {"name": "Annexe", "lat": 5.4, "lng": -4.0}).json()["id"]
    annex_eq = c.post("equipment/", {"name": "Pompe", "site": annex}).json()["id"]
    r1, r2 = c.member("requester"), c.member("requester", sites=[annex])
    mgr = c.member("site_manager", sites=[annex])
    a = c.request(user=r1).json()
    b = c.request(user=c.owner, site=annex).json()
    # un demandeur ne voit que SES demandes
    assert {x["id"] for x in c.get("requests/", user=r1).json()["results"]} == {a["id"]}
    assert c.get(f"requests/{b['id']}/", user=r1).status_code == 404
    # un membre borné à un site ne voit ni ne crée rien ailleurs
    assert {s["id"] for s in c.get("sites/", user=mgr).json()} == {annex}
    assert {e["id"] for e in c.get("equipment/", user=mgr).json()} == {annex_eq}
    assert {x["id"] for x in c.get("requests/", user=mgr).json()["results"]} == {b["id"]}
    assert c.get(f"requests/{a['id']}/", user=mgr).status_code == 404
    assert c.request(user=mgr, site=c.site).status_code == 403
    assert c.request(user=r2, site=c.site).status_code == 403
    assert c.post("equipment/", {"name": "Ailleurs", "site": c.site}, user=mgr).status_code == 403
    assert api(mgr).get(f"/handy/business/equipment/lookup/{c.equipment_code}/").status_code == 404  # QR d'un site hors périmètre


# ---- Demandes, numérotation, SLA ----------------------------------------------------------------------------------

def test_requests_are_numbered_per_organization_and_carry_default_sla():
    a, b = Company("A", "orgg"), Company("B", "orgh")
    r1, r2 = a.request().json(), a.request(priority="urgent").json()
    rb = b.request().json()
    year = timezone.now().year
    assert (r1["number"], r2["number"], rb["number"]) == (f"INT-{year}-0001", f"INT-{year}-0002", f"INT-{year}-0001")
    assert r1["status"] == "approved" and r1["steps"] == []  # aucune règle : validée d'office
    req2 = InterventionRequest.objects.get(pk=r2["id"])
    assert (req2.due_response_at - req2.created_at).total_seconds() == pytest.approx(4 * 3600, abs=5)
    assert (req2.due_resolution_at - req2.created_at).total_seconds() == pytest.approx(24 * 3600, abs=5)
    assert a.request(title="").status_code == 400


def test_a_maintenance_contract_overrides_default_sla_and_marks_its_requests():
    c = Company("Contrat", "contract")
    art = artisan("biz_provider")
    ct = c.post("contracts/", {"name": "Plomberie annuelle", "provider": art.id, "categories": [plomberie().id],
                               "starts_on": str(date.today() - timedelta(days=5)), "sla_response_hours": 6, "sla_resolution_hours": 12})
    assert ct.status_code == 201, ct.content
    r = c.request().json()
    req = InterventionRequest.objects.get(pk=r["id"])
    assert req.contract_id == ct.json()["id"]
    assert (req.due_resolution_at - req.created_at).total_seconds() == pytest.approx(12 * 3600, abs=5)
    other = ServiceCategory.objects.create(name="Électricité", slug="elec2")
    assert InterventionRequest.objects.get(pk=c.request(category=other.id).json()["id"]).contract_id is None
    ghost = _client("biz_not_artisan")  # un compte non éligible ne peut pas être prestataire d'un contrat
    assert c.post("contracts/", {"name": "X", "provider": ghost.id, "starts_on": "2026-01-01"}).status_code == 400


# ---- Validation hiérarchique --------------------------------------------------------------------------------------

def test_amount_and_priority_select_the_rule_and_its_ordered_steps():
    c = Company("Rules", "rules")
    rule(c, ["site_manager", "finance"], name="Gros montant", min_amount="100000", order=1)
    rule(c, ["site_manager"], name="Moyen", min_amount="20000", max_amount="99999", order=2)
    rule(c, ["admin"], name="Urgent", priorities=["urgent"], order=0, max_amount="19999")
    steps = lambda **kw: [s["role"] for s in c.request(**kw).json()["steps"]]  # noqa: E731
    assert steps(estimated_cost="150000") == ["site_manager", "finance"]
    assert steps(estimated_cost="50000") == ["site_manager"]
    assert steps(estimated_cost="5000", priority="urgent") == ["admin"]
    assert steps(estimated_cost="5000") == []  # aucune règle ne couvre : approbation automatique
    assert c.post("approval-rules/", {"name": "Mauvaise", "steps": ["viewer"]}).status_code == 400
    assert c.post("approval-rules/", {"name": "Plafond", "steps": ["admin"], "min_amount": "10", "max_amount": "5"}).status_code == 400


def test_approval_chain_needs_each_role_in_order_and_never_the_requester():
    c = Company("Chain", "chain")
    rule(c, ["site_manager", "finance"], min_amount="1000")
    mgr, fin, req_user, other_mgr = c.member("site_manager"), c.member("finance"), c.member("requester"), c.member("site_manager")
    r = c.request(user=req_user, estimated_cost="5000").json()
    assert r["status"] == "pending_approval"
    decide = lambda user, approve=True, comment="": c.post(f"requests/{r['id']}/decide/", {"approve": approve, "comment": comment}, user=user)  # noqa: E731
    assert decide(req_user).status_code == 403                  # le demandeur ne valide pas sa propre demande
    assert c.get(f"requests/{r['id']}/", user=mgr).json()["can_decide"] is True
    assert c.get(f"requests/{r['id']}/", user=fin).json()["can_decide"] is False  # pas son tour
    assert decide(fin).status_code == 403                       # la finance ne saute pas l'étape du responsable
    assert decide(mgr).status_code == 200
    mid = c.get(f"requests/{r['id']}/", user=fin).json()
    assert mid["status"] == "pending_approval" and [s["status"] for s in mid["steps"]] == ["approved", "pending"]
    assert decide(mgr).status_code == 403                       # l'étape 2 appartient à la finance
    done = decide(fin).json()
    assert done["status"] == "approved"
    assert decide(fin).status_code == 409                       # plus rien à valider
    assert Notification.objects.filter(user=req_user, notification_type="business_update", message__contains="validée").exists()
    assert AuditEvent.objects.filter(action="request.approved", organization_id=c.id).count() == 2


def test_rejection_stops_the_chain_with_a_reason_and_owner_can_override_a_step():
    c = Company("Reject", "reject")
    rule(c, ["finance"], min_amount="1")
    req_user = c.member("requester")
    r = c.request(user=req_user, estimated_cost="100").json()
    res = c.post(f"requests/{r['id']}/decide/", {"approve": False, "comment": "Hors budget"}).json()  # propriétaire : dérogation
    assert res["status"] == "rejected" and res["rejection_reason"] == "Hors budget"
    assert Notification.objects.filter(user=req_user, message__contains="refusée").exists()
    assert AuditEvent.objects.filter(action="request.rejected", data__override=True).exists()
    r2 = c.request(user=req_user, estimated_cost="100").json()
    assert c.post(f"requests/{r2['id']}/decide/", {"approve": "oui"}, user=c.owner).status_code == 400


def test_the_requester_can_cancel_a_pending_request_but_not_someone_elses():
    c = Company("Cancel", "cancel")
    rule(c, ["admin"], min_amount="1")
    u1, u2 = c.member("requester"), c.member("requester")
    r = c.request(user=u1, estimated_cost="10").json()
    assert c.post(f"requests/{r['id']}/cancel/", user=u2).status_code in (403, 404)
    assert c.post(f"requests/{r['id']}/cancel/", user=u1).json()["status"] == "cancelled"
    assert c.post(f"requests/{r['id']}/cancel/", user=u1).status_code == 409


# ---- Affectation intelligente --------------------------------------------------------------------------------------------

def test_only_eligible_artisans_are_suggested_ranked_and_explained():
    c = Company("Dispatch", "dispatch")
    near, far = artisan("biz_near", online=True), artisan("biz_far")
    Point_far = Point(-3.5, 6.0, srid=4326)
    far.handyman_profile.location = Point_far
    far.handyman_profile.save()
    ineligible = artisan("biz_inelig", eligible=False, online=True)
    suspended = artisan("biz_susp", online=True)
    suspended.is_active = False
    suspended.save()
    on_leave = artisan("biz_leave", online=True)
    TimeOff.objects.create(handyman=on_leave.handyman_profile, start=timezone.now() - timedelta(hours=1), end=timezone.now() + timedelta(hours=5))
    r = c.request().json()
    sugg = c.get(f"requests/{r['id']}/suggestions/").json()["results"]
    ids = [s["user_id"] for s in sugg]
    assert near.id in ids and far.id in ids
    assert ineligible.id not in ids and suspended.id not in ids and on_leave.id not in ids
    assert ids.index(near.id) < ids.index(far.id)               # plus proche et en ligne
    top = sugg[0]
    assert top["distance_km"] is not None and any("km" in x for x in top["reasons"]) and "En ligne" in top["reasons"]
    assert api(_client("biz_req_only")).get(c.url(f"requests/{r['id']}/suggestions/")).status_code == 404
    assert c.get(f"requests/{r['id']}/suggestions/", user=c.member("requester")).status_code == 403


def test_contract_provider_comes_first_and_the_requester_never_assigns_themselves():
    c = Company("Prio", "prio")
    star, provider = artisan("biz_star", online=True), artisan("biz_prov")
    star.handyman_profile.rating = 5
    star.handyman_profile.save()
    c.post("contracts/", {"name": "Attitré", "provider": provider.id, "starts_on": str(date.today() - timedelta(days=1))})
    r = c.request().json()
    sugg = c.get(f"requests/{r['id']}/suggestions/").json()["results"]
    assert sugg[0]["user_id"] == provider.id and "contrat" in sugg[0]["reasons"][0]
    # un compte à la fois artisan éligible et demandeur n'est jamais proposé pour SA propre demande
    mixed = artisan("biz_mixed", online=True)
    code = c.post("invitations/", {"role": "requester"}).json()["code"]
    api(mixed).post("/handy/business/join/", {"code": code}, format="json")
    mine = c.request(user=mixed).json()
    assert mixed.id not in [s["user_id"] for s in c.get(f"requests/{mine['id']}/suggestions/").json()["results"]]


def test_dispatch_creates_a_real_booking_for_an_eligible_artisan_only():
    c = Company("Book", "book")
    art, bad = artisan("biz_book_art", online=True), artisan("biz_book_bad", eligible=False)
    service(art, "Plomberie")
    req = c.member("requester")
    r = c.request(user=req, estimated_cost="25000", title="Chauffe-eau HS").json()
    assert c.post(f"requests/{r['id']}/dispatch/", {"artisan": art.id}, user=req).status_code == 403   # pas son rôle
    assert c.post(f"requests/{r['id']}/dispatch/", {"artisan": bad.id}).status_code == 400
    assert c.post(f"requests/{r['id']}/dispatch/", {}).status_code == 400
    res = c.post(f"requests/{r['id']}/dispatch/", {"artisan": art.id})
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["status"] == "dispatched" and body["booking_id"]
    b = Booking.objects.get(pk=body["booking_id"])
    assert (b.client_id, b.handyman_id, b.status) == (req.id, art.id, "pending")
    assert b.job_location.y == pytest.approx(ABIDJAN[0]) and "Chauffe-eau HS" in b.description and r["number"] in b.description
    assert Notification.objects.filter(user=art, notification_type="booking_request", message__contains=r["number"]).exists()
    assert c.post(f"requests/{r['id']}/dispatch/", {"artisan": art.id}).status_code == 409           # déjà affectée
    rule(c, ["admin"], min_amount="1")
    pending = c.request(user=req, estimated_cost="5").json()
    assert c.post(f"requests/{pending['id']}/dispatch/", {"auto": True}).status_code == 409          # pas encore validée


def test_auto_dispatch_picks_the_top_candidate_and_fails_cleanly_without_any():
    c = Company("Auto", "auto")
    r = c.request().json()
    res = c.post(f"requests/{r['id']}/dispatch/", {"auto": True})
    assert res.status_code == 409 and res.json()["code"] == "no_candidate"
    best = artisan("biz_auto_best", online=True)
    artisan("biz_auto_other")
    r2 = c.request().json()
    out = c.post(f"requests/{r2['id']}/dispatch/", {"auto": True}).json()
    assert Booking.objects.get(pk=out["booking_id"]).handyman_id == best.id


# ---- Cycle de vie, SLA, coûts -------------------------------------------------------------------------------------------------

def _dispatched(company, **extra):
    art = artisan(f"biz_cycle_{company.prefix}", online=True)
    r = company.request(estimated_cost="30000", **extra).json()
    body = company.post(f"requests/{r['id']}/dispatch/", {"artisan": art.id}).json()
    return art, Booking.objects.get(pk=body["booking_id"]), r["id"]


def test_the_request_follows_its_booking_and_records_response_time_and_cost():
    c = Company("Cycle", "cycle")
    art, b, rid = _dispatched(c)
    get = lambda: c.get(f"requests/{rid}/").json()  # noqa: E731
    b.transition_to("confirmed")
    assert get()["status"] == "scheduled"
    assert InterventionRequest.objects.get(pk=rid).responded_at is not None
    b.refresh_from_db()
    b.transition_to("in_progress")
    assert get()["status"] == "in_progress"
    b.transition_to("completed")
    done = get()
    assert done["status"] == "completed" and Decimal(done["cost"]) == Decimal("30000.00")   # montant convenu de la réservation
    assert done["sla"]["response_met"] is True and done["sla"]["resolution_met"] is True
    assert InterventionRequest.objects.get(pk=rid).final_cost == Decimal("30000.00")


def test_a_cancelled_mission_returns_to_the_dispatch_queue_and_managers_are_told():
    c = Company("Cancel2", "cancel2")
    art, b, rid = _dispatched(c)
    b.transition_to("cancelled")
    req = InterventionRequest.objects.get(pk=rid)
    assert req.status == "approved" and req.booking_id is None
    assert Notification.objects.filter(user=c.owner, message__contains="à réaffecter").exists()
    assert c.post(f"requests/{rid}/dispatch/", {"artisan": art.id}).status_code == 200      # réaffectable


def test_sla_breach_is_measured_not_assumed():
    c = Company("Sla", "sla")
    art, b, rid = _dispatched(c)
    InterventionRequest.objects.filter(pk=rid).update(due_response_at=timezone.now() - timedelta(hours=1), due_resolution_at=timezone.now() - timedelta(minutes=1))
    b.transition_to("confirmed")
    b.refresh_from_db()
    b.transition_to("in_progress")
    b.transition_to("completed")
    sla = c.get(f"requests/{rid}/").json()["sla"]
    assert sla["response_met"] is False and sla["resolution_met"] is False


# ---- Budgets, facturation, préventif, KPI ---------------------------------------------------------------------------------------

def _complete(company, cost, *, site=None, equipment=None, name=None):
    art = artisan(name or f"biz_done_{company.prefix}_{InterventionRequest.objects.count()}", online=True)
    extra = {}
    if site:
        extra["site"] = site
    if equipment:
        extra["equipment"] = equipment
    r = company.request(estimated_cost=str(cost), **extra).json()
    body = company.post(f"requests/{r['id']}/dispatch/", {"artisan": art.id}).json()
    b = Booking.objects.get(pk=body["booking_id"])
    for st in ("confirmed", "in_progress", "completed"):
        b.refresh_from_db()
        b.transition_to(st)
    return r["id"]


def test_budgets_measure_real_spending_per_site_and_equipment():
    c = Company("Budget", "budget")
    annex = c.post("sites/", {"name": "Annexe"}).json()["id"]
    today = date.today()
    period = {"period_start": str(today - timedelta(days=30)), "period_end": str(today + timedelta(days=30))}
    org_b = c.post("budgets/", {"name": "Global", "amount": "100000", **period}).json()
    site_b = c.post("budgets/", {"name": "Annexe", "amount": "20000", "site": annex, "alert_threshold_pct": 70, **period}).json()
    eq_b = c.post("budgets/", {"name": "Clim", "amount": "30000", "equipment": c.equipment, **period}).json()
    _complete(c, 25000, equipment=c.equipment)
    _complete(c, 15000, site=annex)
    by = {b["name"]: b["status"] for b in c.get("budgets/").json()}
    assert Decimal(by["Global"]["spent"]) == Decimal("40000") and by["Global"]["level"] == "ok"
    assert Decimal(by["Annexe"]["spent"]) == Decimal("15000") and by["Annexe"]["level"] == "warning"   # 75 % ≥ seuil d'alerte de 70 %
    assert Decimal(by["Clim"]["spent"]) == Decimal("25000") and by["Clim"]["percent"] == pytest.approx(83.3, abs=0.1)
    # une demande qui ferait dépasser un budget est signalée aux validateurs
    rule(c, ["admin"], min_amount="1")
    warn = c.request(estimated_cost="10000", site=annex).json()
    assert [w["name"] for w in warn["budget_warnings"]] == ["Annexe"]
    assert org_b["id"] and site_b["id"] and eq_b["id"]


def test_consolidated_invoice_bills_each_intervention_once_with_real_amounts():
    c = Company("Invoice", "invoice")
    fin = c.member("finance")
    _complete(c, 12000)
    _complete(c, 8000)
    today = date.today()
    body = {"start": str(today - timedelta(days=1)), "end": str(today + timedelta(days=1))}
    assert c.post("invoices/generate/", body, user=c.member("requester")).status_code == 403
    inv = c.post("invoices/generate/", body, user=fin)
    assert inv.status_code == 201, inv.content
    data = inv.json()
    assert Decimal(data["total"]) == Decimal("20000.00") and len(data["lines"]) == 2 and data["number"].startswith("FAC-")
    assert c.post("invoices/generate/", body, user=fin).status_code == 409           # rien de nouveau : jamais deux fois
    _complete(c, 5000)
    second = c.post("invoices/generate/", body, user=fin).json()
    assert len(second["lines"]) == 1 and second["number"] != data["number"]
    csv = c.get(f"invoices/{data['id']}/export.csv", user=fin)
    assert csv.status_code == 200 and "TOTAL" in csv.content.decode() and csv["Content-Disposition"].startswith("attachment")
    assert api(Company("Other", "inv2").owner).get(c.url(f"invoices/{data['id']}/")).status_code == 404
    assert c.post("invoices/generate/", {"start": "2026-02-01", "end": "2026-01-01"}, user=fin).status_code == 400


def test_unpriced_interventions_are_never_invoiced_at_zero():
    c = Company("Unpriced", "unpriced")
    art = artisan("biz_unpriced", online=True)
    r = c.request().json()  # sans coût estimé ni montant convenu
    b = Booking.objects.get(pk=c.post(f"requests/{r['id']}/dispatch/", {"artisan": art.id}).json()["booking_id"])
    for st in ("confirmed", "in_progress", "completed"):
        b.refresh_from_db()
        b.transition_to(st)
    today = date.today()
    out = c.post("invoices/generate/", {"start": str(today), "end": str(today)})
    assert out.status_code == 409 and "sans montant" in out.json()["detail"]
    assert c.get("dashboard/").json()["spend"]["unpriced_interventions"] == 1


def test_preventive_plans_create_requests_once_per_due_date_and_reschedule_after_completion():
    c = Company("Prev", "prev")
    manager = c.member("site_manager")
    today = date.today()
    plan = c.post("preventive-plans/", {"equipment": c.equipment, "title": "Entretien clim", "frequency_days": 90,
                                        "next_due_on": str(today + timedelta(days=5)), "lead_days": 7}, user=manager)
    assert plan.status_code == 201, plan.content
    late = c.post("preventive-plans/", {"equipment": c.equipment, "title": "Plus tard", "frequency_days": 30,
                                        "next_due_on": str(today + timedelta(days=60)), "lead_days": 7}).json()
    assert services.run_preventive() == 1
    assert services.run_preventive() == 0                       # idempotent : une demande par échéance
    req = InterventionRequest.objects.get(source="preventive")
    assert req.equipment_id == c.equipment and "Entretien clim" in req.title and req.preventive_plan_id == plan.json()["id"]
    assert Notification.objects.filter(user=manager, notification_type="business_reminder").exists()
    assert not InterventionRequest.objects.filter(preventive_plan_id=late["id"]).exists()
    # l'intervention terminée reprogramme l'échéance
    art = artisan("biz_prev_art", online=True)
    b = Booking.objects.get(pk=c.post(f"requests/{req.id}/dispatch/", {"artisan": art.id}).json()["booking_id"])
    for st in ("confirmed", "in_progress", "completed"):
        b.refresh_from_db()
        b.transition_to(st)
    p = PreventivePlan.objects.get(pk=plan.json()["id"])
    assert p.last_done_on == today and p.next_due_on == today + timedelta(days=90)
    Equipment.objects.filter(pk=c.equipment).update(status="retired")
    PreventivePlan.objects.filter(pk=p.pk).update(next_due_on=today)
    assert services.run_preventive() == 0                       # équipement retiré : plus de maintenance


def test_dashboard_kpis_are_real_and_scoped_to_the_viewer():
    c = Company("Kpi", "kpi")
    annex = c.post("sites/", {"name": "Annexe", "lat": 5.4, "lng": -4.0}).json()["id"]
    _complete(c, 10000)
    _complete(c, 30000, site=annex)
    open_req = c.request(priority="urgent").json()
    InterventionRequest.objects.filter(pk=open_req["id"]).update(due_resolution_at=timezone.now() - timedelta(hours=1))
    d = c.get("dashboard/").json()
    assert d["requests"]["completed"] == 2 and d["requests"]["open"] == 1 and d["requests"]["overdue"] == 1
    assert Decimal(d["spend"]["total"]) == Decimal("40000") and {x["name"] for x in d["spend"]["by_site"]} == {"Siège", "Annexe"}
    assert d["sla"]["resolution"] == {"met": 2, "measured": 2, "rate": 1.0}
    assert d["durations"]["avg_resolution_hours"] is not None
    mgr = c.member("site_manager", sites=[annex])
    scoped = c.get("dashboard/", user=mgr).json()
    assert scoped["requests"]["completed"] == 1 and Decimal(scoped["spend"]["total"]) == Decimal("30000")
    assert {x["name"] for x in scoped["spend"]["by_site"]} == {"Annexe"}


def test_csv_report_neutralises_spreadsheet_formulas_and_respects_scope():
    c = Company("Csv", "csv")
    c.request(title='=HYPERLINK("http://evil","clic")')
    r = c.get("reports/requests.csv")
    text = r.content.decode()
    assert r.status_code == 200 and "'=HYPERLINK" in text and ";=HYPERLINK" not in text
    assert c.get("reports/requests.csv", user=c.member("requester")).status_code == 403


def test_audit_log_records_who_did_what_and_stays_inside_the_organization():
    c = Company("Audit", "audit")
    other = Company("Autre", "audit2")
    r = c.request().json()
    other.request()
    log = c.get("audit/").json()
    actions = [e["action"] for e in log]
    assert "organization.created" in actions and "request.created" in actions and "site.created" in actions
    assert all(e["actor"] for e in log)
    assert not any(e["detail"].get("number") == "INT-0001" for e in log)
    assert {e["target_id"] for e in log if e["target_type"] == "interventionrequest"} == {r["id"]}


# ---- Matrices exhaustives : organisations et rôles ------------------------------------------------------------------------

def _endpoints(c, req_id, member_id, invitation_id, rule_id, contract_id, plan_id, budget_id, invoice_id):
    """(méthode, chemin, capacité requise, charge utile) pour TOUTES les routes d'une organisation."""
    site, eq = c.site, c.equipment
    ok_request = {"site": site, "title": "Matrice", "priority": "low"}
    return [
        ("get", "", "view.structure", None), ("patch", "", "org.manage", {"name": "Renommée"}),
        ("get", "sites/", "view.structure", None), ("post", "sites/", "sites.manage", {"name": "Site matrice"}),
        ("get", f"sites/{site}/", "view.structure", None), ("patch", f"sites/{site}/", "sites.manage", {"notes": "x"}),
        ("get", "buildings/", "view.structure", None), ("post", "buildings/", "sites.manage", {"site": site, "name": "Bât M"}),
        ("get", "equipment/", "view.structure", None), ("post", "equipment/", "equipment.manage", {"site": site, "name": "Eq M"}),
        ("get", f"equipment/{eq}/", "view.structure", None), ("patch", f"equipment/{eq}/", "equipment.manage", {"notes": "x"}),
        ("get", f"equipment/{eq}/qr.png", "view.structure", None),
        ("get", "members/", "members.manage", None), ("patch", f"members/{member_id}/", "members.manage", {"role": "viewer"}),
        ("get", "invitations/", "members.manage", None), ("post", "invitations/", "members.manage", {"role": "viewer"}),
        ("delete", f"invitations/{invitation_id}/", "members.manage", None),
        ("get", "approval-rules/", "approval_rules.manage", None), ("post", "approval-rules/", "approval_rules.manage", {"name": "R", "steps": ["admin"]}),
        ("patch", f"approval-rules/{rule_id}/", "approval_rules.manage", {"is_active": True}),
        ("get", "contracts/", "view.structure", None), ("post", "contracts/", "contracts.manage", {"name": "C", "starts_on": "2026-01-01"}),
        ("patch", f"contracts/{contract_id}/", "contracts.manage", {"notes": "x"}),
        ("get", "preventive-plans/", "view.structure", None),
        ("post", "preventive-plans/", "preventive.manage", {"equipment": eq, "title": "P", "frequency_days": 30, "next_due_on": "2030-01-01"}),
        ("patch", f"preventive-plans/{plan_id}/", "preventive.manage", {"title": "P2"}), ("post", "preventive-plans/run/", "preventive.manage", None),
        ("get", "budgets/", "reports.view", None), ("post", "budgets/", "budgets.manage", {"name": "B", "period_start": "2026-01-01", "period_end": "2026-12-31", "amount": "1"}),
        ("patch", f"budgets/{budget_id}/", "budgets.manage", {"name": "B2"}),
        ("get", "invoices/", "invoices.manage", None), ("get", f"invoices/{invoice_id}/", "invoices.manage", None),
        ("get", f"invoices/{invoice_id}/export.csv", "invoices.manage", None),
        ("post", "invoices/generate/", "invoices.manage", {"start": "2026-01-01", "end": "2026-01-02"}),
        ("get", "dashboard/", "reports.view", None), ("get", "reports/requests.csv", "reports.view", None), ("get", "audit/", "audit.view", None),
        ("post", "requests/", "requests.create", ok_request),
        ("get", f"requests/{req_id}/suggestions/", "requests.dispatch", None), ("post", f"requests/{req_id}/dispatch/", "requests.dispatch", {}),
        ("post", f"requests/{req_id}/decide/", "requests.approve", {"approve": True}),
    ]


def _fixture_org(prefix):
    from business.models import ConsolidatedInvoice
    c = Company(prefix.title(), prefix)
    viewer = c.member("viewer")
    member_id = Membership.objects.get(organization_id=c.id, user=viewer).id
    inv = c.post("invitations/", {"role": "viewer"}).json()["id"]
    rule_id = c.post("approval-rules/", {"name": "R0", "steps": ["admin"], "min_amount": "999999999"}).json()["id"]
    contract = c.post("contracts/", {"name": "C0", "starts_on": "2026-01-01"}).json()["id"]
    plan = c.post("preventive-plans/", {"equipment": c.equipment, "title": "P0", "frequency_days": 30, "next_due_on": "2030-01-01"}).json()["id"]
    budget = c.post("budgets/", {"name": "B0", "period_start": "2026-01-01", "period_end": "2026-12-31", "amount": "1"}).json()["id"]
    org = Organization.objects.get(pk=c.id)
    invoice = ConsolidatedInvoice.objects.create(organization=org, number="FAC-TEST-001", period_start="2026-01-01", period_end="2026-01-02")
    req = c.request().json()["id"]
    return c, dict(req_id=req, member_id=member_id, invitation_id=inv, rule_id=rule_id, contract_id=contract, plan_id=plan, budget_id=budget, invoice_id=invoice.id)


def _call(user, c, method, path, payload):
    client = api(user)
    kw = {"format": "json"} if payload is not None else {}
    return getattr(client, method)(c.url(path), payload, **kw) if method in ("post", "patch") else getattr(client, method)(c.url(path))


def test_every_route_of_an_organization_is_invisible_to_other_organizations_and_non_members():
    a, ids = _fixture_org("matrixa")
    b = Company("B", "matrixb")
    stranger = _client("matrix_stranger")
    before = (Site.objects.count(), InterventionRequest.objects.count(), Membership.objects.count())
    for method, path, _cap, payload in _endpoints(a, **ids):
        for who, label in ((b.owner, "propriétaire d'une autre organisation"), (stranger, "compte sans organisation")):
            r = _call(who, a, method, path, payload)
            assert r.status_code == 404, f"{method.upper()} {path} ({label}) → {r.status_code}"
        assert _call(None, a, method, path, payload).status_code == 401, f"{method.upper()} {path} (anonyme)"
    assert (Site.objects.count(), InterventionRequest.objects.count(), Membership.objects.count()) == before   # rien n'a été écrit
    assert Organization.objects.get(pk=a.id).name == "Matrixa"


@pytest.mark.parametrize("role", ["admin", "site_manager", "approver", "requester", "finance", "viewer"])
def test_every_route_enforces_exactly_the_capabilities_of_the_role(role):
    from business import rbac
    c, ids = _fixture_org(f"caps{role}".replace("_", ""))
    user = c.member(role)
    caps = rbac.ROLE_CAPS[role]
    for method, path, cap, payload in _endpoints(c, **ids):
        r = _call(user, c, method, path, payload)
        if cap in caps:
            assert r.status_code not in (401, 403, 404) or (r.status_code == 404 and method == "delete"), f"{role}: {method.upper()} {path} refusé alors que « {cap} » est accordée → {r.status_code}"
        else:
            assert r.status_code == 403, f"{role}: {method.upper()} {path} aurait dû être refusé (« {cap} ») → {r.status_code}"
        if method == "patch" and path == "":  # ne renomme pas pour de bon l'organisation pour les rôles suivants
            Organization.objects.filter(pk=c.id).update(name=c.prefix)
