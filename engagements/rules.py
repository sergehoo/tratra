"""Règles de la plateforme pour les engagements, résolues par catégorie (règle de la catégorie, sinon règle générale,
sinon valeurs d'usine). Ce sont des règles de FONCTIONNEMENT de Tratra, modifiables en Back-Office ; elles ne constituent
ni un avis juridique ni un calcul légal : l'emploi salarié est désactivé tant qu'une règle ne l'autorise pas."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from engagements.models import EngagementRule


@dataclass(frozen=True)
class Rules:
    allow_recurring: bool = True
    allow_long_term: bool = True
    allow_employment: bool = False
    max_duration_months: int = 60
    min_notice_days_independent: int = 7
    min_notice_days_employment: int = 30
    commission_percent_independent: Decimal = Decimal("0")
    commission_percent_employment: Decimal = Decimal("0")
    commission_payer: str = "principal"
    max_advance_percent: int = 50
    late_grace_days: int = 5
    min_days_for_evaluation: int = 30
    evaluation_interval_days: int = 90
    evaluation_edit_days: int = 7
    source: str = "factory"

    def min_notice_days(self, relationship: str) -> int:
        return self.min_notice_days_employment if relationship == "employment" else self.min_notice_days_independent

    def commission_percent(self, relationship: str) -> Decimal:
        return self.commission_percent_employment if relationship == "employment" else self.commission_percent_independent

    def allows(self, mission_type: str) -> bool:
        return self.allow_long_term if mission_type == "long_term" else self.allow_recurring


FIELDS = [f for f in Rules.__dataclass_fields__ if f != "source"]
# Bornes de validation côté Back-Office (même source pour l'interface et le serveur).
HORIZON_PERIODS = 3     # échéances générées à l'avance : les 3 prochaines périodes
SHIFT_HORIZON_DAYS = 60
BOOKING_HORIZON_DAYS = 7


def _from_model(rule: EngagementRule, source: str) -> Rules:
    return Rules(**{f: getattr(rule, f) for f in FIELDS}, source=source)


def rules_for(category) -> Rules:
    category_id = getattr(category, "pk", category)
    if category_id is not None:
        specific = EngagementRule.objects.filter(category_id=category_id, active=True).first()
        if specific is not None:
            return _from_model(specific, f"category:{category_id}")
    default = EngagementRule.objects.filter(is_default=True, active=True).first()
    return _from_model(default, "default") if default is not None else Rules()


def rules_payload(rules: Rules) -> dict:
    return {**{f: (str(getattr(rules, f)) if isinstance(getattr(rules, f), Decimal) else getattr(rules, f)) for f in FIELDS}, "source": rules.source}
