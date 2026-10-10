"""Planning : calendrier généré, congés/absences validés par la contrepartie, heures supplémentaires, remplacements, présences
déclarées puis confirmées, réservations par occurrence (idempotentes) — et AUCUNE donnée de position."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from engagements import tasks
from engagements.models import InstallmentLine, ScheduleEvent
from engagements.services import contracts, planning
from engagements.services.common import EngagementError
from engagements.testing import WEEK, make_contract, person, pro
from handy.models import Booking

pytestmark = pytest.mark.django_db
START = date(2027, 1, 4)    # lundi


def err(fn, *a, **k):
    with pytest.raises(EngagementError) as e:
        fn(*a, **k)
    return e.value


def shifts(c, **kw):
    return c.schedule_events.filter(kind="shift", **kw)


def test_calendar_is_generated_once_on_the_contract_days_only_and_extends_as_time_passes():
    owner, worker = person("pl_owner"), pro("pl_worker")
    c = make_contract(owner, worker, start=START, months=12, schedule=WEEK)
    tasks.run(START)
    first = shifts(c, status="planned").count()
    assert first == 45 and {e.date.weekday() for e in shifts(c)} == {0, 1, 2, 3, 4}               # 60 jours ahead, jours ouvrés
    tasks.run(START); tasks.run(START)
    assert shifts(c).count() == first                                                              # idempotent
    tasks.run(START + timedelta(days=30))
    assert shifts(c).count() > first and shifts(c).count() == len(set(shifts(c).values_list("date", "start_time")))


def test_leave_needs_the_counterpart_removes_covered_shifts_and_survives_regeneration():
    owner, worker, stranger = person("lv_owner"), pro("lv_worker"), person("lv_stranger")
    c = make_contract(owner, worker, start=START, months=12, schedule=WEEK)
    tasks.run(START)
    assert err(planning.request_event, c, stranger, {"kind": "leave", "date": "2027-01-18", "end_date": "2027-01-22"}, today=START).status == 404
    ev = planning.request_event(c, worker, {"kind": "leave", "date": "2027-01-18", "end_date": "2027-01-22", "note": "Congé annuel convenu"}, today=START)
    assert ev.status == "requested" and shifts(c, date__range=("2027-01-18", "2027-01-22"), status="planned").count() == 5   # pas encore validé : rien ne bouge
    assert err(planning.respond_event, ev, worker, True).status == 403                             # on ne valide pas sa propre demande
    assert err(planning.request_event, c, worker, {"kind": "absence", "date": "2027-01-20"}, today=START).code == "overlap"
    planning.respond_event(ev, owner, True)
    assert not shifts(c, date__range=("2027-01-18", "2027-01-22"), status="planned").exists()
    assert err(planning.respond_event, ev, owner, True).code == "not_open"
    tasks.run(START + timedelta(days=1))
    assert not shifts(c, date__range=("2027-01-18", "2027-01-22"), status="planned").exists()      # la régénération respecte le congé
    out = planning.request_event(c, worker, {"kind": "rest", "date": "2027-03-01"}, today=START + timedelta(days=1))
    assert planning.cancel_event(out, worker).status == "cancelled" and err(planning.cancel_event, out, owner).status == 403
    assert err(planning.request_event, c, worker, {"kind": "leave", "date": "2030-01-01"}, today=START).extra["fields"].get("date")      # hors durée du contrat
    assert err(planning.request_event, c, worker, {"kind": "leave", "date": "2026-12-01"}, today=START).extra["fields"].get("date")


def test_overtime_requires_both_parties_and_a_contract_rate_never_a_legal_one():
    owner, worker = person("ot_owner"), pro("ot_worker")
    c = make_contract(owner, worker, start=START, months=12, schedule=WEEK)
    tasks.run(START)
    ev = planning.request_event(c, worker, {"kind": "overtime", "date": "2027-01-12", "hours": "2.5", "note": "Fin de chantier"}, today=START)
    planning.respond_event(ev, owner, True)
    assert not InstallmentLine.objects.filter(kind="overtime").exists()                            # aucun taux au contrat : aucune valorisation inventée
    assert err(planning.request_event, c, worker, {"kind": "overtime", "date": "2027-01-13", "hours": "20"}, today=START).extra["fields"]["hours"]
    paid = make_contract(person("ot_owner2"), pro("ot_worker2"), start=START, months=12, schedule=WEEK, overtime_hourly_rate="4000")
    tasks.run(START)
    ev2 = planning.request_event(paid, paid.worker, {"kind": "overtime", "date": "2027-01-12", "hours": "2.5"}, today=START)
    assert not InstallmentLine.objects.filter(source_event=ev2).exists()
    planning.respond_event(ev2, paid.principal, True)
    line = InstallmentLine.objects.get(source_event=ev2)
    assert line.status == "accepted" and line.amount == Decimal("10000.00") and line.kind == "overtime"
    assert InstallmentLine.objects.filter(source_event=ev2).count() == 1


def test_attendance_is_declared_by_the_worker_and_confirmed_by_the_principal_without_any_location():
    owner, worker = person("at_owner"), pro("at_worker")
    c = make_contract(owner, worker, start=START, months=12, schedule=WEEK)
    tasks.run(START)
    shift = shifts(c, date=START).first()
    assert err(planning.declare_attendance, shift, owner, {}, today=START).status == 403           # seul le prestataire déclare
    future = shifts(c, date=START + timedelta(days=3)).first()
    assert err(planning.declare_attendance, future, worker, {}, today=START).code == "future_event"
    assert err(planning.declare_attendance, shift, worker, {"actual_start": "08:00"}, today=START).extra["fields"]
    shift = planning.declare_attendance(shift, worker, {"actual_start": "08:10", "actual_end": "12:05"}, today=START)
    assert shift.attendance_status == "declared" and shift.hours == Decimal("3.92")                # 08:10 → 12:05
    assert err(planning.respond_attendance, shift, worker, True).status == 403                     # le prestataire ne confirme pas sa propre présence
    shift = planning.respond_attendance(shift, owner, True)
    assert shift.attendance_status == "confirmed" and err(planning.declare_attendance, shift, worker, {}, today=START).code == "not_open"
    fields = {f.name for f in ScheduleEvent._meta.get_fields()}
    assert not any(token in name for name in fields for token in ("lat", "lng", "lon", "gps", "position", "coord"))   # JAMAIS de suivi de position


def test_replacement_needs_the_substitute_then_the_counterpart_and_attendance_goes_to_the_substitute():
    owner, worker, sub, unverified = person("rp_owner"), pro("rp_worker"), pro("rp_sub"), person("rp_unverified")
    c = make_contract(owner, worker, start=START, months=12, schedule=WEEK)
    tasks.run(START)
    target = shifts(c, date=START + timedelta(days=1)).first()
    assert err(planning.propose_replacement, c, worker, target.pk, unverified.pk).code == "worker_not_verified"
    assert err(planning.propose_replacement, c, worker, target.pk, worker.pk).code == "invalid"
    ev = planning.propose_replacement(c, worker, target.pk, sub.pk, "Rendez-vous médical")
    assert err(planning.respond_event, ev, owner, True).code == "replacement_pending"             # le remplaçant d'abord
    assert err(planning.respond_replacement, ev, owner, True).status == 404
    planning.respond_replacement(ev, sub, True)
    assert err(planning.respond_event, ev, worker, True).status == 403
    planning.respond_event(ev, owner, True)
    target.refresh_from_db()
    assert target.status == "replaced"
    ev.refresh_from_db()
    cal_sub = list(planning.calendar(c, sub, START, START + timedelta(days=30)))
    assert [e.pk for e in cal_sub] == [ev.pk]                                                      # le remplaçant ne voit que son remplacement
    assert len(list(planning.calendar(c, owner, START, START + timedelta(days=30)))) > 1
    assert err(planning.declare_attendance, ev, worker, {}, today=START + timedelta(days=1)).status == 403
    planning.declare_attendance(ev, sub, {}, today=START + timedelta(days=1))


def test_each_occurrence_becomes_one_booking_idempotently_and_a_leave_cancels_it():
    owner, worker = person("bk_owner"), pro("bk_worker")
    c = make_contract(owner, worker, start=START, months=6, schedule=[{"weekday": 0, "start": "08:00", "end": "10:00"}, {"weekday": 2, "start": "08:00", "end": "10:00"}], bookings_mode="per_occurrence")
    tasks.run(START)
    made = Booking.objects.filter(client=owner, handyman=worker).count()
    assert made == 3                                                                               # 7 jours : lun 4, mer 6, lun 11
    for _ in range(3):
        tasks.run(START)
    assert Booking.objects.filter(client=owner, handyman=worker).count() == made                   # idempotent
    assert Booking.objects.filter(client=owner, handyman=worker, status="confirmed").count() == made
    ev = planning.request_event(c, worker, {"kind": "absence", "date": "2027-01-06", "note": "Indisponible ce jour"}, today=START)
    planning.respond_event(ev, owner, True)
    assert Booking.objects.get(booking_date__date="2027-01-06").status == "cancelled"
    tasks.run(START + timedelta(days=1))
    assert Booking.objects.filter(client=owner, handyman=worker, status="confirmed").count() >= 2
    assert Booking.objects.filter(booking_date__date="2027-01-06", status="confirmed").count() == 0
    # Un emploi salarié ne génère jamais de réservations.
    from engagements.testing import allow_employment
    allow_employment()
    emp = make_contract(person("bk_owner2"), pro("bk_worker2"), start=START, months=6, schedule=WEEK, work_relationship="employment", legal_notice_ack=True, notice_period_days=30)
    tasks.run(START)
    assert not Booking.objects.filter(client=emp.principal).exists()
