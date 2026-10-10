"""Besoins, candidatures, entretiens, contrat numérique, avenants, suspension, préavis, renouvellement, clôture."""
from datetime import date, timedelta

import pytest
from django.utils import timezone

from engagements import tasks
from engagements.models import (
    ContractAcceptance, ContractEvent, ContractInstallment, EngagementApplication, EngagementContract, EngagementPosting, EngagementRule, ScheduleEvent,
)
from engagements.services import contracts, postings
from engagements.services.common import EngagementError
from engagements.testing import WEEK, allow_employment, category, contract_data, make_contract, person, pro
from handy.models import Notification

pytestmark = pytest.mark.django_db
TODAY = date(2027, 1, 4)     # un lundi


def posting_data(**over):
    data = dict(category=category().pk, title="Gardien de nuit — résidence", description="Surveillance de la résidence, rondes et accueil des visiteurs.",
                mission_type="long_term", work_relationship="independent", city="Abidjan", start_date=TODAY + timedelta(days=10), schedule=WEEK,
                amount="180000", period="monthly", conditions="Tenue fournie.")
    data.update(over)
    return data


def err(fn, *a, **k):
    with pytest.raises(EngagementError) as e:
        fn(*a, **k)
    return e.value


# ── Besoins ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_posting_validation_rules_and_employment_safeguards():
    owner = person("p_owner")
    bad = err(postings.create_posting, owner, {"title": "x", "description": "court"}, today=TODAY)
    assert bad.code == "invalid" and {"category", "title", "description", "mission_type", "city", "amount"} <= set(bad.extra["fields"])
    ok = postings.create_posting(owner, posting_data(), today=TODAY)
    assert ok.status == "draft" and str(ok.hours_per_week) == "20.00"                              # heures déduites du planning
    emp = err(postings.create_posting, owner, posting_data(work_relationship="employment"), today=TODAY)
    assert "work_relationship" in emp.extra["fields"]                                              # emploi salarié fermé par défaut
    allow_employment()
    no_ack = err(postings.create_posting, owner, posting_data(work_relationship="employment"), today=TODAY)
    assert "employment_notice_ack" in no_ack.extra["fields"]
    good = postings.create_posting(owner, posting_data(work_relationship="employment", employment_notice_ack=True), today=TODAY)
    assert good.work_relationship == "employment"
    too_long = err(postings.create_posting, owner, posting_data(end_date=TODAY + timedelta(days=365 * 7)), today=TODAY)
    assert "end_date" in too_long.extra["fields"]                                                  # durée maximale (60 mois par défaut)
    assert err(postings.create_posting, owner, posting_data(start_date=TODAY - timedelta(days=1)), today=TODAY).extra["fields"].get("start_date")
    assert err(postings.create_posting, owner, posting_data(schedule=[{"weekday": 9, "start": "08:00", "end": "09:00"}]), today=TODAY).extra["fields"].get("schedule")
    assert err(postings.create_posting, owner, posting_data(schedule=[{"weekday": 1, "start": "08:00", "end": "10:00"}, {"weekday": 1, "start": "09:00", "end": "11:00"}]), today=TODAY).extra["fields"].get("schedule")


def test_only_owner_publishes_edits_and_versions_are_checked():
    owner, other = person("pv_owner"), person("pv_other")
    p = postings.create_posting(owner, posting_data(), today=TODAY)
    assert err(postings.publish, p, other).status == 403
    p = postings.publish(p, owner)
    assert p.status == "open" and postings.publish(p, owner).status == "open"                      # idempotent
    upd = postings.update_posting(p, owner, {"title": "Gardien de nuit (équipe B)"}, expected_version=p.version, today=TODAY)
    assert upd.version == p.version + 1
    assert err(postings.update_posting, p, owner, {"title": "Écrasement"}, expected_version=p.version, today=TODAY).code == "version_conflict"
    assert err(postings.update_posting, p, other, {"title": "Pirate !"}, today=TODAY).status == 403
    closed = postings.close_posting(upd, owner)
    assert closed.status == "closed" and err(postings.update_posting, closed, owner, {"title": "Trop tard"}, today=TODAY).code == "not_editable"


