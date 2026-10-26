"""Annonces : registre central des écrans (rôles, paramètres, équivalent web), aperçu du Back-Office, notification push avec
image 2:1 (message de données pour les appareils « rich1 », notification classique avec image pour les autres), lien ouvert au
toucher. Le serveur FCM est simulé."""
import io

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from announcements import push_image
from announcements.models import Announcement
from announcements.test_announcements import BASE, account, api, draft, staff
from handy import destinations, push
from handy.models import Device
from handy.test_eligibility import artisan, service
from handy.test_push import FakeHTTP, service_account  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db

# Clés que l'application sait ouvrir (lib/core/deep_links.dart) : toute destination du registre doit y figurer.
APP_KEYS = {
    "home", "explore", "categories", "category", "services", "service", "search", "urgent", "flash_order", "favorites", "bookings",
    "messages", "notifications", "announcement", "reviews", "engagements", "profile", "addresses", "kyc", "pro", "reputation", "badge",
    "availability", "replacements", "business", "booking", "mission", "conversation", "contract", "posting", "business_request",
    "flash_offer", "flash_request", "trust_penalty", "panne",
}


@pytest.fixture(autouse=True)
def _media_in_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)          # images générées hors du dépôt


def png(size=(1600, 1200), color=(46, 139, 87, 255), mode="RGBA"):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format="PNG")
    return SimpleUploadedFile("visuel.png", buf.getvalue(), content_type="image/png")


# ── Registre central ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_registry_matches_the_app_and_covers_the_requested_screens():
    assert set(destinations.BY_KEY) == APP_KEYS
    offered = {d["key"] for d in destinations.catalog()}
    for key in ("home", "categories", "category", "services", "service", "search", "bookings", "profile", "reputation", "kyc",
                "flash_order", "availability", "announcement", "notifications", "business"):
        assert key in offered, key
    # Objets privés d'un seul compte : jamais proposés dans une annonce.
    assert not offered & {"booking", "mission", "conversation", "contract", "posting", "flash_offer", "flash_request"}


def test_destination_is_refused_unless_every_recipient_role_can_open_it():
    destinations.validate_for_announcement("reputation", ["artisans"])
    with pytest.raises(ValidationError, match="artisans"):
        destinations.validate_for_announcement("reputation", ["clients", "artisans"])
    with pytest.raises(ValidationError, match="entreprises"):
        destinations.validate_for_announcement("business", ["artisans"])
    destinations.validate_for_announcement("home", ["clients", "artisans", "companies"])
    for bad in ("admin", "booking/3", "home/4", "service", "service/abc", "../kyc"):
        with pytest.raises(ValidationError):
            destinations.validate_for_announcement(bad, ["clients"])


def test_parameters_must_designate_a_public_object():
    pro = artisan("dest_pro")
    offer = service(pro)
    destinations.validate_for_announcement(f"service/{offer.pk}", ["clients"])
    destinations.validate_for_announcement(f"category/{offer.category_id}", ["clients"])
    offer.is_active = False
    offer.save(update_fields=["is_active"])
    with pytest.raises(ValidationError, match="pas publiée"):
        destinations.validate_for_announcement(f"service/{offer.pk}", ["clients"])
    with pytest.raises(ValidationError):
        destinations.validate_for_announcement("category/999999", ["clients"])
    label = destinations.describe(f"category/{offer.category_id}")
    assert label["valid"] and label["detail"] == offer.category.name
    assert destinations.web_href(f"category/{offer.category_id}") == f"/search?metier={offer.category.slug}"


def test_back_office_lists_destinations_and_checks_one_against_the_recipients():
    c = api(staff("dest_mkt", "marketing"))
    body = c.get(f"{BASE}destinations/").json()
    keys = [d["key"] for d in body["results"]]
    assert "reputation" in keys and "booking" not in keys
    rep = next(d for d in body["results"] if d["key"] == "reputation")
    assert rep["roles"] == ["artisans"] and rep["group"] == "Espace professionnel"
    check = c.get(f"{BASE}destinations/", {"value": "reputation", "roles": "clients,artisans"}).json()["check"]
    assert check["label"].startswith("Ma réputation") and "artisans" in check["error"]
    assert c.get(f"{BASE}destinations/", {"value": "reviews", "roles": "clients"}).json()["check"]["error"] == ""
    assert api(account("dest_user")).get(f"{BASE}destinations/").status_code == 403


