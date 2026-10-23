"""Badges Google Play / App Store du site : liens configurés dans l'administration Django (configuration unique), validés
strictement (fiche officielle, HTTPS, hôte exact, aucun paramètre de redirection) et exposés en lecture seule par
/public/mobile-apps/ — null quand le badge est désactivé, vide ou non conforme."""
import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from rest_framework.test import APIClient

from handy.models import MobileAppLinks
from handy.store_links import normalize_app_store_url, normalize_play_store_url, safe_store_url

User = get_user_model()
URL = "/handy/public/mobile-apps/"
PLAY = "https://play.google.com/store/apps/details?id=com.tratra"
APPLE = "https://apps.apple.com/ci/app/tratra/id6450000000"


# ---- Validation des liens -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    (PLAY, PLAY),
    ("  https://play.google.com/store/apps/details?id=com.tratra  ", PLAY),
    ("https://PLAY.GOOGLE.COM/store/apps/details/?id=com.tratra", PLAY),
    # paramètres de suivi et fragment retirés ; langue/pays conservés
    ("https://play.google.com/store/apps/details?id=com.tratra&pcampaignid=web_share&utm_source=x#avis",
     PLAY),
    ("https://play.google.com/store/apps/details?hl=fr&id=com.tratra&gl=CI", PLAY + "&hl=fr&gl=CI"),
    ("https://play.google.com/store/apps/details?id=com.tratra&url=https://evil.example", PLAY),
])
def test_play_links_are_rewritten_to_the_official_form(raw, expected):
    assert normalize_play_store_url(raw) == expected


@pytest.mark.parametrize("raw", [
    "http://play.google.com/store/apps/details?id=com.tratra",               # pas de HTTPS
    "javascript:alert(1)",
    "https://play.google.com.evil.example/store/apps/details?id=com.tratra",  # sous-domaine piégé
    "https://evil.example/store/apps/details?id=com.tratra&x=play.google.com",
    "https://play.google.com@evil.example/store/apps/details?id=com.tratra",  # identifiant « …@ »
    "https://user:pw@play.google.com/store/apps/details?id=com.tratra",
    "https://play.google.com:8443/store/apps/details?id=com.tratra",          # port
    "https://play.google.com./store/apps/details?id=com.tratra",
    "https://www.google.com/url?q=https://play.google.com/store/apps/details?id=com.tratra",
    "https://play.google.com/store/apps/developer?id=Tratra",                 # pas une fiche d'application
    "https://play.google.com/store/apps/details",                             # id manquant
    "https://play.google.com/store/apps/details?id=com.tratra&id=com.autre",  # id ambigu
    "https://play.google.com/store/apps/details?id=../../evil",
    "https://play.google.com/store/apps/details?id=com.tratra\n.evil",
    "https://apps.apple.com/ci/app/tratra/id6450000000",                     # mauvais store
    "//play.google.com/store/apps/details?id=com.tratra",
])
def test_play_links_outside_an_official_listing_are_refused(raw):
    with pytest.raises(ValidationError):
        normalize_play_store_url(raw)
    assert safe_store_url("android", raw) is None


@pytest.mark.parametrize("raw, expected", [
    (APPLE, APPLE),
    ("https://apps.apple.com/ci/app/tratra/id6450000000?platform=iphone&l=fr#x", APPLE),
    ("https://apps.apple.com/app/id6450000000", "https://apps.apple.com/app/id6450000000"),
    ("https://apps.apple.com/fr/app/tratra-artisans/id6450000000/", "https://apps.apple.com/fr/app/tratra-artisans/id6450000000"),
])
def test_app_store_links_are_rewritten_to_the_official_form(raw, expected):
    assert normalize_app_store_url(raw) == expected


@pytest.mark.parametrize("raw", [
    "http://apps.apple.com/ci/app/tratra/id6450000000",
    "https://apps.apple.com.evil.example/ci/app/tratra/id6450000000",
    "https://itunes.apple.com/ci/app/tratra/id6450000000",
    "https://apps.apple.com@evil.example/ci/app/tratra/id6450000000",
    "https://apps.apple.com/ci/developer/tratra/id6450000000",
    "https://apps.apple.com/ci/app/tratra/",
    "https://apps.apple.com/ci/app/../../redirect/id6450000000",
    "https://apps.apple.com/ci/app/../id6450000000",
    PLAY,
])
def test_app_store_links_outside_an_official_listing_are_refused(raw):
    with pytest.raises(ValidationError):
        normalize_app_store_url(raw)
    assert safe_store_url("ios", raw) is None


