"""Simulation d'un engagement de TROIS ANS jour après jour (tick hebdomadaire) : échéances sans doublon ni trou (fins de mois,
année bissextile), avenant non rétroactif, suspension de deux mois, paiements confirmés par la contrepartie, évaluations annuelles,
terme, clôture — puis rejeu du tick : aucun effet."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from engagements import tasks
from engagements.dates import add_months, next_payment_date, period_bounds
from engagements.models import ContractEvent, ContractInstallment, EngagementContract, EngagementEvaluation, ScheduleEvent
from engagements.services import contracts, evaluations as ev_svc, installments as inst_svc
from engagements.services.common import moment
from engagements.testing import make_contract, person, pro
from handy.models import Notification

pytestmark = pytest.mark.django_db
D = Decimal


def test_month_end_clamping_and_leap_years_are_contiguous_and_stable():
    start = date(2027, 1, 31)
    assert add_months(start, 1) == date(2027, 2, 28) and add_months(start, 13) == date(2028, 2, 29) and add_months(start, 14) == date(2028, 3, 31)
    assert add_months(date(2028, 2, 29), 12) == date(2029, 2, 28)
    previous_end = None
    for k in range(0, 72):
        ps, pe = period_bounds(start, k)
        assert ps <= pe and (previous_end is None or ps == previous_end + timedelta(days=1))      # aucune période ne recouvre ni ne laisse de trou
        previous_end = pe
    assert next_payment_date(date(2027, 2, 27), 31) == date(2027, 2, 28) and next_payment_date(date(2027, 2, 27), 5) == date(2027, 3, 5)
    assert next_payment_date(date(2028, 1, 31), 31) == date(2028, 1, 31)


def test_three_year_engagement_end_to_end():
    owner, worker = person("sim_owner"), pro("sim_worker")
    start = date(2027, 1, 31)
    c = make_contract(owner, worker, start=start, months=36, schedule=[{"weekday": 0, "start": "08:00", "end": "12:00"}], payment_day=5)
    assert c.end_date == date(2030, 1, 30) and c.status == "active"
    amend_effective, suspension = date(2028, 3, 31), (date(2028, 9, 30), date(2028, 11, 30))
    done, evaluated = set(), []
    day, last = start, date(2030, 3, 15)
    while day <= last:
        stats = tasks.run(day)
        assert stats["errors"] == 0
        if "amend" not in done and day >= date(2028, 3, 1):
            am = contracts.propose_amendment(c, owner, {"kind": "change", "changes": {"amount": "165000"}, "reason": "Revalorisation annuelle convenue", "effective_date": amend_effective}, today=day)
            contracts.respond_amendment(am, worker, True, today=day)
            done.add("amend")
        if "suspend" not in done and day >= date(2028, 9, 1):
            am = contracts.propose_amendment(c, worker, {"kind": "suspend", "changes": {"starts_on": suspension[0].isoformat(), "ends_on": suspension[1].isoformat()}, "reason": "Congé sans solde convenu"}, today=day)
            contracts.respond_amendment(am, owner, True, today=day)
            done.add("suspend")
        for inst in ContractInstallment.objects.filter(contract=c, status__in=("due", "overdue", "partial"), base_amount__gt=0):
            left = inst_svc.totals(inst)["remaining_to_declare"]
            if left > 0:
                p = inst_svc.declare_payment(inst, owner, {"amount": str(left), "method": "mobile_money", "reference": f"SIM{inst.sequence}", "paid_on": day}, today=day)
                inst_svc.respond_payment(p, worker, True, today=day)
        if day.month == 6 and day.day <= 7 and day.year in (2027, 2028, 2029) and day.year not in evaluated:
            ev = ev_svc.create(c, owner, {"kind": "periodic", "rating": 5, "comment": f"Année {day.year} : service irréprochable."}, today=day)
            EngagementEvaluation.objects.filter(pk=ev.pk).update(created_at=moment(day))
            evaluated.append(day.year)
        day += timedelta(days=7)
    assert done == {"amend", "suspend"} and evaluated == [2027, 2028, 2029]
    c.refresh_from_db()
    assert c.status == "completed" and c.renewal_count == 0 and c.ended_at is not None
    insts = list(c.installments.order_by("sequence"))
    assert [i.sequence for i in insts] == list(range(36))                                          # 36 échéances, sans trou ni doublon
    assert insts[0].period_start == start and insts[-1].period_end == c.end_date
    assert all(insts[i + 1].period_start == insts[i].period_end + timedelta(days=1) for i in range(35))
    assert all(insts[i].due_date < insts[i + 1].due_date for i in range(35))
    by_seq = {i.sequence: i for i in insts}
    assert all(by_seq[k].base_amount == D("150000.00") for k in range(14) if k not in (20, 21))    # périodes commencées avant l'avenant : intactes
    assert all(by_seq[k].base_amount == D("165000.00") for k in range(14, 36) if k not in (20, 21)) # à partir du 31 mars 2028 : nouveau montant
    assert by_seq[13].period_end == date(2028, 3, 30) and by_seq[14].period_start == amend_effective
    assert by_seq[20].status == by_seq[21].status == "on_hold" and by_seq[20].base_amount == by_seq[21].base_amount == 0     # deux mois suspendus
    paid = [i for i in insts if i.status == "paid"]
    assert len(paid) == 34 and all(inst_svc.totals(i)["balance"] == 0 for i in paid)
    assert sum(inst_svc.totals(i)["confirmed"] for i in paid) == D("150000.00") * 14 + D("165000.00") * 20
    assert not InstallmentPaymentsSelfConfirmed()
    # Historique complet et ordonné.
    types = list(c.events.values_list("type", flat=True))
    assert types.count("amendment_applied") == 2 and "ended" in types and types.index("created") == 0
    # Planning : un créneau par lundi du contrat, jamais pendant la suspension, jamais deux fois le même.
    mondays = ScheduleEvent.objects.filter(contract=c, kind="shift", status="planned")
    assert not mondays.filter(date__gte=suspension[0], date__lt=suspension[1]).exists()
    assert mondays.count() == len({(e.date, e.start_time) for e in mondays})
    # Clôture, puis rejeu du tick : aucun effet.
    assert contracts.close(c, owner).closed_at is not None
    before = (ContractInstallment.objects.count(), ScheduleEvent.objects.count(), ContractEvent.objects.count(), Notification.objects.count())
    for _ in range(2):
        tasks.run(last); tasks.run(last + timedelta(days=30))
    assert before == (ContractInstallment.objects.count(), ScheduleEvent.objects.count(), ContractEvent.objects.count(), Notification.objects.count())
    # Évaluation finale encore possible dans les 60 jours, puis expérience vérifiable.
    final = ev_svc.create(c, worker, {"kind": "final", "rating": 5, "comment": "Trois ans de collaboration sereine."}, today=c.ended_at.date() + timedelta(days=5))
    assert final.period_key == "final"
    from engagements.services.experience import experience_for
    xp = experience_for(worker, today=date(2030, 3, 15))
    assert xp["contracts_completed"] == 1 and xp["months_total"] == 36


def InstallmentPaymentsSelfConfirmed():
    from engagements.models import InstallmentPayment
    return [p for p in InstallmentPayment.objects.filter(status="confirmed") if p.responded_by_id == p.declared_by_id]


def test_indefinite_contract_runs_for_years_with_a_rolling_horizon_and_ends_with_notice():
    owner, worker = person("ind_owner"), pro("ind_worker")
    start = date(2027, 3, 15)
    c = make_contract(owner, worker, start=start, months=None)
    day = start
    while day <= date(2031, 3, 15):                                                                # quatre ans, tick mensuel
        tasks.run(day)
        assert c.installments.count() <= (day.year - 2027) * 12 + day.month + 6                    # horizon glissant : jamais une avalanche d'échéances
        day += timedelta(days=30)
    last = c.installments.order_by("-sequence").first()
    assert last.sequence >= 48 and c.installments.count() == last.sequence + 1
    c.refresh_from_db()
    assert c.status == "active" and c.is_indefinite
    c = contracts.give_notice(c, owner, {"last_day": date(2031, 5, 31), "reason": "Fin de besoin du service"}, today=date(2031, 3, 15))
    tasks.run(date(2031, 6, 1))
    c.refresh_from_db()
    assert c.status == "terminated" and c.ends_on == date(2031, 5, 31)
    live = c.installments.exclude(status="cancelled")
    assert live.order_by("-sequence").first().period_end == date(2031, 5, 31)                      # dernière période ramenée à la date de fin (montant du contrat)
    assert not c.installments.filter(period_start__gt=date(2031, 5, 31)).exclude(status="cancelled").exists()
