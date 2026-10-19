"""Catalogue unique des métiers : `GET /handy/catalog/` (web, application mobile), arbre métier → prestation → offre, icônes normalisées,
métier actif jamais masqué faute d'offre, administration (visibilité, ordre, mise en avant), recherche par métier et droits d'écriture.

Cas de recette : Jardinage, Cuisine et Nounou (un métier sans offre ni prestation)."""
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from handy import catalog
from handy.models import Service, ServiceCategory
from handy.test_eligibility import artisan

User = get_user_model()
pytestmark = pytest.mark.django_db
URL = "/handy/catalog/"


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


def trade(name, slug, icon=None, **kw):
    return ServiceCategory.objects.create(name=name, slug=slug, icon=icon, **kw)


def prestation(parent, name, slug, **kw):
    return ServiceCategory.objects.create(name=name, slug=slug, parent=parent, **kw)


def offer(user, category, title="Prestation", active=True):
    return Service.objects.create(handyman=user, category=category, title=title, description="d", price_type="fixed", price=5000, is_active=active)


@pytest.fixture
def world():
    jardinage = trade("Jardinage", "jardinage", "fa-solid fa-tree", position=10, is_featured=True)
    fleurs = prestation(jardinage, "Entretien de fleurs", "entretien-de-fleurs", icon="fa-solid fa-seedling")
    elagage = prestation(jardinage, "Élagage léger", "elagage-leger")
    cuisine = trade("Cuisine", "cuisine", "fa-solid fa-utensils", position=20, is_featured=True)
    cours = prestation(cuisine, "Cours de cuisine", "cours-de-cuisine", icon="fa-solid fa-utensils")
    chef = prestation(cuisine, "Chef privé", "chef-prive")
    nounou = trade("Nounou", "nounou", "fa-solid fa-baby", position=30)               # actif, SANS prestation ni offre
    cachee = trade("Cachée", "cachee", is_active=False)
    prestation(cachee, "Invisible avec son métier", "invisible")
    prestation(cuisine, "Prestation masquée", "prestation-masquee", is_active=False)
    pro = artisan("cat_pro")
    offer(pro, fleurs, "Taille de rosiers")
    offer(pro, elagage, "Élagage d'un manguier")
    offer(pro, chef, "Dîner pour six")
    offer(pro, chef, "Brunch", active=False)                                          # inactive : jamais comptée
    return dict(jardinage=jardinage, fleurs=fleurs, elagage=elagage, cuisine=cuisine, cours=cours, chef=chef, nounou=nounou, cachee=cachee, pro=pro)


def get_catalog():
    r = APIClient().get(URL)
    assert r.status_code == 200
    return r, {i["slug"]: i for i in r.json()["results"]}


# ----------------------------------------------------------------------------------------------------------- l'endpoint

def test_the_catalog_is_public_and_exposes_the_agreed_fields(world):
    r, items = get_catalog()
    data = r.json()
    assert data["count"] == len(data["results"]) == 8 and "plomberie" in items and data["next"] is None and data["version"]
    j = items["jardinage"]
    assert {"id", "name", "slug", "parent", "icon", "icon_key", "position", "order", "is_active", "offers_count", "offers_total", "kind", "trade", "is_featured"} <= set(j)
    assert (j["id"], j["name"], j["parent"], j["kind"], j["icon_key"], j["is_active"]) == (world["jardinage"].pk, "Jardinage", None, "trade", "tree", True)
    assert items["entretien-de-fleurs"]["parent"] == world["jardinage"].pk and items["entretien-de-fleurs"]["kind"] == "service"
    assert items["entretien-de-fleurs"]["trade"] == world["jardinage"].pk
    assert "cat_pro" not in json.dumps(data) and "@" not in json.dumps(data)         # aucune donnée personnelle


