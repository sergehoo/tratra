"""Annonces : droits, validations, programmation, ciblage (rôles, villes déclarées, jamais le GPS), consentement marketing,
livraison unique, flux utilisateur, statistiques et isolation entre utilisateurs. Le serveur FCM est simulé."""
import io
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from announcements import services
from announcements.models import Announcement, AnnouncementDelivery
from backoffice import rbac
from handy import notifications, push
from handy.models import Device, Notification
from handy.test_push import FakeHTTP, service_account  # noqa: F401  (fixture)

User = get_user_model()
pytestmark = pytest.mark.django_db
BASE = "/handy/backoffice/announcements/"


def account(name, kind="client", city=None):
    u = User.objects.create_user(username=name, email=f"{name}@ex.com", password="pass1234", user_type=kind, is_verified=True, city=city)
    return u


def staff(name, role=None, superuser=False):
    rbac.ensure_roles()
    u = User.objects.create_user(username=name, email=f"{name}@ex.com", password="pass1234", is_staff=True, is_superuser=superuser)
    if role:
        u.groups.add(Group.objects.get(name=rbac.role_group_name(role)))
    return u


def api(u=None):
    c = APIClient()
    if u:
        c.force_authenticate(u)
    return c


@pytest.fixture
def publish_now(django_capture_on_commit_callbacks):
    """Publie puis exécute la diffusion (planifiée via on_commit, que pytest n'exécute pas sans capture)."""
    def go(a):
        with django_capture_on_commit_callbacks(execute=True):
            return services.publish(a)
    return go


def draft(**over):
    base = dict(title="Nouveau service", body="Découvrez nos nouveautés.", kind="service", to_clients=True, to_artisans=True, to_companies=True)
    base.update(over)
    return Announcement.objects.create(**base)


# ── Droits (RBAC côté serveur) ──────────────────────────────────────────────────────────────────────────────────────

def test_only_marketing_and_super_admin_can_manage_announcements():
    payload = {"title": "T", "body": "B", "to_clients": True}
    assert api().post(BASE, payload, format="json").status_code in (401, 403)
    assert api(account("a_user")).post(BASE, payload, format="json").status_code == 403           # simple utilisateur
    assert api(staff("a_nostaff_role")).post(BASE, payload, format="json").status_code == 403     # personnel sans rôle
    assert api(staff("a_support", "support")).post(BASE, payload, format="json").status_code == 403
    assert api(staff("a_mkt", "marketing")).post(BASE, payload, format="json").status_code == 201
    assert api(staff("a_root", superuser=True)).post(BASE, payload, format="json").status_code == 201
    assert api(staff("a_mkt2", "marketing")).get(BASE).json()["count"] == 2


def test_back_office_roles_are_server_side_permissions_not_ui_flags():
    assert rbac.has_permission(staff("r_mkt", "marketing"), "announcements.manage")
    assert not rbac.has_permission(staff("r_fin", "finance"), "announcements.manage")
    assert rbac.has_permission(staff("r_fin2", "finance"), "finance.manage")
    assert rbac.user_permissions(account("r_plain")) == set()


# ── Validations ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_action_validation_rejects_unsafe_links_and_unknown_screens():
    c = api(staff("v_mkt", "marketing"))
    ok = {"title": "T", "body": "B", "to_clients": True}
    assert c.post(BASE, {**ok, "action_kind": "link", "action_value": "javascript:alert(1)"}, format="json").status_code == 400
    assert c.post(BASE, {**ok, "action_kind": "link", "action_value": "http://insecure.example"}, format="json").status_code == 400
    assert c.post(BASE, {**ok, "action_kind": "deeplink", "action_value": "admin/1"}, format="json").status_code == 400
    assert c.post(BASE, {**ok, "action_kind": "deeplink", "action_value": "booking"}, format="json").status_code == 400
    assert c.post(BASE, {**ok, "action_kind": "link", "action_value": "https://tratra.net/offre"}, format="json").status_code == 201
    assert c.post(BASE, {**ok, "action_kind": "deeplink", "action_value": "reviews"}, format="json").status_code == 201


