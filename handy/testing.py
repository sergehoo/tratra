"""Aides de test partagées (jamais importées par le code de production).

`make_eligible` complète un profil artisan pour qu'il satisfasse TOUTE la règle d'éligibilité
(handy/eligibility.py) : à appeler dans les fixtures des tests qui ont besoin d'un artisan
publié ou réservable. Non destructif : ne remplace pas ce que le test a déjà renseigné
(commune, spécialités, présentation…).
"""
from handy.models import HandymanDocument, ServiceCategory


def make_eligible(profile, *, category=None):
    profile.is_approved = True
    profile.bio = profile.bio or "Plombier depuis dix ans."
    profile.experience_years = profile.experience_years or 10
    profile.photo = profile.photo or "profile_pics/test.jpg"
    profile.commune = profile.commune or "Cocody"
    profile.save()
    if not profile.skills.exists():
        # Catégorie neutre : n'interfère avec aucun filtre de catégorie des tests.
        profile.skills.add(category or ServiceCategory.objects.get_or_create(
            slug="eligibility-skill", defaults={"name": "Spécialité de test", "is_active": False})[0])
    HandymanDocument.objects.get_or_create(
        handyman=profile, document_type="id_card", defaults={"file": "kyc/test.pdf", "status": "approved"})
    HandymanDocument.objects.filter(handyman=profile, document_type="id_card").update(status="approved")
    return profile