def test_saving_an_announcement_applies_the_role_rule():
    c = api(staff("dest_mkt2", "marketing"))
    ok = {"title": "Réputation", "body": "Consultez votre score", "to_artisans": True}
    assert c.post(BASE, {**ok, "action_kind": "deeplink", "action_value": "reputation"}, format="json").status_code == 201
    r = c.post(BASE, {**ok, "to_clients": True, "action_kind": "deeplink", "action_value": "reputation"}, format="json")
    assert r.status_code == 400 and "artisans" in str(r.json()["action_value"])


# ── Image de notification ──────────────────────────────────────────────────────────────────────────────────────────────

def test_push_image_is_a_light_centred_2_to_1_jpeg_never_enlarged():
    big = Image.open(io.BytesIO(push_image.render(png((1600, 1200)))))
    assert big.format == "JPEG" and big.size == (1024, 512)
    small = Image.open(io.BytesIO(push_image.render(png((300, 600), mode="RGB", color=(200, 10, 10)))))
    assert small.size == (300, 150)                                  # recadrée, jamais agrandie
    wide = Image.open(io.BytesIO(push_image.render(png((3000, 500)))))
    assert wide.size == (1000, 500)
    noisy = Image.effect_noise((2400, 1200), 120).convert("RGB")
    buf = io.BytesIO()
    noisy.save(buf, format="PNG")
    assert len(push_image.render(io.BytesIO(buf.getvalue()))) <= push_image.MAX_BYTES


def _published_with_image(publish_now, **over):
    a = draft(to_clients=True, to_artisans=False, to_companies=False, title="Une réparation à faire ?", body="Publiez votre besoin.",
              **over)
    a.image = png()
    a.save()
    publish_now(a)
    return Announcement.objects.get(pk=a.pk)


def _fcm(monkeypatch, path, fn):
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)
    with override_settings(FCM_CREDENTIALS_FILE=path, API_PUBLIC_URL="https://api.tratra.test"):
        fn()
    return [kw["json"]["message"] for url, kw in http.calls if "fcm.googleapis.com" in url]


@pytest.fixture
def publish_capture(django_capture_on_commit_callbacks):
    from announcements import services

    def go(a):
        with django_capture_on_commit_callbacks(execute=True):
            return services.publish(a)
    return go


def test_rich_devices_get_a_data_message_with_image_link_and_button_others_a_notification_with_image(
        service_account, monkeypatch, publish_capture):
    path, _ = service_account
    u = account("img_user")
    Device.objects.create(user=u, device_token="tok-rich", device_type="android", capabilities=["flash1", "rich1", "flash"])
    Device.objects.create(user=u, device_token="tok-old", device_type="android", capabilities=["flash1", "flash"])
    Device.objects.create(user=u, device_token="tok-ios", device_type="ios", capabilities=["flash"])
    Device.objects.create(user=u, device_token="tok-outdated", device_type="android", capabilities=["flash1", "rich1"])
    sent = _fcm(monkeypatch, path, lambda: _published_with_image(
        publish_capture, action_kind="deeplink", action_value="flash_order", action_label="Publier ma demande"))
    by_token = {m["token"]: m for m in sent}
    assert set(by_token) == {"tok-rich", "tok-old", "tok-ios"}            # un seul message par appareil : jamais de doublon
    # « tok-outdated » : version sans l'écran « Trouvez-moi un professionnel » (handy.features) — aucun bouton qui n'ouvre rien
    a = Announcement.objects.get()
    assert a.push_image and a.push_image_source == a.image.name
    rich = by_token["tok-rich"]
    assert "notification" not in rich                                      # l'application construit l'alerte (grande image, logo)
    assert rich["data"]["t"] == "announcement" and rich["data"]["title"] == "Une réparation à faire ?"
    assert rich["data"]["deeplink"] == "tratra://flash_order" and rich["data"]["cta"] == "Publier ma demande"
    assert rich["data"]["image"].startswith("https://api.tratra.test/") and rich["data"]["image"].endswith(".jpg")
    old = by_token["tok-old"]
    assert old["notification"]["image"] == rich["data"]["image"] and old["android"]["notification"]["channel_id"] == "tratra_announcements"
    assert old["data"]["deeplink"] == "tratra://flash_order"
    ios = by_token["tok-ios"]
    assert ios["apns"]["fcm_options"]["image"] == rich["data"]["image"] and ios["apns"]["payload"]["aps"]["mutable-content"] == 1


