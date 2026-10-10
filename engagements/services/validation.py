"""Validation partagée des besoins publiés et des contrats : erreurs regroupées par champ (formulaires Web et Flutter)."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from django.utils.dateparse import parse_date

from engagements.dates import hours_between, parse_hhmm, weekly_hours
from engagements.models import EngagementPosting
from engagements.rules import Rules
from engagements.services.common import EngagementError

CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_AMOUNT = Decimal("1000000000")
PERIODS = {k for k, _ in EngagementPosting.PERIODS}
MISSION_TYPES = {k for k, _ in EngagementPosting.MISSION_TYPES}
RELATIONSHIPS = {k for k, _ in EngagementPosting.RELATIONSHIPS}


class Validator:
    """Accumule les erreurs par champ puis les lève ensemble (réponse 400 `invalid` avec `fields`)."""

    def __init__(self):
        self.fields: Dict[str, str] = {}

    def err(self, field: str, message: str) -> None:
        self.fields.setdefault(field, message)

    def raise_if(self) -> None:
        if self.fields:
            raise EngagementError("invalid", "Formulaire invalide : corrigez les champs signalés.", 400, fields=self.fields)

    def text(self, data: dict, field: str, *, label: str, max_len: int, min_len: int = 0, required: bool = False, default: str = "") -> str:
        raw = data.get(field, default)
        value = CONTROL.sub("", str(raw if raw is not None else "")).strip()
        if required and not value:
            self.err(field, f"{label} : champ obligatoire.")
        elif value and len(value) < min_len:
            self.err(field, f"{label} : {min_len} caractères au minimum.")
        elif len(value) > max_len:
            self.err(field, f"{label} : {max_len} caractères au maximum.")
        return value

    def amount(self, data: dict, field: str, *, label: str, required: bool = False, allow_zero: bool = False) -> Optional[Decimal]:
        raw = data.get(field)
        if raw in (None, ""):
            if required:
                self.err(field, f"{label} : montant obligatoire.")
            return None
        try:
            value = Decimal(str(raw).replace(",", ".").replace(" ", "")).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            self.err(field, f"{label} : montant invalide.")
            return None
        if value < 0 or (value == 0 and not allow_zero) or value > MAX_AMOUNT:
            self.err(field, f"{label} : montant hors limites.")
            return None
        return value

    def date(self, data: dict, field: str, *, label: str, required: bool = False) -> Optional[date]:
        raw = data.get(field)
        if raw in (None, ""):
            if required:
                self.err(field, f"{label} : date obligatoire.")
            return None
        if isinstance(raw, datetime):
            return raw.date()
        if isinstance(raw, date):
            return raw
        value = parse_date(str(raw)[:10]) if raw else None
        if value is None:
            self.err(field, f"{label} : date invalide (AAAA-MM-JJ).")
        return value

    def integer(self, data: dict, field: str, *, label: str, lo: int, hi: int, default: Optional[int] = None) -> Optional[int]:
        raw = data.get(field, default)
        if raw in (None, ""):
            return default
        try:
            value = int(raw)
        except (TypeError, ValueError):
            self.err(field, f"{label} : nombre entier invalide.")
            return default
        if not (lo <= value <= hi):
            self.err(field, f"{label} : valeur attendue entre {lo} et {hi}.")
            return default
        return value

    def choice(self, data: dict, field: str, *, label: str, allowed, default: Optional[str] = None) -> Optional[str]:
        value = data.get(field, default)
        if value not in allowed:
            self.err(field, f"{label} : valeur non reconnue.")
            return default
        return value

    def schedule(self, data: dict, field: str = "schedule") -> List[dict]:
        raw = data.get(field) or []
        if not isinstance(raw, list) or len(raw) > 21:
            self.err(field, "Planning : liste de créneaux invalide (21 au plus).")
            return []
        slots, seen = [], {}
        for slot in raw:
            try:
                weekday = int(slot["weekday"])
                start, end = parse_hhmm(str(slot["start"])), parse_hhmm(str(slot["end"]))
            except (KeyError, TypeError, ValueError):
                self.err(field, "Planning : chaque créneau a un jour (0 = lundi … 6 = dimanche), un début et une fin « HH:MM ».")
                return []
            if not (0 <= weekday <= 6) or end <= start:
                self.err(field, "Planning : jour hors 0-6 ou fin avant le début.")
                return []
            for other in seen.get(weekday, []):
                if start < other[1] and end > other[0]:
                    self.err(field, "Planning : deux créneaux se chevauchent le même jour.")
                    return []
            seen.setdefault(weekday, []).append((start, end))
            slots.append({"weekday": weekday, "start": f"{start:%H:%M}", "end": f"{end:%H:%M}"})
        return sorted(slots, key=lambda s: (s["weekday"], s["start"]))


def duration_months(start: Optional[date], end: Optional[date]) -> Optional[int]:
    if not start or not end:
        return None
    return (end.year - start.year) * 12 + (end.month - start.month) + (1 if end.day >= start.day else 0)


def check_common_terms(v: Validator, *, rules: Rules, mission_type, relationship, start, end, ack: bool, auto_renew=False, renewal_months=None) -> None:
    """Règles communes besoin / contrat : types autorisés par catégorie, emploi salarié, durée maximale, renouvellement."""
    if mission_type and not rules.allows(mission_type):
        v.err("mission_type", "Ce type de mission n'est pas ouvert pour cette catégorie.")
    if relationship == "employment":
        if not rules.allow_employment:
            v.err("work_relationship", "L'emploi salarié n'est pas ouvert pour cette catégorie : choisissez une prestation indépendante.")
        elif not ack:
            v.err("employment_notice_ack", "Reconnaissez que Tratra n'établit ni ne contrôle le contrat de travail légal.")
    if start and end:
        if end < start:
            v.err("end_date", "La fin ne peut pas précéder le début.")
        else:
            months = duration_months(start, end)
            if months and months > rules.max_duration_months:
                v.err("end_date", f"Durée maximale : {rules.max_duration_months} mois pour cette catégorie.")
    if auto_renew and not renewal_months:
        v.err("renewal_term_months", "Indiquez la durée de chaque renouvellement.")
    if auto_renew and not end:
        v.err("auto_renew", "Un contrat à durée indéterminée n'a pas besoin de renouvellement automatique.")


def derived_hours(schedule: List[dict], hours) -> Optional[Decimal]:
    return Decimal(str(hours)) if hours not in (None, "") else (weekly_hours(schedule) or None)


__all__ = ["Validator", "check_common_terms", "derived_hours", "duration_months", "hours_between"]
