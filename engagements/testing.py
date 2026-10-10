"""Utilitaires de test partagés des engagements (aucun usage en production)."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model

from engagements.models import EngagementContract, EngagementRule
from engagements.services import contracts
from handy.models import ServiceCategory
from handy.test_eligibility import artisan

User = get_user_model()


def person(name, **kw):
    return User.objects.create_user(name, f"{name}@x.test", "pass1234", user_type="client", is_verified=True, first_name=name.title(), last_name="Test", **kw)


def pro(name):
    return artisan(name)


def category(slug="plomberie", name="Plomberie"):
    return ServiceCategory.objects.get_or_create(slug=slug, defaults={"name": name})[0]


def allow_employment(cat=None):
    cat = cat or category()
    EngagementRule.objects.update_or_create(category=cat, defaults=dict(allow_employment=True, is_default=False))
    return cat


WEEK = [{"weekday": d, "start": "08:00", "end": "12:00"} for d in range(0, 5)]   # lundi-vendredi, 4 h


def contract_data(worker, *, start, months=12, amount="150000", period="monthly", schedule=None, cat=None, **over):
    cat = cat or category()
    from engagements.dates import add_months

    end = None if months is None else add_months(start, months) - timedelta(days=1)
    data = dict(worker=worker.pk, title="Entretien des locaux", description="Nettoyage et petites réparations.", conditions="Selon l'accord des parties.",
                category_id=cat.pk, mission_type="long_term", work_relationship="independent", start_date=start, end_date=end,
                amount=amount, period=period, payment_day=5, notice_period_days=7, location_city="Abidjan",
                location_address="Rue des Jardins 12", schedule=schedule if schedule is not None else [])
    data.update(over)
    return data


def make_contract(principal, worker, *, start, today=None, activate=True, **over) -> EngagementContract:
    """Brouillon → proposition → acceptation des deux parties (→ en cours si le début est atteint)."""
    today = today or start
    c = contracts.create_draft(principal, contract_data(worker, start=start, **over), today=today)
    contracts.propose(c, principal, today=today)
    c.refresh_from_db()
    contracts.accept(c, worker, c.terms_hash, today=today)
    c.refresh_from_db()
    return c
