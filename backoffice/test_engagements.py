"""Back-Office « Engagements » : droits par rôle, contrats, décisions motivées, litiges, modération, règles bornées, commission,
tableau de bord réel, exports sûrs — et aucune donnée sensible exposée."""
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from backoffice import rbac
from engagements import tasks
from engagements.models import ContractInstallment, EngagementDispute, EngagementEvaluation, EngagementPosting, EngagementRule, EvaluationReport
from engagements.services import contracts as contract_svc
from engagements.services import disputes as dispute_svc
from engagements.services import evaluations as eval_svc
from engagements.services import installments as inst_svc
from engagements.services import postings as posting_svc
from engagements.testing import WEEK, category, make_contract, person as eng_person, pro
from handy.models import Notification
from trust.models import AuditEvent

User = get_user_model()
pytestmark = pytest.mark.django_db
BO = "/handy/backoffice/engagements"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


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


def world():
    today = timezone.localdate()
    owner, worker = eng_person("bo_owner"), pro("bo_worker")
    c = make_contract(owner, worker, start=today, today=today, months=12, schedule=WEEK)
    tasks.run(today)
    return owner, worker, c, today


def test_rights_by_role_and_every_endpoint_refuses_anonymous_and_non_staff():
    owner, worker, c, today = world()
    paths = ["", "contracts/", f"contracts/{c.pk}/", "postings/", "installments/", "disputes/", "evaluations/", "rules/"]
    for path in paths:
        assert api().get(f"{BO}/{path}").status_code in (401, 403), path
        assert api(owner).get(f"{BO}/{path}").status_code == 403, path                                # un compte ordinaire n'entre pas
    for role, expected in (("ops", 200), ("support", 200), ("finance", 200), ("marketing", 403), ("analyst", 403)):
        u = staff(f"r_{role}", role)
        assert api(u).get(f"{BO}/contracts/").status_code == expected, role
    mods = api(staff("r_ops2", "ops")).get("/handy/backoffice/me/").json()["modules"]
    assert "engagements" in [m["id"] for m in mods]
    assert "engagements" not in [m["id"] for m in api(staff("r_mkt2", "marketing")).get("/handy/backoffice/me/").json()["modules"]]
    # Écritures : support/ops oui ; finance en lecture seule sur les contrats ; règles réservées à settings.manage.
    fin = api(staff("r_fin2", "finance"))
    assert fin.post(f"{BO}/contracts/{c.pk}/decision/", {"action": "suspend", "reason": "Test de droits"}, format="json").status_code == 403
    assert api(staff("r_sup2", "support")).put(f"{BO}/rules/default/", {"allow_employment": True}, format="json").status_code == 403
    assert api(staff("r_ops3", "ops")).put(f"{BO}/rules/default/", {"allow_employment": True}, format="json").status_code == 403


def test_contract_list_and_detail_expose_real_data_without_sensitive_fields():
    owner, worker, c, today = world()
    ops = api(staff("d_ops", "ops"))
    rows = ops.get(f"{BO}/contracts/").json()
    assert rows["count"] == 1 and rows["results"][0]["id"] == c.pk and rows["results"][0]["status"] == "active" and rows["results"][0]["amount"] == "150000.00"
    assert ops.get(f"{BO}/contracts/?status=terminated").json()["count"] == 0 and ops.get(f"{BO}/contracts/?flag=overdue").json()["count"] == 0
    assert ops.get(f"{BO}/contracts/?mission_type=long_term&work_relationship=independent").json()["count"] == 1
    detail = ops.get(f"{BO}/contracts/{c.pk}/").json()
    assert len(detail["installments"]) == 4 and {a["role"] for a in detail["acceptances"]} == {"principal", "worker"} and detail["terms_hash"] == c.terms_hash
    blob = str(detail).lower()
    assert "location_address" not in blob and "rue des jardins" not in blob                                # adresse précise : entre les parties
    assert "evidence" not in blob and "@x.test" not in blob and "+225" not in blob
    assert detail["principal_detail"]["phone"] is None or "••" in detail["principal_detail"]["phone"]
    assert ops.get(f"{BO}/contracts/999999/").status_code == 404