def test_the_three_acceptance_trades_are_present_with_their_tree_icons_and_counts(world):
    _, items = get_catalog()
    assert [(items[s]["name"], items[s]["icon_key"]) for s in ("jardinage", "cuisine", "nounou")] == [("Jardinage", "tree"), ("Cuisine", "utensils"), ("Nounou", "baby")]
    assert {s for s, i in items.items() if i["parent"] == world["jardinage"].pk} == {"entretien-de-fleurs", "elagage-leger"}
    assert {s for s, i in items.items() if i["parent"] == world["cuisine"].pk} == {"cours-de-cuisine", "chef-prive"}      # la prestation masquée n'apparaît pas
    assert (items["jardinage"]["offers_count"], items["jardinage"]["offers_total"]) == (0, 2)     # les offres des prestations comptent pour le métier
    assert (items["cuisine"]["offers_count"], items["cuisine"]["offers_total"], items["chef-prive"]["offers_count"]) == (0, 1, 1)
    assert items["jardinage"]["services_count"] == 2 and items["jardinage"]["prestations_count"] == 2


def test_an_active_trade_is_never_hidden_because_it_has_no_offer(world):
    _, items = get_catalog()
    assert "nounou" in items and items["nounou"]["offers_total"] == 0 and items["nounou"]["prestations_count"] == 0 and items["nounou"]["is_active"] is True
    assert "cours-de-cuisine" in items and items["cours-de-cuisine"]["offers_total"] == 0     # une prestation active sans offre reste aussi visible


def test_a_hidden_trade_disappears_with_its_prestations_and_a_hidden_prestation_alone(world):
    _, items = get_catalog()
    assert "cachee" not in items and "invisible" not in items and "prestation-masquee" not in items
    ServiceCategory.objects.filter(pk=world["cachee"].pk).update(is_active=True)
    cache.clear()
    assert "cachee" in get_catalog()[1] and "invisible" in get_catalog()[1]


def test_order_is_position_then_name_with_prestations_right_after_their_trade(world):
    r, items = get_catalog()
    slugs = [i["slug"] for i in r.json()["results"]]
    assert slugs[:3] == ["jardinage", "elagage-leger", "entretien-de-fleurs"]                  # « Élagage » se range avec les E : ordre alphabétique français
    assert slugs.index("jardinage") < slugs.index("cuisine") < slugs.index("nounou")          # positions 10 < 20 < 30
    assert [i["order"] for i in r.json()["results"]] == list(range(len(slugs)))
    ServiceCategory.objects.filter(pk=world["nounou"].pk).update(position=1)
    cache.clear()
    assert [i["slug"] for i in APIClient().get(URL).json()["results"]][0] == "nounou"          # l'ordre se règle dans l'administration


def test_unpublished_offers_are_not_counted(world):
    from handy.models import HandymanProfile

    HandymanProfile.objects.filter(user=world["pro"]).update(is_approved=False)            # artisan non éligible : ses offres ne sont plus publiées
    cache.clear()
    _, items = get_catalog()
    assert items["jardinage"]["offers_total"] == 0 and items["cuisine"]["offers_total"] == 0 and "jardinage" in items       # le métier reste affiché


def test_etag_and_conditional_requests(world):
    c = APIClient()
    first = c.get(URL)
    etag = first["ETag"]
    assert etag.startswith('W/"') and "max-age" in first["Cache-Control"] and "stale-while-revalidate" in first["Cache-Control"]
    again = c.get(URL, HTTP_IF_NONE_MATCH=etag)
    assert again.status_code == 304 and again.content == b"" and again["ETag"] == etag
    trade("Coiffure", "coiffure")
    cache.clear()
    changed = c.get(URL, HTTP_IF_NONE_MATCH=etag)
    assert changed.status_code == 200 and changed["ETag"] != etag                            # le catalogue a changé : nouvelle version


def test_a_category_change_invalidates_the_cached_catalog(world):
    assert "nounou" in get_catalog()[1]
    ServiceCategory.objects.filter(pk=world["nounou"].pk).first().delete()                     # signal post_delete : cache vidé
    assert "nounou" not in get_catalog()[1]
    cat = ServiceCategory.objects.get(slug="cuisine")
    cat.is_featured = False
    cat.save()
    assert get_catalog()[1]["cuisine"]["is_featured"] is False