def test_publication_requires_an_audience_and_valid_dates():
    a = draft(to_clients=False, to_artisans=False, to_companies=False)
    with pytest.raises(Exception):
        services.publish(a)
    b = draft(expires_at=timezone.now() - timedelta(hours=1))
    with pytest.raises(Exception):
        services.publish(b)
    c = api(staff("d_mkt", "marketing"))
    bad = c.post(BASE, {"title": "T", "body": "B", "to_clients": True, "publish_at": "2030-01-02T10:00:00Z", "expires_at": "2030-01-01T10:00:00Z"}, format="json")
    assert bad.status_code == 400


def test_optimistic_locking_and_published_announcements_are_immutable():
    c = api(staff("o_mkt", "marketing"))
    created = c.post(BASE, {"title": "T", "body": "B", "to_clients": True}, format="json").json()
    url = f"{BASE}{created['id']}/"
    assert c.patch(url, {"title": "Sans version"}, format="json").status_code == 400
    ok = c.patch(url, {"title": "Titre 2", "version": created["version"]}, format="json")
    assert ok.status_code == 200 and ok.json()["version"] == created["version"] + 1
    stale = c.patch(url, {"title": "Écrasement", "version": created["version"]}, format="json")
    assert stale.status_code == 409 and stale.json()["current_version"] == ok.json()["version"]
    pub = c.post(f"{url}publish/", {}, format="json")
    assert pub.status_code == 200 and pub.json()["status"] == "published"
    assert c.patch(url, {"title": "Trop tard", "version": pub.json()["version"]}, format="json").status_code == 400
    assert c.delete(url).status_code == 409                                    # une annonce publiée s'annule, ne se supprime pas
    assert c.post(f"{url}cancel/", {}, format="json").json()["status"] == "cancelled"


# ── Ciblage ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_roles_cities_and_gps_targeting():
    client_abj = account("t_cli_abj", city="Abidjan")
    client_bkn = account("t_cli_bkn", city="Bouaké")
    artisan = account("t_art", "handyman")
    artisan.handyman_profile.commune = "Cocody"; artisan.handyman_profile.save()
    company = account("t_cie", "entreprise", city="Abidjan")
    a = draft(to_clients=True, to_artisans=False, to_companies=False)
    ids = set(services.audience_queryset(a).values_list("username", flat=True))
    assert {"t_cli_abj", "t_cli_bkn"} <= ids and "t_art" not in ids and "t_cie" not in ids      # un artisan n'est pas un « client » pur
    a.cities = ["abidjan"]                                                                      # insensible à la casse, exact
    assert set(services.audience_queryset(a).values_list("username", flat=True)) >= {"t_cli_abj"}
    assert "t_cli_bkn" not in set(services.audience_queryset(a).values_list("username", flat=True))
    a.to_artisans, a.cities = True, ["cocody"]                                                  # commune déclarée de l'artisan
    assert "t_art" in set(services.audience_queryset(a).values_list("username", flat=True))
    # Une position GPS ne cible JAMAIS : un client à Abidjan par GPS mais sans ville déclarée n'est pas ciblé.
    gps = account("t_gps"); gps.last_location = Point(-4.0083, 5.36, srid=4326); gps.save()
    a.to_artisans, a.cities = False, ["abidjan"]
    assert "t_gps" not in set(services.audience_queryset(a).values_list("username", flat=True))
    comp = draft(to_clients=False, to_artisans=False, to_companies=True)
    assert set(services.audience_queryset(comp).values_list("username", flat=True)) == {"t_cie"}


# ── Consentement marketing ──────────────────────────────────────────────────────────────────────────────────────────

