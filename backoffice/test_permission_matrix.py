"""Matrice de permissions KYC, Business et engagements : balayage systématique de TOUS les points d'accès de ces domaines
(énumérés depuis les routes, pas depuis une liste écrite à la main) — anonyme, compte sans lien, lecteur seul, rôle Back-Office sans le droit."""
import re
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.schemas.generators import EndpointEnumerator
from rest_framework.test import APIClient

from backoffice import rbac
from business import services as business
from business.models import Membership, Role
from engagements import tasks
from engagements.models import ContractInstallment, EngagementApplication, EngagementEvaluation, ScheduleEvent
from engagements.services import contracts as contract_svc
from engagements.services import evaluations as eval_svc
from engagements.services import installments as inst_svc
from engagements.services import planning, postings
from engagements.testing import WEEK, category, make_contract, person, pro
from handy.models import HandymanDocument

User = get_user_model()
pytestmark = pytest.mark.django_db
WRITE = ("POST", "PUT", "PATCH", "DELETE")
PATH_VALUES = {"code": "x", "kind": "payment", "key": "default", "op": "hide", "provider": "om", "token": "x"}


def endpoints(*prefixes):
    seen = []
    for path, method, _cb in EndpointEnumerator().get_api_endpoints():
        if method in ("HEAD", "OPTIONS") or not any(path.startswith(p) for p in prefixes):
            continue
        seen.append((path, method))
    return sorted(set(seen))


def fill(path, ids=None):
    ids = ids or {}

    def sub(m):
        name = m.group(1)
        return str(ids.get(name) or PATH_VALUES.get(name) or 1)

    return re.sub(r"\{(\w+)\}", sub, path)


def call(client, method, path):
    return client.generic(method, path, data="{}", content_type="application/json")


ENGAGEMENTS = "/handy/engagements/"
BUSINESS = ("/handy/business/",)
KYC = ("/handy/handyman-docs/", "/handy/backoffice/kyc/")
BO_DOMAINS = ("/handy/backoffice/kyc/", "/handy/backoffice/business/", "/handy/backoffice/engagements/")


def test_the_enumeration_really_covers_the_three_domains():
    assert len(endpoints(ENGAGEMENTS)) >= 60 and len(endpoints(*BUSINESS)) >= 40 and len(endpoints(*KYC)) >= 8
    assert len(endpoints(*BO_DOMAINS)) >= 25


@pytest.mark.parametrize("prefixes", [(ENGAGEMENTS,), BUSINESS, KYC, BO_DOMAINS], ids=["engagements", "business", "kyc", "backoffice"])
def test_every_endpoint_of_the_domain_refuses_an_anonymous_caller(prefixes):
    client = APIClient()
    leaks = []
    for path, method in endpoints(*prefixes):
        status = call(client, method, fill(path)).status_code
        if status not in (401, 403, 405):
            leaks.append((method, path, status))
    assert leaks == []