def test_posting_with_a_past_deadline_expires_and_stops_applications():
    owner, worker = person("pe_owner"), pro("pe_worker")
    p = postings.publish(postings.create_posting(owner, posting_data(application_deadline=TODAY + timedelta(days=2)), today=TODAY), owner)
    assert postings.expire_due(TODAY + timedelta(days=3)) == 1
    p.refresh_from_db()
    assert p.status == "expired" and err(postings.apply, p, worker, {"message": "Bonjour"}).code == "posting_closed"


# ── Candidatures et entretiens ──────────────────────────────────────────────────────────────────────────────────────

def test_application_rules_decisions_and_interviews():
    owner, worker, rival = person("a_owner"), pro("a_worker"), pro("a_rival")
    unverified = person("a_unverified")
    p = postings.publish(postings.create_posting(owner, posting_data(), today=TODAY), owner)
    assert err(postings.apply, p, owner, {}).status == 403                                         # pas à son propre besoin
    assert err(postings.apply, p, unverified, {}).code == "worker_not_verified"                    # KYC exigé
    app = postings.apply(p, worker, {"message": "Dix ans d'expérience.", "proposed_amount": "170000"})
    assert app.status == "submitted" and Notification.objects.filter(user=owner, notification_type="engagement_application").exists()
    assert err(postings.apply, p, worker, {}).code == "already_applied"
    assert err(postings.decide, app, rival, "select").status == 403                                # étranger au besoin
    iv = postings.propose_interview(app, owner, {"scheduled_at": (timezone.now() + timedelta(days=2)).isoformat(), "mode": "phone"})
    app.refresh_from_db()
    assert app.status == "interview" and iv.status == "proposed"
    assert err(postings.respond_interview, iv, owner, "confirm").status == 403                     # c'est à l'autre partie de répondre
    assert postings.respond_interview(iv, worker, "confirm").status == "confirmed"
    assert err(postings.respond_interview, iv, worker, "confirm").code == "not_open"
    assert err(postings.propose_interview, app, owner, {"scheduled_at": (timezone.now() - timedelta(days=1)).isoformat()}).extra["fields"].get("scheduled_at")
    assert postings.respond_interview(iv, owner, "done").status == "done"
    chosen = postings.decide(app, owner, "select", "Profil retenu")
    assert chosen.status == "selected" and Notification.objects.filter(user=worker, notification_type="engagement_selected").exists()
    rival_app = postings.apply(p, rival, {})
    assert postings.withdraw(rival_app, rival).status == "withdrawn"
    assert err(postings.withdraw, rival_app, rival).code == "not_open"


# ── Contrat numérique ───────────────────────────────────────────────────────────────────────────────────────────────

def selected_application(owner, worker, **posting_over):
    p = postings.publish(postings.create_posting(owner, posting_data(**posting_over), today=TODAY), owner)
    app = postings.apply(p, worker, {"proposed_amount": "175000"})
    return p, postings.decide(app, owner, "select")