def test_the_endpoint_needs_no_authentication_and_ignores_a_bad_token(world):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer expired.token.value")
    assert c.get(URL).status_code == 200


def test_ids_are_the_existing_ones_and_nothing_is_recreated(world):
    before = dict(ServiceCategory.objects.values_list("slug", "id"))
    for _ in range(3):
        get_catalog()
    assert dict(ServiceCategory.objects.values_list("slug", "id")) == before


# ------------------------------------------------------------------------------------------------------------- icônes

@pytest.mark.parametrize("raw,slug,expected", [
    ("fa-solid fa-utensils", "", "utensils"), ("fas fa-bolt", "", "bolt"), ("fas fa-home", "", "house"), ("fa-solid fa-user-nurse", "", "user-nurse"),
    ("fa-solid fa-screwdriver-wrench", "", "screwdriver-wrench"), ("fas fa-trash-alt", "", "trash-can"), ("fa fa-fw fa-baby", "", "baby"), ("wrench", "", "wrench"),
    ("FA-SOLID FA-BABY", "", "baby"), (None, "jardinage", "seedling"), ("", "nounou", "baby"), (None, "inconnu", None), ("fa-solid", "", None), ("fas", "", None),
])
def test_icon_names_are_normalised_to_one_vocabulary(raw, slug, expected):
    assert catalog.icon_key(raw, slug) == expected


def test_every_default_and_alias_target_belongs_to_the_shared_vocabulary():
    assert set(catalog.DEFAULT_ICON_BY_SLUG.values()) <= set(catalog.ICON_KEYS)
    assert set(catalog.ALIASES.values()) <= set(catalog.ICON_KEYS)
    assert catalog.DEFAULT_ICON_KEY in catalog.ICON_KEYS and len(set(catalog.ICON_KEYS)) == len(catalog.ICON_KEYS)


def test_the_categories_list_exposes_the_same_icon_key_kind_and_order_fields(world):
    r = APIClient().get("/handy/categories/?page_size=100")
    rows = {i["slug"]: i for i in r.json()["results"]}
    assert rows["nounou"]["icon_key"] == "baby" and rows["nounou"]["kind"] == "trade" and rows["chef-prive"]["kind"] == "service"
    assert rows["jardinage"]["position"] == 10 and rows["jardinage"]["is_featured"] is True and "cachee" not in rows


# ------------------------------------------------------------------------------------------- recherche par métier

def test_choosing_a_trade_in_the_search_covers_its_prestations(world):
    c = APIClient()
    by_trade = c.get(f"/handy/services/?categories={world['jardinage'].pk}&page_size=50").json()
    assert {s["title"] for s in by_trade["results"]} == {"Taille de rosiers", "Élagage d'un manguier"}
    by_prestation = c.get(f"/handy/services/?categories={world['fleurs'].pk}&page_size=50").json()
    assert {s["title"] for s in by_prestation["results"]} == {"Taille de rosiers"}
    assert {s["title"] for s in c.get(f"/handy/services/?categories={world['cuisine'].pk}&page_size=50").json()["results"]} == {"Dîner pour six"}
    assert c.get(f"/handy/services/?categories={world['nounou'].pk}&page_size=50").json()["count"] == 0


