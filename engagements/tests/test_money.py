"""Rémunération : échéances automatiques et idempotentes, ajustements acceptés, paiements confirmés par la CONTREPARTIE, avances, retards,
paiement variable, prorata convenu, solde et clôture. Aucun calcul légal."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from engagements import tasks
from engagements.models import ContractInstallment, EngagementRule, InstallmentPayment, ScheduleEvent
from engagements.services import contracts, installments as inst_svc, planning
from engagements.services.common import EngagementError
from engagements.testing import WEEK, category, make_contract, person, pro
from handy.models import Notification

pytestmark = pytest.mark.django_db
START = date(2027, 1, 4)
D = Decimal


def err(fn, *a, **k):
    with pytest.raises(EngagementError) as e:
        fn(*a, **k)
    return e.value


def pay(inst, user, amount, *, on, method="mobile_money", reference="REF1", today=None):
    return inst_svc.declare_payment(inst, user, {"amount": str(amount), "method": method, "reference": reference, "paid_on": on}, today=today or on)


def test_installments_are_generated_up_to_the_horizon_once_and_only_once():
    owner, worker = person("i_owner"), pro("i_worker")
    c = make_contract(owner, worker, start=START, months=12)
    assert tasks.run(START)["errors"] == 0
    seqs = list(c.installments.order_by("sequence").values_list("sequence", "period_start", "period_end", "due_date"))
    assert [s[0] for s in seqs] == [0, 1, 2, 3]                                                    # horizon : 3 périodes à venir
    assert seqs[0][1:3] == (date(2027, 1, 4), date(2027, 2, 3)) and seqs[0][3] == date(2027, 2, 5)  # échéance le 5 qui suit la fin de période
    count = c.installments.count()
    for _ in range(3):
        tasks.run(START)                                                                           # rejouer le tick : aucun doublon
    assert c.installments.count() == count
    assert not c.installments.exclude(status="scheduled").exists()
    assert all(str(i.base_amount) == "150000.00" and i.platform_fee == 0 for i in c.installments.all())   # commission 0 % par défaut, séparée du salaire


def test_a_payment_counts_only_when_confirmed_by_the_other_party_and_never_by_its_author():
    owner, worker, stranger = person("p_owner"), pro("p_worker"), person("p_stranger")
    c = make_contract(owner, worker, start=START, months=12)
    tasks.run(START)
    inst = c.installments.get(sequence=0)
    day = date(2027, 2, 6)
    assert err(pay, inst, stranger, 150000, on=day).status == 404
    p1 = pay(inst, owner, 100000, on=day)
    assert p1.status == "declared" and inst_svc.totals(inst)["confirmed"] == 0 and inst_svc.totals(inst)["declared"] == D("100000.00")
    assert Notification.objects.filter(user=worker, notification_type="payment_declared").exists()
    assert err(inst_svc.respond_payment, p1, owner, True).status == 403                            # jamais confirmé par son auteur
    assert err(inst_svc.respond_payment, p1, stranger, True).status == 404
    assert err(inst_svc.respond_payment, p1, worker, False).code == "invalid"                      # contestation = motif obligatoire
    inst_svc.respond_payment(p1, worker, True, today=day)
    inst.refresh_from_db()
    assert inst.status == "partial" and inst_svc.totals(inst)["balance"] == D("50000.00")
    assert err(inst_svc.respond_payment, p1, worker, True).code == "not_open"
    assert err(pay, inst, owner, 60000, on=day, reference="REF2").code == "invalid"                # dépasse le solde restant
    p2 = pay(inst, owner, 50000, on=day, reference="REF2")
    contested = inst_svc.respond_payment(p2, worker, False, "Je n'ai rien reçu de ce versement.", today=day)
    assert contested.status == "rejected" and inst_svc.totals(inst)["confirmed"] == D("100000.00")
    p3 = pay(inst, owner, 50000, on=day, reference="REF3")
    inst_svc.respond_payment(p3, worker, True, today=day)
    inst.refresh_from_db()
    assert inst.status == "paid" and inst_svc.totals(inst)["balance"] == 0
    assert err(pay, inst, owner, 1, on=day, reference="REF4").code == "installment_closed"
    # Un paiement déclaré par le PRESTATAIRE (« j'ai été payé ») doit être confirmé par le donneur d'ordre.
    inst2 = c.installments.get(sequence=1)
    wp = pay(inst2, worker, 50000, on=date(2027, 3, 6), today=date(2027, 3, 6))
    assert err(inst_svc.respond_payment, wp, worker, True).status == 403
    assert inst_svc.respond_payment(wp, owner, True, today=date(2027, 3, 6)).status == "confirmed"


def test_duplicates_future_dates_and_advances_are_controlled():
    owner, worker = person("d_owner"), pro("d_worker")
    c = make_contract(owner, worker, start=START, months=12)
    tasks.run(START)
    inst = c.installments.get(sequence=0)
    assert err(pay, inst, owner, 10000, on=date(2027, 1, 20), today=date(2027, 1, 10)).extra["fields"].get("paid_on")      # date future
    adv = pay(inst, owner, 60000, on=date(2027, 1, 10))                                            # 40 % de l'échéance, avant la fin de période : avance
    assert adv.is_advance
    assert err(pay, inst, owner, 60000, on=date(2027, 1, 10)).code == "duplicate_payment"          # même déclaration : refus
    assert err(pay, inst, owner, 30000, on=date(2027, 1, 12), reference="A2").extra["fields"]["amount"] == "Avance trop élevée."   # plafond 50 % = 75 000
    after = pay(inst, owner, 90000, on=date(2027, 2, 4), today=date(2027, 2, 4))                   # période terminée : plus une avance
    assert not after.is_advance


def test_adjustments_need_the_counterpart_and_change_the_balance():
    owner, worker = person("l_owner"), pro("l_worker")
    c = make_contract(owner, worker, start=START, months=12)
    tasks.run(START)
    inst = c.installments.get(sequence=0)
    bonus = inst_svc.propose_line(inst, owner, {"kind": "bonus", "amount": "10000", "description": "Prime de fin d'année"})
    assert inst_svc.totals(inst)["total"] == D("150000.00")                                        # proposé ≠ compté
    assert err(inst_svc.respond_line, bonus, owner, True).status == 403
    inst_svc.respond_line(bonus, worker, True)
    assert inst_svc.totals(inst)["total"] == D("160000.00")
    exp = inst_svc.propose_line(inst, worker, {"kind": "expense", "amount": "4500", "description": "Achat de produits d'entretien"})
    inst_svc.respond_line(exp, owner, False)
    exp.refresh_from_db()
    assert inst_svc.totals(inst)["total"] == D("160000.00") and exp.status == "rejected"
    ded = inst_svc.propose_line(inst, owner, {"kind": "deduction", "amount": "20000", "description": "Matériel cassé convenu"})
    inst_svc.respond_line(ded, worker, True)
    assert inst_svc.totals(inst)["total"] == D("140000.00")                                        # déduction négative, jamais sans accord
    assert err(inst_svc.propose_line, inst, owner, {"kind": "deduction", "amount": "999999", "description": "Trop élevé"}).code == "invalid"
    assert err(inst_svc.propose_line, inst, owner, {"kind": "overtime", "amount": "10", "description": "interdit ici"}).code == "invalid"   # heures sup via le planning


def test_installments_become_due_then_overdue_after_the_grace_period_and_reminders_are_deduplicated():
    owner, worker = person("o_owner"), pro("o_worker")
    c = make_contract(owner, worker, start=START, months=12)
    tasks.run(START)
    inst = c.installments.get(sequence=0)                                                          # échéance le 5 février, tolérance 5 jours
    tasks.run(date(2027, 2, 3))
    soon = Notification.objects.filter(notification_type="installment_due").count()
    tasks.run(date(2027, 2, 4)); tasks.run(date(2027, 2, 4))
    assert Notification.objects.filter(notification_type="installment_due").count() == soon         # une seule fois par échéance
    tasks.run(date(2027, 2, 5))
    inst.refresh_from_db()
    assert inst.status == "due"
    tasks.run(date(2027, 2, 10))
    inst.refresh_from_db()
    assert inst.status == "due"                                                                    # dans la tolérance
    tasks.run(date(2027, 2, 11))
    inst.refresh_from_db()
    assert inst.status == "overdue"
    assert Notification.objects.filter(user=worker, notification_type="installment_overdue").count() == 1
    tasks.run(date(2027, 2, 12))
    assert Notification.objects.filter(user=worker, notification_type="installment_overdue").count() == 1   # pas de relance quotidienne
    p = pay(inst, owner, 150000, on=date(2027, 2, 12))
    inst_svc.respond_payment(p, worker, True, today=date(2027, 2, 12))
    inst.refresh_from_db()
    assert inst.status == "paid"


def test_only_the_worker_can_waive_a_balance_and_the_contract_cannot_close_with_money_open():
    owner, worker = person("w_owner"), pro("w_worker")
    c = make_contract(owner, worker, start=START, months=1)
    tasks.run(START)
    tasks.run(date(2027, 2, 4))
    c.refresh_from_db()
    assert c.status == "completed"
    assert err(contracts.close, c, owner).code == "balance_due"
    inst = c.installments.get(sequence=0)
    assert err(inst_svc.waive, inst, owner, "Je ne veux plus payer").status == 403                 # le payeur ne se libère pas lui-même
    assert err(inst_svc.waive, inst, worker, "x").code == "invalid"
    p = pay(inst, owner, 100000, on=date(2027, 2, 4))
    inst_svc.respond_payment(p, worker, True, today=date(2027, 2, 4))
    inst_svc.waive(inst, worker, "Solde abandonné par le prestataire")
    inst.refresh_from_db()
    assert inst.status == "waived"
    closed = contracts.close(c, owner)
    assert closed.closed_at is not None and contracts.close(c, owner).closed_at == closed.closed_at     # idempotent


def test_hourly_pay_is_computed_after_the_period_from_attendance_confirmed_by_the_principal_only():
    owner, worker = person("h_owner"), pro("h_worker")
    c = make_contract(owner, worker, start=START, months=3, period="hourly", amount="2500", schedule=[{"weekday": 0, "start": "08:00", "end": "12:00"}])
    tasks.run(START)
    inst = c.installments.get(sequence=0)
    assert inst.base_amount is None and inst.status == "scheduled"
    assert err(pay, inst, owner, 1000, on=date(2027, 1, 10)).code == "not_computed"                # montant inconnu avant la fin de période
    mondays = list(c.schedule_events.filter(kind="shift", date__lte=date(2027, 2, 3)).order_by("date"))
    assert [e.date.weekday() for e in mondays] == [0] * len(mondays) and len(mondays) == 5         # 4, 11, 18, 25 janvier et 1er février
    now = date(2027, 2, 3)
    for ev in mondays[:4]:
        planning.declare_attendance(ev, worker, {}, today=now)
    for ev in mondays[:3]:
        planning.respond_attendance(ev, owner, True)
    planning.respond_attendance(mondays[3], owner, False, "Absent ce jour-là, je conteste.")
    tasks.run(now)
    inst.refresh_from_db()
    assert inst.base_amount is None                                                                # la période n'est pas terminée avant le 4 février
    tasks.run(date(2027, 2, 4))
    inst.refresh_from_db()
    assert inst.base_amount == D("30000.00") and inst.status == "scheduled"                        # 3 présences confirmées × 4 h × 2 500 ; ni déclarée seule, ni contestée
    assert ScheduleEvent.objects.get(pk=mondays[3].pk).attendance_status == "disputed"


def test_per_visit_pay_counts_confirmed_visits_and_the_agreed_proration_applies_to_the_last_month_only():
    owner, worker = person("v_owner"), pro("v_worker")
    c = make_contract(owner, worker, start=START, months=3, period="per_visit", amount="8000", schedule=[{"weekday": 2, "start": "09:00", "end": "11:00"}])
    tasks.run(START)
    wed = list(c.schedule_events.filter(kind="shift", date__lte=date(2027, 2, 3)).order_by("date"))
    for ev in wed[:2]:
        planning.declare_attendance(ev, worker, {}, today=date(2027, 2, 3))
        planning.respond_attendance(ev, owner, True)
    tasks.run(date(2027, 2, 4))
    assert c.installments.get(sequence=0).base_amount == D("16000.00")
    # Prorata convenu (jours calendaires) sur la dernière période partielle d'un contrat mensuel.
    prorata = make_contract(person("v_owner2"), pro("v_worker2"), start=date(2027, 1, 1), months=None, proration_mode="calendar_days", end_date=date(2027, 2, 14))
    tasks.run(date(2027, 1, 1))
    last = prorata.installments.order_by("sequence").last()
    assert last.period_end == date(2027, 2, 14) and last.base_amount == D("75000.00")   # 14 jours sur 28
    plain = make_contract(person("v_owner3"), pro("v_worker3"), start=date(2027, 1, 1), months=None, end_date=date(2027, 2, 14))
    tasks.run(date(2027, 1, 1))
    assert plain.installments.order_by("sequence").last().base_amount == D("150000.00")            # sans clause de prorata : montant du contrat, jamais inventé


def test_evidence_files_are_private_sanitized_and_limited():
    owner, worker = person("e_owner"), pro("e_worker")
    c = make_contract(owner, worker, start=START, months=12)
    tasks.run(START)
    inst = c.installments.get(sequence=0)
    bad = SimpleUploadedFile("virus.exe", b"MZ" + b"0" * 50, content_type="application/octet-stream")
    assert err(inst_svc.declare_payment, inst, owner, {"amount": "1000", "method": "cash", "paid_on": START}, bad).code in ("invalid", "invalid_file")
    pdf = SimpleUploadedFile("recu.pdf", b"%PDF-1.4\n%fake\n" + b"0" * 100, content_type="application/pdf")
    p = inst_svc.declare_payment(inst, owner, {"amount": "1000", "method": "cash", "paid_on": START, "reference": "R"}, pdf, today=START)
    assert p.evidence and p.evidence.name.endswith(".pdf") and "private" in p.evidence.storage.__class__.__name__.lower()
    big = SimpleUploadedFile("gros.pdf", b"%PDF-1.4\n" + b"0" * (5 * 1024 * 1024 + 10), content_type="application/pdf")
    assert err(inst_svc.declare_payment, inst, owner, {"amount": "1000", "method": "cash", "paid_on": START, "reference": "R2"}, big).code in ("invalid", "invalid_file")