def test_contract_from_a_selected_application_requires_both_acceptances_on_the_exact_terms():
    owner, worker, rival = person("c_owner"), pro("c_worker"), pro("c_rival")
    posting, app = selected_application(owner, worker)
    rival_app = postings.apply(posting, rival, {})
    assert err(contracts.create_draft, owner, {"application": rival_app.pk}, today=TODAY).code == "application_not_selected"
    c = contracts.create_draft(owner, {"application": app.pk, "notice_period_days": 10, "payment_day": 5}, today=TODAY)
    assert c.status == "draft" and str(c.amount) == "175000.00" and c.worker_id == worker.id    # montant proposé par le candidat
    assert err(contracts.create_draft, owner, {"application": app.pk}, today=TODAY).code == "contract_exists"
    assert err(contracts.accept, c, worker, "x" * 64, today=TODAY).code == "not_pending"          # pas avant la proposition
    assert err(contracts.propose, c, worker, today=TODAY).status == 404                           # le prestataire ne propose pas
    c = contracts.propose(c, owner, today=TODAY)
    assert c.status == "pending_acceptance" and len(c.terms_hash) == 64
    assert ContractAcceptance.objects.get(contract=c).role == "principal"                         # le proposant accepte sa propre offre
    assert Notification.objects.filter(user=worker, notification_type="contract_proposed").exists()
    assert err(contracts.accept, c, worker, "0" * 64, today=TODAY).code == "terms_changed"        # empreinte différente : refus
    assert err(contracts.accept, c, rival, c.terms_hash, today=TODAY).status == 404               # un tiers n'existe pas pour ce contrat
    c = contracts.accept(c, worker, c.terms_hash, today=TODAY + timedelta(days=0))
    assert c.status == "accepted"                                                                  # début dans 10 jours
    assert set(c.acceptances.values_list("role", flat=True)) == {"principal", "worker"}
    posting.refresh_from_db()
    assert posting.status == "filled"
    rival_app.refresh_from_db()
    assert rival_app.status == "rejected"
    assert contracts.sync(c, TODAY + timedelta(days=9)) == []                                      # pas encore le début
    assert contracts.sync(c, TODAY + timedelta(days=10)) and EngagementContract.objects.get(pk=c.pk).status == "active"
    assert {"created", "proposed", "accepted", "activated"} <= set(c.events.values_list("type", flat=True))


def test_worker_can_request_changes_or_decline_and_reproposal_creates_a_new_terms_version():
    owner, worker = person("r_owner"), pro("r_worker")
    c = contracts.create_draft(owner, contract_data(worker, start=TODAY), today=TODAY)
    c = contracts.propose(c, owner, today=TODAY)
    v1_hash = c.terms_hash
    back = contracts.send_back(c, worker, "Je souhaite 160 000 par mois.")
    assert back.status == "draft"
    contracts.update_draft(back, owner, {"amount": "160000"}, today=TODAY)
    again = contracts.propose(back, owner, today=TODAY)
    assert again.terms_version == 2 and again.terms_hash != v1_hash
    assert err(contracts.accept, again, worker, v1_hash, today=TODAY).code == "terms_changed"     # l'ancienne version n'est plus acceptable
    declined = contracts.decline(again, worker, "Conditions non retenues")
    assert declined.status == "cancelled" and err(contracts.accept, declined, worker, again.terms_hash).code == "not_pending"
    assert declined.events.filter(type="cancelled").exists()


def test_contract_terms_are_validated_per_category_rules_and_worker_must_be_verified():
    owner, worker, unverified = person("v_owner"), pro("v_worker"), person("v_unverified")
    assert err(contracts.create_draft, owner, contract_data(unverified, start=TODAY), today=TODAY).code == "worker_not_verified"
    assert "worker" in err(contracts.create_draft, owner, contract_data(owner, start=TODAY), today=TODAY).extra["fields"]   # on ne contracte pas avec soi-même
    bad = err(contracts.create_draft, owner, contract_data(worker, start=TODAY, notice_period_days=1, amount="0", payment_day=40), today=TODAY)
    assert {"notice_period_days", "amount", "payment_day"} <= set(bad.extra["fields"])           # préavis minimal de la catégorie : 7 jours
    emp = err(contracts.create_draft, owner, contract_data(worker, start=TODAY, work_relationship="employment"), today=TODAY)
    assert "work_relationship" in emp.extra["fields"]
    EngagementRule.objects.create(category=category(), allow_employment=True, min_notice_days_employment=30)
    short = err(contracts.create_draft, owner, contract_data(worker, start=TODAY, work_relationship="employment", legal_notice_ack=True, notice_period_days=10), today=TODAY)
    assert "notice_period_days" in short.extra["fields"]
    emp_ok = contracts.create_draft(owner, contract_data(worker, start=TODAY, work_relationship="employment", legal_notice_ack=True, notice_period_days=30), today=TODAY)
    assert emp_ok.work_relationship == "employment"
    bookings = err(contracts.create_draft, owner, contract_data(worker, start=TODAY, work_relationship="employment", legal_notice_ack=True, notice_period_days=30, bookings_mode="per_occurrence", schedule=WEEK), today=TODAY)
    assert "bookings_mode" in bookings.extra["fields"]                                             # pas de réservations pour un emploi salarié
    assert err(contracts.create_draft, owner, contract_data(worker, start=TODAY - timedelta(days=1)), today=TODAY).extra["fields"].get("start_date")