def test_an_unrelated_verified_account_reaches_none_of_the_private_data_of_engagements():
    owner, worker, stranger, sub = person("mx_owner"), pro("mx_worker"), person("mx_stranger"), pro("mx_sub")
    today = timezone.localdate()
    c = make_contract(owner, worker, start=today, today=today, months=12, schedule=WEEK)
    tasks.run(today)
    inst = c.installments.first()
    pay = inst_svc.declare_payment(inst, owner, {"amount": "1000", "method": "cash", "paid_on": today.isoformat()}, today=today)
    line = inst_svc.propose_line(inst, owner, {"kind": "bonus", "amount": "500", "description": "Prime de test"})
    ev = c.schedule_events.filter(kind="shift").first()
    am = contract_svc.propose_amendment(c, owner, {"kind": "change", "changes": {"notice_period_days": 10}, "reason": "Test de la matrice"}, today=today)
    evaluation = eval_svc.create(c, owner, {"kind": "periodic", "rating": 5, "comment": "Très bien."}, today=today + timedelta(days=40))
    posting = postings.publish(postings.create_posting(owner, {"category": category().pk, "title": "Gardien de nuit", "description": "Surveillance de la résidence la nuit.", "mission_type": "long_term",
                                                               "work_relationship": "independent", "city": "Abidjan", "amount": "180000", "period": "monthly"}, today=today), owner)
    app = postings.apply(posting, worker, {"message": "Candidat"})
    interview = postings.propose_interview(app, owner, {"scheduled_at": (timezone.now() + timedelta(days=3)).isoformat(), "mode": "phone"})
    ids = {"contracts": c.pk, "installments": inst.pk, "payments": pay.pk, "lines": line.pk, "events": ev.pk, "amendments": am.pk, "evaluations": evaluation.pk,
           "postings": posting.pk, "applications": app.pk, "interviews": interview.pk}

    def resolve(path):
        # `{id}`/`{pk}` désigne la ressource nommée juste avant dans le chemin (contracts/{id}/…, installments/{id}/…).
        parts = path.split("/")
        out = {}
        for i, part in enumerate(parts):
            if part in ("{id}", "{pk}") and i > 0 and parts[i - 1] in ids:
                out[part.strip("{}")] = ids[parts[i - 1]]
        return out

    stranger_client = APIClient()
    stranger_client.force_authenticate(stranger)
    leaked = []
    for path, method in endpoints(ENGAGEMENTS):
        # Ouverts PAR CONCEPTION à tout compte connecté : règles, recherche de professionnels vérifiés, offres ouvertes (lecture) et candidature
        # (refusée 409 sans profil vérifié), modèles de contrat VALIDÉS (aucune donnée privée). Les listes personnelles (dont les invitations)
        # renvoient une page vide pour un tiers (vérifié plus bas).
        if (path.endswith("/rules/") or "/me/" in path or path.endswith("/workers/")
                or (method == "GET" and path.endswith(("/postings/", "/postings/{pk}/", "/contracts/", "/postings/mine/", "/applications/mine/",
                                                       "/invitations/mine/", "/engagements/templates/")))
                or (method == "POST" and path.endswith("/postings/{pk}/apply/"))):
            continue
        if "{kind}" in path:
            url = fill(path, {**resolve(path), "kind": "payment", "pk": pay.pk})
        else:
            url = fill(path, resolve(path))
        r = call(stranger_client, method, url)
        if r.status_code not in (400, 403, 404, 405):
            leaked.append((method, url, r.status_code))
    assert leaked == [], leaked
    # Les listes personnelles d'un compte sans lien sont vides.
    for url in ("contracts/", "postings/mine/", "applications/mine/", "me/replacements/"):
        data = stranger_client.get(ENGAGEMENTS + url).json()
        assert data["count"] == 0, url
    assert stranger_client.get(ENGAGEMENTS + "me/overview/").json()["todo"] == []
    assert stranger_client.get(ENGAGEMENTS + "invitations/mine/").json()["results"] == []
    # Un tiers ne lit pas non plus les pièces d'un paiement ; le remplaçant désigné ne voit que SES remplacements.
    sub_client = APIClient()
    sub_client.force_authenticate(sub)
    assert sub_client.get(ENGAGEMENTS + f"contracts/{c.pk}/").status_code == 404
    assert sub_client.get(ENGAGEMENTS + f"contracts/{c.pk}/installments/").status_code == 404


def test_business_organisation_data_is_invisible_to_outsiders_and_read_only_members_can_never_write():
    boss, outsider, viewer = person("bz_boss"), person("bz_out"), person("bz_viewer")
    org = business.create_organization(boss, name="Hôtel Ivoire", city="Abidjan")
    Membership.objects.create(organization=org, user=viewer, role=Role.VIEWER)
    other_boss = person("bz_boss2")
    business.create_organization(other_boss, name="Autre société", city="Abidjan")
    ids = {"org_id": org.pk}
    out_client, viewer_client = APIClient(), APIClient()
    out_client.force_authenticate(outsider)
    viewer_client.force_authenticate(viewer)
    org_routes = [(p, m) for p, m in endpoints(*BUSINESS) if "{org_id}" in p]
    assert len(org_routes) >= 35
    leaked, writes = [], []
    for path, method in org_routes:
        url = fill(path, ids)
        r = call(out_client, method, url)
        if r.status_code not in (400, 403, 404, 405):
            leaked.append((method, url, r.status_code))
        if method in WRITE:
            w = call(viewer_client, method, url)
            if w.status_code not in (400, 403, 404, 405):
                writes.append((method, url, w.status_code))
    assert leaked == [] and writes == []
    # Un compte d'une autre organisation n'est pas non plus membre de celle-ci.
    other_client = APIClient()
    other_client.force_authenticate(other_boss)
    assert other_client.get(f"/handy/business/orgs/{org.pk}/").status_code in (403, 404)