def test_without_https_or_without_image_the_notification_is_text_only(service_account, monkeypatch, publish_capture):
    path, _ = service_account
    u = account("txt_user")
    Device.objects.create(user=u, device_token="tok-rich2", device_type="android", capabilities=["rich1"])
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)
    with override_settings(FCM_CREDENTIALS_FILE=path, API_PUBLIC_URL="http://insecure.test"):
        _published_with_image(publish_capture)
    msg = [kw["json"]["message"] for url, kw in http.calls if "fcm.googleapis.com" in url][0]
    assert "image" not in msg["data"] and msg["data"]["deeplink"].startswith("tratra://announcement/")   # sans action : l'annonce
    sent = _fcm(monkeypatch, path, lambda: publish_capture(draft(to_clients=True, to_artisans=False, to_companies=False)))
    assert "image" not in sent[0]["data"]


def test_a_broken_image_never_blocks_the_delivery(service_account, monkeypatch, publish_capture):
    path, _ = service_account
    u = account("broken_user")
    Device.objects.create(user=u, device_token="tok-b", device_type="android", capabilities=["rich1"])
    monkeypatch.setattr(push_image, "render", lambda *_: (_ for _ in ()).throw(OSError("illisible")))
    sent = _fcm(monkeypatch, path, lambda: _published_with_image(publish_capture))
    assert len(sent) == 1 and "image" not in sent[0]["data"] and sent[0]["data"]["title"]


# ── Aperçu du Back-Office ─────────────────────────────────────────────────────────────────────────────────────────────

def test_preview_shows_exactly_what_the_phone_receives():
    pro = artisan("prev_pro")
    offer = service(pro)
    c = api(staff("prev_mkt", "marketing"))
    created = c.post(BASE, {"title": "🔧 Une réparation ?", "body": "Robinet qui fuit ?", "to_clients": True, "action_kind": "deeplink",
                            "action_value": f"service/{offer.pk}", "action_label": "Voir l'offre"}, format="json").json()
    p = c.get(f"{BASE}{created['id']}/preview/").json()
    assert p["title"] == "🔧 Une réparation ?" and p["body"] == "Robinet qui fuit ?" and p["channel"] == "tratra_announcements"
    assert p["deeplink"] == f"tratra://service/{offer.pk}" and p["errors"] == []
    assert p["action"]["label"] == "Voir l'offre" and p["action"]["destination"]["detail"].startswith(offer.title)
    assert p["action"]["web"] == f"/artisans/{pro.handyman_profile.pk}"
    Announcement.objects.filter(pk=created["id"]).update(to_clients=False)
    assert c.get(f"{BASE}{created['id']}/preview/").json()["errors"]          # plus aucun destinataire : publication impossible


def test_the_app_registers_its_rich_capability_through_the_api():
    """La capacité « rich1 » annoncée par l'application est CONSERVÉE à l'enregistrement de l'appareil (sinon les annonces
    repartiraient en notification classique, sans logo ni bouton)."""
    u = account("rich_reg")
    r = api(u).post("/handy/devices/", {"device_token": "tok-reg", "device_type": "android", "capabilities": ["flash1", "rich1", "inconnue"]},
                    format="json")
    assert r.status_code in (200, 201)
    assert Device.objects.get(device_token="tok-reg").capabilities == ["flash1", "rich1"]