# ── Avenants, suspension, préavis, renouvellement, clôture ─────────────────────────────────────────────────────────

def test_amendment_needs_the_other_party_is_not_retroactive_and_keeps_a_full_history():
    owner, worker = person("m_owner"), pro("m_worker")
    c = make_contract(owner, worker, start=TODAY, months=24)
    assert c.status == "active"
    tasks.run(TODAY)
    first = list(c.installments.order_by("sequence").values_list("sequence", "base_amount"))
    assert [s for s, _ in first] == [0, 1, 2, 3] and all(str(a) == "150000.00" for _, a in first)
    eff = date(2027, 3, 4)
    bad = err(contracts.propose_amendment, c, owner, {"kind": "change", "changes": {"start_date": "2027-02-01"}, "reason": "Impossible"}, today=TODAY)
    assert bad.code == "invalid"                                                                   # le début n'est pas modifiable
    am = contracts.propose_amendment(c, owner, {"kind": "change", "changes": {"amount": "165000"}, "reason": "Revalorisation convenue", "effective_date": eff}, today=TODAY)
    assert err(contracts.propose_amendment, c, worker, {"kind": "change", "changes": {"amount": "170000"}, "reason": "Contre-proposition"}, today=TODAY).code == "amendment_pending"
    assert err(contracts.respond_amendment, am, owner, True, today=TODAY).status == 403            # l'auteur ne répond pas à son avenant
    contracts.withdraw_amendment(am, owner)
    am2 = contracts.propose_amendment(c, owner, {"kind": "change", "changes": {"amount": "165000"}, "reason": "Revalorisation convenue", "effective_date": eff}, today=TODAY)
    before_hash, before_version = EngagementContract.objects.get(pk=c.pk).terms_hash, EngagementContract.objects.get(pk=c.pk).terms_version
    contracts.respond_amendment(am2, worker, True, today=TODAY)
    c.refresh_from_db()
    assert str(c.amount) == "150000.00" and c.terms_version == before_version                      # accepté mais pas encore en vigueur
    tasks.run(eff)
    c.refresh_from_db()
    assert str(c.amount) == "165000.00" and c.terms_version == before_version + 1 and c.terms_hash != before_hash
    amounts = {i.sequence: str(i.base_amount) for i in c.installments.all()}
    assert amounts[0] == amounts[1] == "150000.00"                                                 # périodes déjà commencées : intactes
    assert amounts[2] == "165000.00" and amounts[3] == "165000.00"
    assert ContractAcceptance.objects.filter(contract=c, terms_version=before_version + 1).count() == 2   # acceptation des deux parties à la nouvelle version
    assert list(c.events.filter(type__startswith="amendment").values_list("type", flat=True)) == ["amendment_proposed", "amendment_withdrawn", "amendment_proposed", "amendment_accepted", "amendment_applied"]


def test_suspension_by_agreement_holds_installments_pauses_the_planning_and_resumes():
    owner, worker = person("s_owner"), pro("s_worker")
    c = make_contract(owner, worker, start=TODAY, months=12, schedule=WEEK)
    tasks.run(TODAY)
    am = contracts.propose_amendment(c, worker, {"kind": "suspend", "changes": {"starts_on": "2027-02-04", "ends_on": "2027-04-04"}, "reason": "Convalescence"}, today=TODAY)
    contracts.respond_amendment(am, owner, True, today=TODAY)
    tasks.run(date(2027, 2, 4))                                                                     # jour du début de la suspension
    c.refresh_from_db()
    assert c.status == "suspended"
    held = {i.sequence: i.status for i in c.installments.all()}
    assert held[1] == "on_hold" and held[2] == "on_hold" and held[0] != "on_hold"                  # fév. et mars entièrement suspendus
    assert not c.schedule_events.filter(kind="shift", status="planned", date__gte=date(2027, 2, 4), date__lt=date(2027, 4, 4)).exists()
    assert err(contracts.resume, c, person("s_stranger"), today=date(2027, 2, 10)).status == 404
    contracts.resume(c, owner, today=date(2027, 3, 1))
    c.refresh_from_db()
    assert c.status == "active" and c.schedule_events.filter(kind="shift", status="planned", date__gte=date(2027, 3, 1)).exists()


