"""Référentiel des métiers (familles → métiers → prestations, synonymes) : application idempotente, aucun doublon, données existantes
préservées, catalogue public, recherche par synonyme / famille / localisation, artisan multi-spécialités et « J'ai une panne »."""
from collections import Counter

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from handy import catalog, catalog_seed
from handy.models import CatalogFamily, HandymanProfile, Service, ServiceCategory
from handy.test_eligibility import artisan

pytestmark = pytest.mark.django_db


def prestations_total():
    return sum(len(t.prestations) for t in catalog_seed.TRADES)


def test_reference_is_applied_once_and_reapplying_changes_nothing():
    first = catalog_seed.apply()
    assert first["families_created"] == len(catalog_seed.FAMILIES) == 11
    assert first["trades_created"] == len(catalog_seed.TRADES) and first["prestations_created"] == prestations_total()
    snapshot = sorted(ServiceCategory.objects.values_list("id", "slug", "name", "parent_id", "family_id", "keywords"))
    second = catalog_seed.apply()
    assert {k: v for k, v in second.items() if k.endswith("created") or k.endswith("completed") or k == "trades_attached"} == {}
    assert sorted(ServiceCategory.objects.values_list("id", "slug", "name", "parent_id", "family_id", "keywords")) == snapshot
    assert CatalogFamily.objects.count() == 11


def test_structure_family_trade_prestation_without_duplicates_and_with_known_icons():
    catalog_seed.apply()
    it = CatalogFamily.objects.get(slug="informatique-numerique")
    assert it.name == "Informatique & Numérique" and it.trades.count() == 12
    assert set(it.trades.values_list("slug", flat=True)) >= {"maintenance-informatique", "reseaux-wifi", "developpement-web-mobile", "cybersecurite",
                                                             "videosurveillance", "telephonie", "bureautique", "cloud-serveurs", "design-numerique",
                                                             "marketing-digital", "formation-informatique", "domotique"}
    repair_families = {t.family for t in catalog_seed.TRADES if t.family != "informatique-numerique"}
    assert len(repair_families) <= 12                                       # navigation compacte pour les métiers de réparation
    for trade in ServiceCategory.objects.filter(parent__isnull=True):
        assert trade.family_id is not None
        names = [catalog_seed.fold(n) for n in trade.children.values_list("name", flat=True)]
        assert names and len(names) == len(set(names))                     # aucune prestation en double dans un métier
        assert not trade.children.filter(children__isnull=False).exists()   # trois niveaux, jamais plus
    assert all(len(s) <= 50 for s in ServiceCategory.objects.values_list("slug", flat=True))
    for f in catalog_seed.FAMILIES:
        assert catalog.icon_known(catalog.icon_key(f.icon)), f.icon
    for t in catalog_seed.TRADES:
        assert catalog.icon_known(catalog.icon_key(t.icon)), t.icon


def test_existing_trades_profiles_and_offers_are_preserved_and_reused():
    plumbing = ServiceCategory.objects.create(name="Plomberie", slug="plomberie", icon="fas fa-faucet", position=5, is_featured=True, keywords="plombier")
    leak = ServiceCategory.objects.create(name="réparation de fuite d'eau", slug="fuite", parent=plumbing)
    custom = ServiceCategory.objects.create(name="Fuite de WC", slug="fuite-wc", parent=plumbing)
    phones = ServiceCategory.objects.create(name="Réparation smartphone", slug="reparation-smartphone", is_active=False)
    appliance = ServiceCategory.objects.create(name="Électroménager", slug="electro")
    garden_family = CatalogFamily.objects.create(name="Extérieur", slug="exterieur")
    garden = ServiceCategory.objects.create(name="Jardinage", slug="jardinage", family=garden_family)
    worker = artisan("plombier_historique")
    profile = HandymanProfile.objects.get(user=worker)
    profile.skills.set([plumbing, custom])
    offer = Service.objects.create(handyman=worker, category=custom, title="WC qui fuit", description="d", price_type="fixed", price=5000)

    stats = catalog_seed.apply()

    plumbing.refresh_from_db()
    assert (plumbing.name, plumbing.position, plumbing.is_featured, plumbing.icon) == ("Plomberie", 5, True, "fas fa-faucet")
    assert plumbing.family.slug == "electricite-plomberie" and plumbing.keywords.startswith("plombier,")
    folded = Counter(catalog_seed.fold(n) for n in plumbing.children.values_list("name", flat=True))
    assert max(folded.values()) == 1 and ServiceCategory.objects.filter(pk__in=[leak.pk, custom.pk]).count() == 2
    assert ServiceCategory.objects.get(pk=leak.pk).name == "réparation de fuite d'eau"            # jamais renommée
    assert not ServiceCategory.objects.filter(slug__in=["telephones-tablettes", "electromenager"]).exists()  # métiers réutilisés
    phones.refresh_from_db()
    assert phones.is_active is False and phones.children.count() == 8                             # masqué par l'admin : le reste
    assert ServiceCategory.objects.get(pk=appliance.pk).children.filter(name__icontains="réfrigérateur").exists()
    garden.refresh_from_db()
    assert garden.family_id == garden_family.pk                                                    # famille choisie par l'admin conservée
    assert set(profile.skills.values_list("pk", flat=True)) == {plumbing.pk, custom.pk}
    offer.refresh_from_db()
    assert offer.category_id == custom.pk and offer.is_active
    assert stats["trades_reused"] >= 4