def test_admin_decision_needs_a_reason_is_audited_and_notifies_both_parties():
    owner, worker, c, today = world()
    sup = staff("a_sup", "support")
    client = api(sup)
    assert client.post(f"{BO}/contracts/{c.pk}/decision/", {"action": "suspend"}, format="json").status_code == 400                           # motif obligatoire
    assert client.post(f"{BO}/contracts/{c.pk}/decision/", {"action": "delete", "reason": "Suppression"}, format="json").status_code == 400    # pas de suppression
    r = client.post(f"{BO}/contracts/{c.pk}/decision/", {"action": "suspend", "reason": "Signalement de fraude en cours d'examen"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    assert audited("engagement.contract_suspend", target_id=c.pk).filter(actor=sup).exists()
    assert audited("engagement.contract_suspend", target_id=c.pk).first().data["reason"].startswith("Signalement")
    assert Notification.objects.filter(user=owner, notification_type="contract_suspended").exists() and Notification.objects.filter(user=worker, notification_type="contract_suspended").exists()
    # Les parties ne peuvent pas lever une suspension de la plateforme.
    from engagements.services.common import EngagementError
    with pytest.raises(EngagementError) as e:
        contract_svc.resume(c, owner, today=today)
    assert e.value.status == 403
    assert client.post(f"{BO}/contracts/{c.pk}/decision/", {"action": "resume", "reason": "Vérifications terminées"}, format="json").json()["status"] == "active"
    r = client.post(f"{BO}/contracts/{c.pk}/decision/", {"action": "terminate", "reason": "Résiliation après litige constaté"}, format="json")
    assert r.json()["status"] == "terminated" and audited("engagement.contract_terminate").exists()
    assert client.post(f"{BO}/contracts/{c.pk}/decision/", {"action": "suspend", "reason": "Trop tard maintenant"}, format="json").status_code == 409


def test_disputes_are_reviewed_then_resolved_with_a_decision_and_may_suspend_the_contract():
    owner, worker, c, today = world()
    d = dispute_svc.open_dispute(c, owner, {"kind": "payment", "reason": "Le prestataire conteste le montant versé ce mois-ci."})
    sup = api(staff("dp_sup", "support"))
    assert sup.get(f"{BO}/disputes/?status=open").json()["count"] == 1
    detail = sup.get(f"{BO}/disputes/{d.pk}/").json()
    assert detail["reason"].startswith("Le prestataire") and detail["opened_by_role"] == "principal"
    assert sup.post(f"{BO}/disputes/{d.pk}/review/").json()["status"] == "under_review"
    assert sup.post(f"{BO}/disputes/{d.pk}/resolve/", {"accepted": True, "resolution": "court"}, format="json").status_code == 400
    assert sup.post(f"{BO}/disputes/{d.pk}/resolve/", {"accepted": "oui", "resolution": "Décision motivée en détail"}, format="json").status_code == 400
    assert sup.post(f"{BO}/disputes/{d.pk}/resolve/", {"accepted": True, "resolution": "Médiation menée, les parties s'accordent.", "resolution_action": "waive_installment"}, format="json").status_code == 400
    ok = sup.post(f"{BO}/disputes/{d.pk}/resolve/", {"accepted": True, "resolution": "Suspension le temps de la médiation entre les parties.", "resolution_action": "suspend"}, format="json")
    assert ok.status_code == 200 and ok.json()["status"] == "resolved" and ok.json()["resolution_action"] == "suspend"
    c.refresh_from_db()
    assert c.status == "suspended" and audited("engagement.dispute_resolved", target_id=d.pk).exists()
    assert Notification.objects.filter(user=worker, notification_type="engagement_dispute", title="Litige traité").exists()
    assert sup.post(f"{BO}/disputes/{d.pk}/resolve/", {"accepted": True, "resolution": "Encore une décision motivée ici"}, format="json").status_code == 409


def test_evaluations_can_be_hidden_with_a_reason_and_leave_the_public_summary():
    owner, worker, c, today = world()
    ev = eval_svc.create(c, owner, {"kind": "periodic", "rating": 1, "comment": "Très déçu du service rendu."}, today=today + timedelta(days=40))
    eval_svc.report(ev, worker, "Cette évaluation est mensongère et diffamatoire.")
    sup = api(staff("ev_sup", "support"))
    flagged = sup.get(f"{BO}/evaluations/?flag=reported").json()
    assert flagged["count"] == 1 and flagged["results"][0]["reports"] == 1
    assert sup.post(f"{BO}/evaluations/{ev.pk}/hide/", {}, format="json").status_code == 400
    assert sup.post(f"{BO}/evaluations/{ev.pk}/wipe/", {"reason": "Suppression définitive"}, format="json").status_code == 404
    assert sup.post(f"{BO}/evaluations/{ev.pk}/hide/", {"reason": "Propos diffamatoires confirmés par la relecture"}, format="json").json()["is_hidden"] is True
    assert eval_svc.summary_for(worker)["count"] == 0 and EvaluationReport.objects.get(evaluation=ev).is_resolved
    assert audited("engagement.evaluation_hide", target_id=ev.pk).exists()
    assert sup.post(f"{BO}/evaluations/{ev.pk}/hide/", {"reason": "Déjà masquée avant"}, format="json").status_code == 409
    assert sup.post(f"{BO}/evaluations/{ev.pk}/restore/", {}, format="json").json()["is_hidden"] is False
    assert EngagementEvaluation.objects.filter(pk=ev.pk).exists()                                       # jamais supprimée


def test_abusive_postings_are_removed_not_deleted_and_the_author_is_told():
    owner, worker = eng_person("pm_owner"), pro("pm_worker")
    today = timezone.localdate()
    p = posting_svc.publish(posting_svc.create_posting(owner, {"category": category().pk, "title": "Offre trop belle pour être vraie", "description": "Gagnez beaucoup sans rien faire, payez d'abord.",
                                                               "mission_type": "long_term", "work_relationship": "independent", "city": "Abidjan", "amount": "500000", "period": "monthly"}, today=today), owner)
    app = posting_svc.apply(p, worker, {"message": "Intéressé"})
    ops = api(staff("pm_ops", "ops"))
    assert ops.get(f"{BO}/postings/?status=open").json()["count"] == 1
    assert ops.post(f"{BO}/postings/{p.pk}/remove/", {}, format="json").status_code == 400
    r = ops.post(f"{BO}/postings/{p.pk}/remove/", {"reason": "Demande d'avance d'argent : tentative d'arnaque"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    p.refresh_from_db(); app.refresh_from_db()
    assert p.status == "cancelled" and app.status == "rejected" and EngagementPosting.objects.filter(pk=p.pk).exists()
    assert Notification.objects.filter(user=owner, notification_type="system", title="Besoin retiré").exists() and audited("engagement.posting_removed", target_id=p.pk).exists()
    assert ops.post(f"{BO}/postings/{p.pk}/remove/", {"reason": "Une seconde fois pour voir"}, format="json").status_code == 409


def test_rules_are_bounded_audited_per_category_and_drive_the_user_side():
    owner, worker, c, today = world()
    root = api(staff("ru_root", superuser=True))
    listing = root.get(f"{BO}/rules/").json()
    assert listing["default"]["allow_employment"] is False and listing["limits"]["max_duration_months"] == [1, 240] and "avis juridique" in listing["notice"]
    bad = root.put(f"{BO}/rules/default/", {"max_duration_months": 999, "commission_percent_independent": "80", "commission_payer": "tratra", "allow_employment": "yes"}, format="json")
    assert bad.status_code == 400 and set(bad.json()["fields"]) == {"max_duration_months", "commission_percent_independent", "commission_payer", "allow_employment"}
    assert root.put(f"{BO}/rules/default/", {}, format="json").status_code == 400
    assert root.put(f"{BO}/rules/unknown/", {"late_grace_days": 3}, format="json").status_code == 404
    ok = root.put(f"{BO}/rules/{category().pk}/", {"allow_employment": True, "min_notice_days_employment": 45, "reason": "Pilote emploi domestique"}, format="json")
    assert ok.status_code == 200 and ok.json()["allow_employment"] is True and ok.json()["customized"] is True
    event = audited("engagement.rules_updated").first()
    assert event.data["changes"]["allow_employment"] == {"from": False, "to": True} and event.data["reason"].startswith("Pilote")
    # Côté utilisateur : l'emploi est désormais accepté pour cette catégorie, avec le préavis de 45 jours.
    user_rules = api(owner).get(f"/handy/engagements/rules/?category={category().pk}").json()
    assert user_rules["allow_employment"] is True and user_rules["min_notice_days_employment"] == 45
    assert root.get(f"{BO}/rules/").json()["categories"][0]["customized"] is True
    assert root.delete(f"{BO}/rules/default/").status_code == 404                                       # pas encore de règle générale enregistrée
    assert root.put(f"{BO}/rules/default/", {"late_grace_days": 4}, format="json").status_code == 200
    assert root.delete(f"{BO}/rules/default/").status_code == 409                                       # la règle générale se modifie, ne se supprime pas
    assert root.delete(f"{BO}/rules/{category().pk}/").status_code == 204
    assert api(owner).get(f"/handy/engagements/rules/?category={category().pk}").json()["allow_employment"] is False
    assert audited("engagement.rules_reset").exists()


def test_platform_fee_settlement_needs_a_reference_and_finance_manage_and_never_changes_amounts():
    owner, worker = eng_person("fee_owner"), pro("fee_worker")
    EngagementRule.objects.create(is_default=True, commission_percent_independent="2.00", commission_payer="principal")
    today = timezone.localdate()
    c = make_contract(owner, worker, start=today, today=today, months=12)
    tasks.run(today)
    inst = c.installments.get(sequence=0)
    assert str(inst.platform_fee) == "3000.00" and inst.platform_fee_status == "due" and str(inst.base_amount) == "150000.00"     # commission séparée du montant dû
    fin = api(staff("fee_fin", "finance"))
    rows = fin.get(f"{BO}/installments/?fee=due").json()
    assert rows["count"] == 4 and rows["results"][0]["platform_fee"] == "3000.00" and rows["results"][0]["total"] == "150000.00"
    assert api(staff("fee_sup", "support")).post(f"{BO}/installments/{inst.pk}/fee/", {"status": "settled", "reference": "VIR-1"}, format="json").status_code == 403
    assert fin.post(f"{BO}/installments/{inst.pk}/fee/", {"status": "settled"}, format="json").status_code == 400                  # référence obligatoire
    assert fin.post(f"{BO}/installments/{inst.pk}/fee/", {"status": "paid", "reference": "VIR-1"}, format="json").status_code == 400
    ok = fin.post(f"{BO}/installments/{inst.pk}/fee/", {"status": "settled", "reference": "VIR-2027-0001"}, format="json")
    assert ok.status_code == 200 and ok.json()["platform_fee_status"] == "settled" and ok.json()["total"] == "150000.00" and ok.json()["balance"] == "150000.00"
    assert fin.post(f"{BO}/installments/{inst.pk}/fee/", {"status": "waived", "reason": "Geste commercial"}, format="json").status_code == 409
    assert audited("engagement.fee_settled", target_id=inst.pk).exists()
    # Le Back-Office ne confirme jamais un paiement : aucune route ne le permet.
    assert fin.post(f"{BO}/installments/{inst.pk}/payments/", {}, format="json").status_code == 404


def test_dashboard_overview_and_exports_are_real_and_safe():
    owner, worker, c, today = world()
    late_day = today + timedelta(days=75)                                                                   # au moins la première échéance est en retard, quel que soit le jour du mois
    tasks.run(late_day)
    late = ContractInstallment.objects.filter(status="overdue").count()
    assert late >= 1
    dispute_svc.open_dispute(c, worker, {"kind": "planning", "reason": "Les heures de présence ne sont pas reconnues."})
    ops = api(staff("ov_ops", "ops"))
    ov = ops.get(f"{BO}/").json()
    assert ov["contracts"]["live"] == 1 and ov["contracts"]["by_mission_type"] == {"long_term": 1} and ov["contracts"]["monthly_commitment"] == "150000.00"
    assert ov["installments"]["overdue"] == late and ov["installments"]["overdue_amount"] == f"{150000 * late}.00" and ov["disputes"]["open"] == 1
    assert ov["series"]["contracts_created"][-1]["count"] == 1 and ov["series"]["confirmed_payments"] == []
    dash = ops.get("/handy/backoffice/dashboard/").json()
    assert dash["kpis"]["engagements"]["live"] == 1 and {a["key"] for a in dash["alerts"]} >= {"engagement_disputes", "engagement_overdue"}
    marketing = api(staff("ov_mkt", "marketing")).get("/handy/backoffice/dashboard/").json()
    assert "engagements" not in marketing["kpis"] and not any(a["key"].startswith("engagement") for a in marketing["alerts"])
    analyst = staff("ov_ana", "analyst")
    assert api(analyst).get("/handy/backoffice/analytics/export/engagements/").status_code == 403           # droit supplémentaire exigé
    csv = ops.get("/handy/backoffice/analytics/export/engagements/")
    assert csv.status_code == 200 and "bo_owner" not in csv.content.decode() and "id;cree_le;statut" in csv.content.decode()
    inst_csv = ops.get("/handy/backoffice/analytics/export/engagement_installments/")
    assert inst_csv.status_code == 200 and "statut_commission" in inst_csv.content.decode()
    assert audited("export.downloaded", target_type="export").count() == 2