def test_promotions_reach_only_users_who_consented_and_stop_when_consent_is_withdrawn(publish_now):
    yes, no = account("c_yes"), account("c_no")
    notifications.set_marketing_consent(yes, True, source="test")
    promo = draft(kind="promotion", to_clients=True)
    service = draft(title="Maintenance", kind="service", to_clients=True)
    assert set(services.audience_queryset(promo).values_list("username", flat=True)) == {"c_yes"}
    assert {"c_yes", "c_no"} <= set(services.audience_queryset(service).values_list("username", flat=True))
    publish_now(promo); publish_now(service)
    assert {a["title"] for a in api(yes).get("/handy/me/announcements/").json()["results"]} == {promo.title, "Maintenance"}
    assert [a["title"] for a in api(no).get("/handy/me/announcements/").json()["results"]] == ["Maintenance"]
    notifications.set_marketing_consent(yes, False, source="test")
    assert [a["title"] for a in api(yes).get("/handy/me/announcements/").json()["results"]] == ["Maintenance"]   # promo masquée


def test_promotional_push_is_never_sent_after_consent_withdrawal(service_account, monkeypatch, django_capture_on_commit_callbacks):
    path, _ = service_account
    u = account("c_push")
    notifications.set_marketing_consent(u, True, source="test")
    Device.objects.create(user=u, device_token="tok-promo", device_type="android")
    promo = draft(kind="promotion", to_clients=True)
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)
    with override_settings(FCM_CREDENTIALS_FILE=path):
        with django_capture_on_commit_callbacks(execute=False):                # le push est planifié, pas encore exécuté
            services.publish(promo)
            services.deliver(promo.pk)
        n = Notification.objects.get(user=u, notification_type="announcement")
        assert n.push_status == "queued"
        notifications.set_marketing_consent(u, False, source="test")           # retrait AVANT l'envoi effectif
        from handy.tasks import send_notification_push
        send_notification_push(n.pk)
    n.refresh_from_db()
    assert n.push_status == "disabled" and not [1 for url, _ in http.calls if "fcm.googleapis.com" in url]


# ── Programmation, diffusion, expiration ────────────────────────────────────────────────────────────────────────────

def test_scheduled_announcement_is_published_by_the_tick_and_delivered_exactly_once(service_account, monkeypatch, django_capture_on_commit_callbacks):
    path, _ = service_account
    u = account("s_user")
    Device.objects.create(user=u, device_token="tok-s", device_type="android")
    c = api(staff("s_mkt", "marketing"))
    created = c.post(BASE, {"title": "Fête", "body": "Rendez-vous samedi", "to_clients": True}, format="json").json()
    past = c.post(f"{BASE}{created['id']}/schedule/", {"publish_at": (timezone.now() - timedelta(minutes=5)).isoformat()}, format="json")
    assert past.status_code == 400
    soon = timezone.now() + timedelta(minutes=10)
    assert c.post(f"{BASE}{created['id']}/schedule/", {"publish_at": soon.isoformat()}, format="json").json()["status"] == "scheduled"
    assert services.tick(now=timezone.now()) == {"published": 0, "expired": 0}      # pas encore l'heure
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)
    with override_settings(FCM_CREDENTIALS_FILE=path), django_capture_on_commit_callbacks(execute=True):
        assert services.tick(now=soon + timedelta(seconds=1))["published"] == 1
    assert services.deliver(created["id"]) == 0                                       # rejeu : aucune double livraison
    assert AnnouncementDelivery.objects.filter(announcement_id=created["id"], user=u).count() == 1
    assert Notification.objects.filter(user=u, notification_type="announcement").count() == 1
    sent = [kw["json"]["message"] for url, kw in http.calls if "fcm.googleapis.com" in url]
    assert len(sent) == 1 and sent[0]["data"]["deeplink"] == f"tratra://announcement/{created['id']}"
    assert sent[0]["android"]["notification"]["channel_id"] == "tratra_announcements"