def test_the_single_category_filter_nearby_and_featured_artisans_follow_the_same_tree(world):
    c = APIClient()
    listing = c.get(f"/handy/services/?category={world['jardinage'].pk}&page_size=50").json()
    assert {s["title"] for s in listing["results"]} == {"Taille de rosiers", "Élagage d'un manguier"}            # `category` (application mobile) couvre les prestations
    assert {s["title"] for s in c.get(f"/handy/services/?category={world['elagage'].pk}&page_size=50").json()["results"]} == {"Élagage d'un manguier"}
    by_name = c.get("/handy/services/?category__name=jardinage&page_size=50").json()                                # application mobile : filtre par nom
    assert {s["title"] for s in by_name["results"]} == {"Taille de rosiers", "Élagage d'un manguier"}
    assert c.get("/handy/services/?category__name=Entretien%20de%20fleurs&page_size=50").json()["count"] == 1
    assert c.get("/handy/services/?category=abc").status_code == 400                                                # valeur invalide : toujours refusée
    near = c.get(f"/handy/services/nearby/?lat=5.36&lng=-4.0083&radius_km=50&category_id={world['jardinage'].pk}&page_size=50").json()
    assert {s["title"] for s in near["results"]} == {"Taille de rosiers", "Élagage d'un manguier"}
    featured = c.get(f"/handy/handymen/featured/?category={world['cuisine'].pk}").json()
    assert [a["id"] for a in featured["results"]] and c.get(f"/handy/handymen/featured/?category={world['nounou'].pk}").json()["count"] == 0


def test_descendants_follow_active_prestations_only(world):
    assert catalog.with_descendants([world["cuisine"].pk]) == {world["cuisine"].pk, world["cours"].pk, world["chef"].pk}
    assert catalog.with_descendants([]) == set()


# ----------------------------------------------------------------------------------------------- droits d'écriture

def test_only_staff_can_write_categories_through_the_public_api(world):
    member = User.objects.create_user("cat_member", "m@x.test", "pass1234")
    staff = User.objects.create_user("cat_staff", "s@x.test", "pass1234", is_staff=True)
    payload = {"name": "Pirate", "slug": "pirate"}
    for client in (APIClient(), _as(member)):
        assert client.post("/handy/categories/", payload, format="json").status_code in (401, 403)
        assert client.patch(f"/handy/categories/{world['nounou'].pk}/", {"is_featured": True, "position": 1}, format="json").status_code in (401, 403)
        assert client.delete(f"/handy/categories/{world['nounou'].pk}/").status_code in (401, 403)
    assert not ServiceCategory.objects.filter(slug="pirate").exists() and ServiceCategory.objects.get(pk=world["nounou"].pk).position == 30
    assert _as(staff).patch(f"/handy/categories/{world['nounou'].pk}/", {"is_featured": True, "position": 5}, format="json").status_code == 200
    assert ServiceCategory.objects.get(pk=world["nounou"].pk).is_featured is True
    assert APIClient().get("/handy/categories/").status_code == 200                           # la lecture reste publique


