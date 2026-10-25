"""Contrôles de qualité d'un contrat AVANT sa proposition et son scellement : avertissements, jamais de blocage ni de réécriture.

  - missions non décrites ;
  - missions sans aucun rapport avec le métier choisi (vocabulaire du catalogue : noms et synonymes du métier, de la prestation et des
    prestations du métier) — ex. « Nettoyage et petites réparations » pour le métier « Nounou »."""
from typing import List

from handy import catalog


def coherence_warnings(contract) -> List[str]:
    warnings: List[str] = []
    missions = (contract.description or "").strip()
    if not missions:
        warnings.append("Missions non décrites : précisez ce que le professionnel fera ; elles figurent dans le contrat.")
        return warnings
    category = contract.category
    vocab = catalog.category_terms(category)
    words = set(catalog.terms(f"{missions} {contract.title or ''}"))
    if vocab and not any(catalog.related(t, w) for t in vocab for w in words):
        trade = category.parent if category.parent_id else category
        name = f"{trade.name} › {category.name}" if category.parent_id else category.name
        warnings.append(f"Les missions décrites ne semblent pas correspondre au métier « {name} » : vérifiez le métier choisi ou la description "
                        "des missions avant de proposer le contrat.")
    return warnings