def test_expired_announcements_leave_the_feed_and_the_tick_marks_them(publish_now):
    u = account("e_user")
    a = draft(to_clients=True, expires_at=timezone.now() + timedelta(minutes=30))
    publish_now(a)
    assert len(api(u).get("/handy/me/announcements/").json()["results"]) == 1
    Announcement.objects.filter(pk=a.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert api(u).get("/handy/me/announcements/").json()["results"] == []          # masquée dès l'expiration, avant même le tick
    assert services.tick()["expired"] == 1 and Announcement.objects.get(pk=a.pk).status == "expired"


# ── Flux utilisateur, statistiques, isolation ───────────────────────────────────────────────────────────────────────

def test_feed_events_stats_and_isolation_between_users(publish_now):
    a_user, b_user, outsider = account("f_a"), account("f_b"), staff("f_outsider")
    ann = draft(to_clients=True, action_kind="deeplink", action_value="reviews", action_label="Voir mes avis")
    publish_now(ann)
    feed = api(a_user).get("/handy/me/announcements/").json()["results"]
    assert feed[0]["action"] == {"kind": "deeplink", "label": "Voir mes avis", "value": "reviews", "web": "/dashboard/reviews"}
    assert "cities" not in feed[0] and "to_clients" not in feed[0]                  # aucune donnée de ciblage côté utilisateur
    ca, cb = api(a_user), api(b_user)
    assert ca.post(f"/handy/me/announcements/{ann.pk}/seen/", {}, format="json").status_code == 200
    assert ca.post(f"/handy/me/announcements/{ann.pk}/open/", {}, format="json").status_code == 200
    first = AnnouncementDelivery.objects.get(announcement=ann, user=a_user)
    ca.post(f"/handy/me/announcements/{ann.pk}/open/", {}, format="json")          # idempotent : horodatage conservé
    assert AnnouncementDelivery.objects.get(pk=first.pk).opened_at == first.opened_at
    assert api(account("f_never")).post(f"/handy/me/announcements/{ann.pk}/seen/", {}, format="json").status_code == 404
    assert ca.post(f"/handy/me/announcements/{ann.pk}/inconnu/", {}, format="json").status_code == 404
    st = services.stats(ann)
    assert st["delivered"] >= 2 and st["seen"] == 1 and st["opened"] == 1 and st["open_rate"] == round(1 / st["delivered"], 4)
    assert cb.get("/handy/me/announcements/").json()["results"][0]["opened_at"] is None   # l'ouverture de A n'est pas visible par B
    ca.post(f"/handy/me/announcements/{ann.pk}/dismiss/", {}, format="json")
    assert ca.get("/handy/me/announcements/").json()["results"] == []
    root = api(staff("f_mkt", "marketing"))
    body = root.get(f"{BASE}{ann.pk}/stats/").json()
    assert set(body) >= {"delivered", "seen", "opened", "push", "open_rate"} and "f_a" not in str(body)   # statistiques agrégées, sans identité
    assert api(outsider).get(f"{BASE}{ann.pk}/stats/").status_code == 403         # personnel sans rôle marketing


def test_image_upload_is_reencoded_without_metadata():
    c = api(staff("i_mkt", "marketing"))
    buf = io.BytesIO()
    img = Image.new("RGB", (40, 30), (200, 30, 30))
    exif = Image.Exif(); exif[0x010F] = "AppareilSecret"
    img.save(buf, "JPEG", exif=exif)
    upload = SimpleUploadedFile("photo.jpg", buf.getvalue(), content_type="image/jpeg")
    r = c.post(BASE, {"title": "Avec image", "body": "B", "to_clients": "true", "image": upload}, format="multipart")
    assert r.status_code == 201, r.content
    stored = Announcement.objects.get(pk=r.json()["id"])
    with Image.open(stored.image) as saved:
        assert b"AppareilSecret" not in (saved.info.get("exif") or b"")
    bad = c.post(BASE, {"title": "Faux", "body": "B", "to_clients": "true", "image": SimpleUploadedFile("x.png", b"pas une image", content_type="image/png")}, format="multipart")
    assert bad.status_code == 400