def test_sync_catalog_command_is_safe_to_run_twice(capsys):
    call_command("sync_catalog", "--dry-run")
    assert ServiceCategory.objects.count() == 0 and "Simulation" in capsys.readouterr().out
    call_command("sync_catalog")
    n = ServiceCategory.objects.count()
    call_command("sync_catalog")
    out = capsys.readouterr().out
    assert ServiceCategory.objects.count() == n and "0 métiers créés" in out.splitlines()[-1]


def test_public_catalog_exposes_families_and_synonyms():
    catalog_seed.apply()
    hidden = CatalogFamily.objects.get(slug="couture-cordonnerie")
    hidden.is_active = False
    hidden.save()
    data = APIClient().get("/handy/catalog/").json()
    families = data["families"]
    assert families[0]["name"] == "Informatique & Numérique" and len(families[0]["trades"]) == 12 and families[0]["icon_key"] == "laptop"
    assert "couture-cordonnerie" not in [f["slug"] for f in families]
    items = {i["slug"]: i for i in data["results"]}
    assert items["cordonnerie"]["family"] is None                                                  # famille masquée : métier « sans famille »
    fridge = next(i for i in data["results"] if i["name"] == "Réparation de réfrigérateur et congélateur")
    assert fridge["family"] == items["electromenager"]["family"] and "frigo" in fridge["keywords"]
    assert all(isinstance(i["keywords"], list) for i in data["results"])


def _published(user, category, title, commune):
    profile = HandymanProfile.objects.get(user=user)
    profile.commune = commune
    profile.save()
    return Service.objects.create(handyman=user, category=category, title=title, description="Intervention à domicile.", price_type="fixed", price=10000)


def test_search_by_synonym_family_and_location_with_a_multi_skilled_artisan():
    catalog_seed.apply()
    fridge = ServiceCategory.objects.get(name="Réparation de réfrigérateur et congélateur")
    screen = ServiceCategory.objects.get(name="Remplacement d'écran", parent__slug="telephones-tablettes")
    clim = ServiceCategory.objects.get(name="Recharge de gaz")
    multi, other = artisan("tech_polyvalent"), artisan("reparateur_tel")
    a = _published(multi, fridge, "Dépannage froid", "Cocody")
    b = _published(multi, clim, "Climatisation", "Cocody")               # plusieurs spécialités pour un même artisan
    c = _published(other, screen, "Écrans", "Yopougon")
    HandymanProfile.objects.get(user=multi).skills.set([fridge, clim])
    api = APIClient()

    def ids(query):
        return {r["id"] for r in api.get(f"/handy/services/?{query}&page_size=50").json()["results"]}

    assert a.pk in ids("search=frigo") and c.pk not in ids("search=frigo")  # synonyme populaire (« frigoriste » couvre aussi la clim)
    assert ids("search=ne refroidit plus") == {a.pk, b.pk}                 # panne décrite : frigo et clim
    assert ids("search=vitre cassée") == {c.pk}
    assert ids("family=electromenager-froid") == {a.pk, b.pk}
    family_id = CatalogFamily.objects.get(slug="telephones-electronique").pk
    assert ids(f"family={family_id}") == {c.pk}
    assert ids("family=electromenager-froid&commune=Yopougon") == set()
    assert ids(f"categories={fridge.parent_id}&commune=Cocody") == {a.pk}   # métier → ses prestations, filtré par localisation
    assert ids("family=inconnue") == set()


@pytest.mark.parametrize("text, expected, trade", [
    ("Mon frigo ne refroidit plus depuis hier", "Réparation de réfrigérateur et congélateur", "electromenager"),
    ("L'écran de mon téléphone est cassé", "Remplacement d'écran", "telephones-tablettes"),
    ("Ma clim coule dans la chambre", "Dépannage de climatiseur", "climatisation"),
    ("Il y a une fuite d'eau sous l'évier", "Réparation de fuite d'eau", "plomberie"),
    ("Plus de courant, le disjoncteur saute", "Dépannage de panne électrique", "electricite"),
    ("Ma voiture ne démarre pas ce matin", None, None),
    ("Je dois faire réparer le talon de ma chaussure", "Réparation de chaussures", "cordonnerie"),
    ("Des virus et des publicités partout sur mon ordinateur", "Suppression de virus et nettoyage logiciel", "maintenance-informatique"),
    ("Mon pc est très lent", "Diagnostic et réparation d'ordinateur", "maintenance-informatique"),
])
def test_i_have_a_breakdown_finds_the_relevant_prestations(text, expected, trade):
    catalog_seed.apply()
    r = APIClient().get("/handy/catalog/match/", {"q": text})
    assert r.status_code == 200 and r["Cache-Control"] == "no-store"
    results = r.json()["results"]
    assert results
    if expected is None:                                                    # « ne démarre pas » : électricité auto ou dépannage, au choix
        assert {results[0]["trade_slug"]} <= {"mecanique-auto", "depannage-remorquage"}
        return
    assert results[0]["name"] == expected and results[0]["trade_slug"] == trade, [(x["name"], x["score"]) for x in results]


def test_i_have_a_breakdown_without_useful_words_returns_nothing():
    catalog_seed.apply()
    for text in ("", "   ", "bonjour j'ai un problème svp", "x" * 400):
        body = APIClient().get("/handy/catalog/match/", {"q": text}).json()
        assert body["results"] == [] and body["trades"] == []