def test_notice_period_ends_the_contract_cancels_future_periods_and_closing_needs_no_balance():
    owner, worker = person("n_owner"), pro("n_worker")
    c = make_contract(owner, worker, start=TODAY, months=None, schedule=WEEK)          # durée indéterminée
    assert c.is_indefinite
    tasks.run(TODAY)
    assert err(contracts.give_notice, c, worker, {"last_day": TODAY + timedelta(days=3), "reason": "Départ"}, today=TODAY).code == "invalid"   # préavis de 7 jours
    last_day = date(2027, 2, 12)
    c = contracts.give_notice(c, worker, {"last_day": last_day, "reason": "Nouveau poste"}, today=TODAY)
    assert c.status == "notice" and c.ends_on == last_day and c.notice_given_by_id == worker.id
    assert Notification.objects.filter(user=owner, notification_type="contract_notice").exists()
    assert not c.installments.filter(period_start__gt=last_day).exclude(status="cancelled").exists()
    assert not c.schedule_events.filter(kind="shift", date__gt=last_day, status="planned").exists()
    tasks.run(last_day + timedelta(days=1))
    c.refresh_from_db()
    assert c.status == "terminated" and c.ended_at and not c.schedule_events.filter(date__gt=last_day, status="planned").exists()
    assert err(contracts.close, c, owner).code == "balance_due"                                    # échéances encore dues
    for inst in ContractInstallment.objects.filter(contract=c).exclude(status="cancelled"):
        inst.status = "waived"
        inst.save(update_fields=["status"])
    assert contracts.close(c, owner).closed_at is not None


def test_fixed_term_auto_renews_unless_non_renewal_is_given_in_time_and_respects_the_duration_cap():
    owner, worker = person("rn_owner"), pro("rn_worker")
    c = make_contract(owner, worker, start=TODAY, months=6, auto_renew=True, renewal_term_months=6, notice_period_days=15)
    first_end = c.end_date
    tasks.run(first_end + timedelta(days=1))
    c.refresh_from_db()
    assert c.status == "active" and c.renewal_count == 1 and c.end_date > first_end and c.events.filter(type="renewed").exists()
    assert err(contracts.declare_non_renewal, c, owner, today=c.end_date - timedelta(days=5)).code == "too_late"   # préavis de 15 jours dépassé
    contracts.declare_non_renewal(c, owner, today=c.end_date - timedelta(days=20))
    second_end = c.end_date
    tasks.run(second_end + timedelta(days=1))
    c.refresh_from_db()
    assert c.status == "completed" and c.renewal_count == 1                                        # non-renouvelé : terme atteint
    capped = make_contract(person("rn_owner2"), pro("rn_worker2"), start=TODAY, months=60, auto_renew=True, renewal_term_months=12)
    tasks.run(capped.end_date + timedelta(days=1))
    capped.refresh_from_db()
    assert capped.status == "completed"                                                            # plafond de 60 mois : pas de renouvellement


def test_admin_decisions_suspend_resume_and_terminate_with_a_reason_only():
    owner, worker, admin = person("ad_owner"), pro("ad_worker"), person("ad_admin")
    c = make_contract(owner, worker, start=TODAY, months=12)
    assert err(contracts.admin_decision, c, admin, "suspend", "x", today=TODAY).code == "invalid"
    c = contracts.admin_decision(c, admin, "suspend", "Fraude présumée sur les paiements", today=TODAY)
    assert c.status == "suspended"
    assert err(contracts.resume, c, owner, today=TODAY).status == 403                              # les parties ne lèvent pas une suspension de la plateforme
    c = contracts.admin_decision(c, admin, "resume", "Vérifications terminées", today=TODAY + timedelta(days=3))
    assert c.status == "active"
    c = contracts.admin_decision(c, admin, "terminate", "Résiliation après litige", today=TODAY + timedelta(days=10))
    assert c.status == "terminated" and "plateforme" in c.end_reason