def _as(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


# --------------------------------------------------------------------------------------------- administration Django

@pytest.fixture
def admin_client(client):
    client.force_login(User.objects.create_superuser("cat_root", "root@x.test", "pass1234"))
    return client


def test_admin_lists_levels_filters_orders_and_edits_in_place(world, admin_client):
    page = admin_client.get(reverse("admin:handy_servicecategory_changelist"))
    assert page.status_code == 200
    html = page.content.decode()
    assert "Métier" in html and "Prestation" in html and "Offres actives" in html
    only_trades = admin_client.get(reverse("admin:handy_servicecategory_changelist") + "?kind=trade").content.decode()
    assert "Jardinage" in only_trades and "Entretien de fleurs" not in only_trades
    one_trade = admin_client.get(reverse("admin:handy_servicecategory_changelist") + f"?trade={world['cuisine'].pk}").content.decode()
    assert "Chef privé" in one_trade and "Entretien de fleurs" not in one_trade


def test_admin_actions_feature_hide_and_show_and_refresh_the_catalog(world, admin_client):
    url = reverse("admin:handy_servicecategory_changelist")
    ids = [str(world["nounou"].pk)]

    def act(action):
        return admin_client.post(url, {"action": action, "_selected_action": ids}, follow=True)

    assert act("feature").status_code == 200 and get_catalog()[1]["nounou"]["is_featured"] is True
    act("unfeature")
    assert get_catalog()[1]["nounou"]["is_featured"] is False
    act("hide")
    assert "nounou" not in get_catalog()[1] and ServiceCategory.objects.filter(pk=world["nounou"].pk).exists()      # masqué, jamais supprimé
    act("show")
    assert "nounou" in get_catalog()[1]


def test_admin_validates_icons_and_prevents_cycles(world, admin_client):
    change = reverse("admin:handy_servicecategory_change", args=[world["nounou"].pk])
    form = {"name": "Nounou", "slug": "nounou", "description": "", "is_active": "on", "position": 30, "parent": ""}
    bad = admin_client.post(change, {**form, "icon": "fa-solid fa-not-an-icon"})
    assert bad.status_code == 200 and "non reconnue" in bad.content.decode()
    good = admin_client.post(change, {**form, "icon": "fa-solid fa-child"})
    assert good.status_code == 302 and ServiceCategory.objects.get(pk=world["nounou"].pk).icon == "fa-solid fa-child"
    cycle = admin_client.post(reverse("admin:handy_servicecategory_change", args=[world["jardinage"].pk]),
                              {"name": "Jardinage", "slug": "jardinage", "parent": world["fleurs"].pk, "is_active": "on", "position": 10, "icon": "fa-solid fa-tree"})
    assert cycle.status_code == 200 and "sous elle-même" in cycle.content.decode()


# ------------------------------------------------------------------------------------------------ Back-Office

def test_back_office_manages_order_featured_and_shows_the_kind(world):
    from backoffice import rbac
    from django.contrib.auth.models import Group

    rbac.ensure_roles()
    ops = User.objects.create_user("cat_ops", "o@x.test", "pass1234", is_staff=True)
    ops.groups.add(Group.objects.get(name=rbac.role_group_name("ops")))
    c = _as(ops)
    rows = {r["slug"]: r for r in c.get("/handy/backoffice/services/categories/").json()["results"]}
    assert rows["jardinage"]["kind"] == "trade" and rows["entretien-de-fleurs"]["kind"] == "service" and rows["nounou"]["icon_key"] == "baby"
    assert rows["jardinage"]["icon_known"] is True and rows["jardinage"]["position"] == 10
    ok = c.patch(f"/handy/backoffice/services/categories/{world['nounou'].pk}/", {"position": 7, "is_featured": True}, format="json")
    assert ok.status_code == 200 and (ok.json()["position"], ok.json()["is_featured"]) == (7, True)
    assert c.patch(f"/handy/backoffice/services/categories/{world['nounou'].pk}/", {"position": -3}, format="json").status_code == 400
    assert c.patch(f"/handy/backoffice/services/categories/{world['nounou'].pk}/", {"position": "abc"}, format="json").status_code == 400
    created = c.post("/handy/backoffice/services/categories/", {"name": "Coiffure", "slug": "coiffure", "position": 40, "is_featured": True}, format="json")
    assert created.status_code == 201 and created.json()["position"] == 40 and created.json()["is_featured"] is True
    assert "coiffure" in get_catalog()[1]


# --------------------------------------------------------------------------------------- migration non destructive

def test_the_migration_keeps_ids_and_marks_only_existing_historic_roots():
    from importlib import import_module

    from django.apps import apps

    plomberie = trade("Plomberie", "plomberie", position=100)
    peinture_child = prestation(plomberie, "Peinture", "peinture")                         # un slug historique mais SOUS-catégorie : jamais marqué
    inactive = trade("Climatisation", "climatisation", is_active=False)
    other = trade("Cuisine", "cuisine")
    ids = dict(ServiceCategory.objects.values_list("slug", "id"))
    import_module("handy.migrations.0050_service_category_order_featured").keep_historic_selection(apps, None)
    after = {c.slug: c for c in ServiceCategory.objects.all()}
    assert dict((s, c.pk) for s, c in after.items()) == ids
    assert (after["plomberie"].is_featured, after["plomberie"].position) == (True, 10)
    assert after["peinture"].is_featured is False and after["climatisation"].is_featured is False and after["cuisine"].is_featured is False
