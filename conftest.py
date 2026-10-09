"""Réglages pytest communs à tout le dépôt.

Règle d'éligibilité (handy/eligibility.py) : stricte en exécution réelle et dans
test_eligibility.py. Les suites plus anciennes fabriquent des artisans « approuvés » sans KYC
ni profil complet : elles tournent avec la règle de publication d'avant (approuvé + actif) tant
que leurs fixtures n'ont pas migré vers `handy.test_eligibility.make_eligible`.
"""
import pytest


@pytest.fixture(autouse=True)
def _legacy_publication_rule(request, monkeypatch):
    if request.node.get_closest_marker("strict_eligibility") or "test_eligibility" in request.node.nodeid:
        return
    from handy import eligibility

    monkeypatch.setattr(eligibility, "STRICT", False)