def test_kyc_documents_belong_to_their_owner_and_never_to_staff_without_the_review_right():
    artisan, other = pro("kc_owner"), pro("kc_other")
    doc = HandymanDocument.objects.filter(handyman=artisan.handyman_profile).first()
    if doc is None:
        from django.core.files.base import ContentFile

        doc = HandymanDocument.objects.create(handyman=artisan.handyman_profile, document_type="id_card", status="pending")
        doc.file.save("id.pdf", ContentFile(b"%PDF-1.4\n% test"), save=True)
    owner_client, other_client = APIClient(), APIClient()
    owner_client.force_authenticate(artisan)
    other_client.force_authenticate(other)
    assert other_client.get(f"/handy/handyman-docs/{doc.pk}/").status_code in (403, 404)
    for path, method in endpoints("/handy/handyman-docs/"):
        if "{id}" in path or "{pk}" in path:
            assert call(other_client, method, fill(path, {"id": doc.pk, "pk": doc.pk})).status_code in (400, 403, 404, 405), (method, path)
    listing = other_client.get("/handy/handyman-docs/").json()
    rows = listing["results"] if isinstance(listing, dict) else listing
    assert doc.pk not in [r["id"] for r in rows]
    # Personnel avec un rôle sans droit KYC : refusé sur l'ancienne API comme sur le Back-Office.
    rbac.ensure_roles()
    marketing = User.objects.create_user("kc_mkt", "kc_mkt@x.test", "pass1234", is_staff=True)
    marketing.groups.add(Group.objects.get(name=rbac.role_group_name("marketing")))
    mkt = APIClient()
    mkt.force_authenticate(marketing)
    assert mkt.get(f"/handy/handyman-docs/{doc.pk}/").status_code in (403, 404)
    assert mkt.get("/handy/backoffice/kyc/").status_code == 403


def _declared_permission(view_cls, method):
    spec = getattr(view_cls, "bo_permission", None)
    if isinstance(spec, dict):
        return spec.get(method) or spec.get("*")
    return spec


def test_back_office_roles_get_exactly_the_rights_they_declare_on_kyc_business_and_engagements():
    """Pour chaque point d'accès et chaque rôle : refus (403) si le rôle n'a pas le droit déclaré par la vue, jamais un refus si le droit existe."""
    rbac.ensure_roles()
    clients = {}
    for role in rbac.ROLES:
        u = User.objects.create_user(f"rm_{role}", f"rm_{role}@x.test", "pass1234", is_staff=True)
        u.groups.add(Group.objects.get(name=rbac.role_group_name(role)))
        clients[role] = APIClient()
        clients[role].force_authenticate(u)
    enumerator = EndpointEnumerator()
    checked = 0
    wrong = []
    for path, method, cb in enumerator.get_api_endpoints():
        if not any(path.startswith(p) for p in BO_DOMAINS):
            continue
        cls = getattr(cb, "cls", None) or getattr(cb, "view_class", None)
        needed = _declared_permission(cls, method)
        assert needed, (path, method)                                  # aucun point d'accès sans droit déclaré
        url = fill(path)
        for role, perms in rbac.ROLES.items():
            status = call(clients[role], method, url).status_code
            allowed = needed in perms
            if (not allowed and status != 403) or (allowed and status == 403):
                wrong.append((role, method, path, needed, status))
            checked += 1
    assert checked > 150 and wrong == []