# ---- Modèle : configuration unique ----------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_single_row_and_clean_normalizes_or_refuses():
    links = MobileAppLinks(android_store_url=PLAY + "&pcampaignid=web_share", android_enabled=True)
    links.full_clean()
    links.save()
    assert links.android_store_url == PLAY
    MobileAppLinks(ios_store_url=APPLE).save()
    assert MobileAppLinks.objects.count() == 1 and MobileAppLinks.get_solo().pk == 1

    with pytest.raises(ValidationError) as exc:
        MobileAppLinks(android_store_url="https://evil.example/app", ios_enabled=True).full_clean()
    assert set(exc.value.message_dict) == {"android_store_url", "ios_store_url"}   # lien piégé + badge activé sans lien


# ---- API publique ---------------------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_public_api_hides_everything_until_configured_and_never_writes():
    res = APIClient().get(URL, HTTP_AUTHORIZATION="Bearer jeton.invalide")   # un jeton invalide est ignoré
    assert res.status_code == 200
    assert res.json() == {"android_url": None, "ios_url": None}
    assert "max-age" in res["Cache-Control"]
    assert not MobileAppLinks.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("fields, expected", [
    ({"android_store_url": PLAY, "android_enabled": True, "ios_store_url": APPLE, "ios_enabled": True},
     {"android_url": PLAY, "ios_url": APPLE}),
    ({"android_store_url": PLAY, "android_enabled": False, "ios_store_url": APPLE, "ios_enabled": True},
     {"android_url": None, "ios_url": APPLE}),
    ({"android_store_url": "", "android_enabled": True, "ios_store_url": "", "ios_enabled": True},
     {"android_url": None, "ios_url": None}),
    # valeur écrite hors administration (sans validation) : jamais exposée
    ({"android_store_url": "https://evil.example/?play.google.com", "android_enabled": True,
      "ios_store_url": "https://apps.apple.com/ci/app/x/id6450000000?ref=evil", "ios_enabled": True},
     {"android_url": None, "ios_url": "https://apps.apple.com/ci/app/x/id6450000000"}),
])
def test_public_api_publishes_only_enabled_and_valid_links(fields, expected):
    MobileAppLinks.objects.create(**fields)
    assert APIClient().get(URL).json() == expected


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_public_api_is_read_only(method):
    res = getattr(APIClient(), method)(URL, {"android_store_url": "https://evil.example", "android_enabled": True}, format="json")
    assert res.status_code in (401, 403, 405)
    assert not MobileAppLinks.objects.exists()


# ---- Administration Django -------------------------------------------------------------------------------------------------

@pytest.fixture
def root(db):
    c = Client()
    c.force_login(User.objects.create_superuser("apps_root", "apps_root@x.test", "pass1234"))
    return c


def test_admin_edits_the_single_row_and_shows_the_resulting_state(root):
    res = root.get("/admin/handy/mobileapplinks/")
    assert res.status_code == 302 and res["Location"].endswith("/admin/handy/mobileapplinks/1/change/")
    page = root.get(res["Location"]).content.decode()
    assert "Masqué : aucun lien" in page

    res = root.post("/admin/handy/mobileapplinks/1/change/", {
        "android_store_url": PLAY + "&pcampaignid=web_share", "android_enabled": "on", "ios_store_url": "",
    })
    assert res.status_code == 302
    links = MobileAppLinks.get_solo()
    assert links.android_store_url == PLAY and links.android_enabled and not links.ios_enabled
    assert "Affiché sur le site" in root.get("/admin/handy/mobileapplinks/1/change/").content.decode()
    assert APIClient().get(URL).json() == {"android_url": PLAY, "ios_url": None}

    # lien piégé refusé, badge activé sans lien refusé : rien n'est modifié
    res = root.post("/admin/handy/mobileapplinks/1/change/", {
        "android_store_url": "https://play.google.com.evil.example/store/apps/details?id=com.tratra", "android_enabled": "on",
        "ios_enabled": "on", "ios_store_url": "",
    })
    assert res.status_code == 200 and "Seuls les liens play.google.com sont acceptés" in res.content.decode()
    assert MobileAppLinks.get_solo().android_store_url == PLAY


def test_admin_cannot_add_a_second_row_nor_delete(root):
    MobileAppLinks.get_solo()
    assert root.get("/admin/handy/mobileapplinks/add/").status_code == 403
    assert root.post("/admin/handy/mobileapplinks/1/delete/", {"post": "yes"}).status_code == 403
    assert MobileAppLinks.objects.count() == 1


def test_admin_requires_staff(db):
    c = Client()
    c.force_login(User.objects.create_user("apps_client", "apps_client@x.test", "pass1234"))
    assert c.get("/admin/handy/mobileapplinks/").status_code == 302      # redirigé vers la connexion de l'administration
    assert not MobileAppLinks.objects.exists()
