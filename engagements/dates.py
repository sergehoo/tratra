"""Arithmétique de dates des engagements pluriannuels : tout est calculé à partir de la date de début (jamais en
incrémentant de proche en proche), pour qu'un contrat commencé un 31 janvier retombe sur le 31 mars après un 28 février."""
import calendar
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Iterable, List, Optional

WEEKDAYS = list(range(7))  # lundi = 0


def add_months(d: date, months: int) -> date:
    index = d.year * 12 + (d.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def period_bounds(start: date, k: int):
    """Période mensuelle n° k (à partir de 0) ancrée sur la date de début : [début + k mois, début + k+1 mois − 1 jour]."""
    return add_months(start, k), add_months(start, k + 1) - timedelta(days=1)


def next_payment_date(period_end: date, payment_day: Optional[int]) -> date:
    """Première date ≥ fin de période dont le quantième est le jour de paiement (ramené au dernier jour des mois courts)."""
    if not payment_day:
        return period_end
    for offset in (0, 1):
        year, month = divmod(period_end.year * 12 + (period_end.month - 1) + offset, 12)
        month += 1
        candidate = date(year, month, min(payment_day, calendar.monthrange(year, month)[1]))
        if candidate >= period_end:
            return candidate
    return period_end  # inatteignable


def daterange(start: date, end: date) -> Iterable[date]:
    for i in range((end - start).days + 1):
        yield start + timedelta(days=i)


def parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def hours_between(start: time, end: time) -> Decimal:
    delta = datetime.combine(date.min, end) - datetime.combine(date.min, start)
    return (Decimal(delta.total_seconds()) / Decimal(3600)).quantize(Decimal("0.01"))


def weekly_hours(schedule: List[dict]) -> Decimal:
    total = Decimal("0")
    for slot in schedule or []:
        total += hours_between(parse_hhmm(slot["start"]), parse_hhmm(slot["end"]))
    return total.quantize(Decimal("0.01"))
