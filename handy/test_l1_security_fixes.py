"""L1a — failles de l'API fermées (§0.6, §9.1, §10 L1a du document de conception).

Chaque faille : le scénario d'attaque est refusé, puis le parcours légitime
correspondant fonctionne toujours (non-régression des clients React et Flutter).
"""
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.db import models
from django.db.models import ProtectedError
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from handy.conftest import STRONG_PASSWORD, TEST_MEDIA_HOST, gps_exif
from handy.models import (
    Booking, DepositTransaction, Dispute, HandymanDocument, HandymanProfile, Invoice, Payment,
    Payout, PayoutAccount, Review, ReviewMedia, Service, ServiceImage, Subscription, User,
)

pytestmark = pytest.mark.django_db

SENSITIVE_KEYS = ("email", "phone", "cni_number", "license_number", "insurance_info",
                  "location", "is_approved", "availability", "user_detail")
SECRETS = ("CNI-SECRET", "LIC-SECRET", "INS-SECRET", "secret-mail.test", "0707070707")


def _assert_coded(response, code, status):
    assert response.status_code == status, response.content
    body = response.json()
    assert body["code"] == code, body
    assert isinstance(body["detail"], str) and body["detail"]
    for entries in (body.get("fields") or {}).values():
        for entry in entries:
            assert set(entry) == {"code", "message"}, entry
    return body


def _stored_image(field_file):
    field_file.open("rb")
    try:
        data = field_file.read()
    finally:
        field_file.close()
    return data, Image.open(io.BytesIO(data))


@pytest.fixture
def artisan(make_handyman):
    """Artisan approuvé et actif, avec toutes les données sensibles renseignées."""
    return make_handyman(
        "awa_l1", approved=True, commune="Cocody", quartier="Riviera",
        cni_number="CNI-SECRET-1", license_number="LIC-SECRET-2", insurance_info="INS-SECRET-3",
        location=Point(-3.99, 5.36, srid=4326), availability={"lundi": "8h-18h"},
        user_extra={"first_name": "Awa", "last_name": "Kone",
                    "email": "awa@secret-mail.test", "phone": "0707070707"},
    )


# ============================ HandymanProfile ============================

def test_owner_cannot_self_approve_nor_write_reserved_fields(api_client, make_handyman, make_user):
    owner = make_handyman("hm_owner", cni_number="CNI-OLD", license_number="LIC-OLD")
    other = make_user("victim")
    profile = owner.handyman_profile
    api_client.force_authenticate(owner)

    r = api_client.patch(reverse("handymen-detail", args=[profile.pk]), {
        "is_approved": True, "user": other.pk, "rating": 5, "completed_jobs": 99,
        "quality_score": 100, "online": True, "cni_number": "CNI-NEW",
        "license_number": "LIC-NEW", "bio": "Plombier depuis 2019",
    }, format="json")

    assert r.status_code == 200, r.content
    profile.refresh_from_db()
    assert profile.is_approved is False
    assert profile.user_id == owner.pk
    assert (profile.rating, profile.completed_jobs, profile.quality_score) == (0, 0, 0)
    assert profile.online is False
    assert (profile.cni_number, profile.license_number) == ("CNI-OLD", "LIC-OLD")
    assert profile.bio == "Plombier depuis 2019"  # champ légitime toujours modifiable
    assert not HandymanProfile.objects.filter(user=other).exists()


def test_create_and_delete_handyman_profile_are_405(api_client, make_handyman, make_user):
    owner = make_handyman("hm_405")
    client = make_user("cli_405")
    api_client.force_authenticate(client)
    r = api_client.post(reverse("handymen-list"), {"user": client.pk, "bio": "x"}, format="json")
    assert r.status_code == 405
    assert not HandymanProfile.objects.filter(user=client).exists()

    api_client.force_authenticate(owner)
    assert api_client.delete(reverse("handymen-detail", args=[owner.handyman_profile.pk])).status_code == 405
    assert HandymanProfile.objects.filter(user=owner).exists()


def test_third_party_gets_404_on_private_profile_and_own_list_only(api_client, make_handyman):
    victim = make_handyman("hm_victim", approved=False, cni_number="CNI-SECRET-9",
                           license_number="LIC-SECRET-9", location=Point(-4.0, 5.3, srid=4326))
    snoop = make_handyman("hm_snoop")
    api_client.force_authenticate(snoop)

    listing = api_client.get(reverse("handymen-list"))
    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()["results"]] == [snoop.handyman_profile.pk]
    assert "CNI-SECRET" not in listing.content.decode()

    detail_url = reverse("handymen-detail", args=[victim.handyman_profile.pk])
    r = api_client.get(detail_url)
    assert r.status_code == 404
    assert "CNI-SECRET" not in r.content.decode()
    assert api_client.patch(detail_url, {"bio": "piraté"}, format="json").status_code == 404
    victim.handyman_profile.refresh_from_db()
    assert victim.handyman_profile.bio != "piraté"
    # inexistant et non publiable : même réponse
    assert api_client.get(reverse("handymen-detail", args=[999999])).json() == r.json()
    assert api_client.get("/handy/handymen/abc/").status_code == 404


def test_compat_bridge_serves_only_the_public_card(api_client, artisan, make_user, make_category,
                                                   make_service):
    """Pont Flutter (artisan_profile_screen) : GET /handymen/{id}/ par un tiers sur un
    profil approuvé et actif -> carte PUBLIQUE, sans aucune donnée sensible."""
    cat = make_category("pont-l1")
    make_service(artisan, cat, "Fuite")
    make_service(artisan, cat, "Inactif", active=False)
    viewer = make_user("viewer_l1")
    api_client.force_authenticate(viewer)

    r = api_client.get(reverse("handymen-detail", args=[artisan.handyman_profile.pk]))
    assert r.status_code == 200, r.content
    body = r.json()
    assert set(body) == {"id", "display_name", "commune", "rating", "completed_jobs",
                         "experience_years", "is_verified", "online", "photo", "user_id",
                         "quartier", "hourly_rate", "skills", "services_count"}
    assert body["user_id"] == artisan.pk and body["display_name"] == "Awa K."
    assert body["services_count"] == 1
    text = r.content.decode()
    for key in SENSITIVE_KEYS:
        assert f'"{key}"' not in text, key
    for secret in SECRETS:
        assert secret not in text, secret

    # Le propriétaire garde sa vue complète (dont ses numéros).
    api_client.force_authenticate(artisan)
    own = api_client.get(reverse("handymen-detail", args=[artisan.handyman_profile.pk])).json()
    assert own["cni_number"] == "CNI-SECRET-1" and own["user"] == artisan.pk


def test_compat_bridge_hides_unapproved_or_inactive_profiles(api_client, make_handyman, make_user):
    pending = make_handyman("hm_pending", approved=False)
    banned = make_handyman("hm_banned", approved=True, active=False)
    api_client.force_authenticate(make_user("viewer_l1b"))
    for user in (pending, banned):
        assert api_client.get(reverse("handymen-detail", args=[user.handyman_profile.pk])).status_code == 404
    # Anonyme : inchangé (authentification exigée).
    api_client.force_authenticate(None)
    assert api_client.get(reverse("handymen-detail", args=[pending.handyman_profile.pk])).status_code == 401


def test_staff_keeps_global_read_until_l1b(api_client, make_handyman, make_user):
    a, b = make_handyman("hm_s1"), make_handyman("hm_s2")
    staff = make_user("staff_l1", is_staff=True)
    api_client.force_authenticate(staff)
    ids = {row["id"] for row in api_client.get(reverse("handymen-list")).json()["results"]}
    assert {a.handyman_profile.pk, b.handyman_profile.pk} <= ids
    r = api_client.get(reverse("handymen-detail", args=[a.handyman_profile.pk]))
    assert r.status_code == 200 and "cni_number" in r.json()


def test_presence_is_unchanged(api_client, make_handyman):
    pending = make_handyman("hm_pres_pending")
    approved = make_handyman("hm_pres_ok", approved=True)
    url = reverse("handymen-presence")
    api_client.force_authenticate(pending)
    assert api_client.post(url, {"online": True}, format="json").status_code == 403
    api_client.force_authenticate(approved)
    r = api_client.post(url, {"online": True}, format="json")
    assert r.status_code == 200 and r.json() == {"online": True}
    assert api_client.post(url, {"online": False}, format="json").json() == {"online": False}


# ================================ Services ================================

def _service_payload(category, **extra):
    payload = {"category": category.pk, "title": "Débouchage", "description": "Évier, douche",
               "price_type": "fixed", "price": "8000"}
    payload.update(extra)
    return payload


def test_create_service_is_forced_onto_requester(api_client, make_handyman, make_category):
    me, rival = make_handyman("svc_me"), make_handyman("svc_rival")
    cat = make_category("svc-create")
    api_client.force_authenticate(me)
    r = api_client.post(reverse("services-list"), _service_payload(cat, handyman=rival.pk), format="json")
    assert r.status_code == 201, r.content
    service = Service.objects.get(pk=r.json()["id"])
    assert service.handyman_id == me.pk and r.json()["handyman"] == me.pk
    assert not Service.objects.filter(handyman=rival).exists()


def test_client_without_profile_cannot_create_service(api_client, make_user, make_category):
    client = make_user("svc_client")
    cat = make_category("svc-noprofile")
    api_client.force_authenticate(client)
    r = api_client.post(reverse("services-list"), _service_payload(cat), format="json")
    _assert_coded(r, "handyman_profile_required", 403)
    assert not Service.objects.filter(handyman=client).exists()


def test_service_owner_cannot_be_changed_and_others_cannot_edit(api_client, make_handyman, make_user,
                                                                 make_category, make_service):
    # Propriétaire éligible : son service est publié, donc visible (et refusé en écriture) pour les tiers.
    owner, rival = make_handyman("svc_owner", approved=True), make_handyman("svc_rival2")
    service = make_service(owner, make_category("svc-update"), "Original")
    url = reverse("services-detail", args=[service.pk])

    api_client.force_authenticate(owner)
    r = api_client.patch(url, {"handyman": rival.pk, "title": "Nouveau titre"}, format="json")
    assert r.status_code == 200, r.content
    service.refresh_from_db()
    assert service.handyman_id == owner.pk and service.title == "Nouveau titre"

    api_client.force_authenticate(rival)
    assert api_client.patch(url, {"title": "Volé"}, format="json").status_code == 403
    api_client.force_authenticate(make_user("svc_staff", is_staff=True))
    assert api_client.patch(url, {"title": "Volé"}, format="json").status_code == 403
    service.refresh_from_db()
    assert service.handyman_id == owner.pk and service.title == "Nouveau titre"


def test_handyman_filter_uses_strict_equality(api_client, make_handyman, make_category, make_service):
    a, b = make_handyman("flt_a", approved=True), make_handyman("flt_b", approved=True)
    cat = make_category("svc-filter")
    a1, a_off = make_service(a, cat, "A1"), make_service(a, cat, "A off", active=False)
    b1 = make_service(b, cat, "B1")
    url = reverse("services-list")

    def ids(params):
        r = api_client.get(url, params)
        assert r.status_code == 200, (params, r.content)
        return {row["id"] for row in r.json()["results"]}

    public_all = ids({"categories": cat.pk})
    assert public_all == {a1.pk, b1.pk}  # catalogue : services actifs d'artisans éligibles
    # ?handyman=<autre id> : uniquement SES services publics, jamais ceux d'autrui.
    assert ids({"handyman": a.pk}) == {a1.pk}
    assert ids({"handyman": b.pk}) == {b1.pk}
    # Contrat Flutter (artisan_profile_screen).
    assert ids({"handyman": a.pk, "is_active": "true", "ordering": "-created_at"}) == {a1.pk}
    # Valeurs non canoniques, inconnues ou multiples : liste vide (plus de 400 qui
    # révélait l'existence d'un compte), jamais le catalogue entier.
    for raw in (f"0{a.pk}", f"{a.pk}abc", f" {a.pk}", f"{a.pk}.0", "-1", "999999999", "abc"):
        assert ids({"handyman": raw}) == set(), raw
    assert ids({"handyman": [a.pk, b.pk]}) == set()
    assert ids({"handyman": ""}) >= {a1.pk, b1.pk}  # vide = pas de filtre
    # Le propriétaire liste ses services, actifs ou non.
    api_client.force_authenticate(a)
    assert ids({"handyman": a.pk}) == {a1.pk, a_off.pk}


@pytest.mark.parametrize("image_url", [
    f"http://{TEST_MEDIA_HOST}/service_images/a.jpg",            # pas https
    "https://tracker.example.com/pixel.gif",                     # hôte tiers
    f"https://{TEST_MEDIA_HOST}@tracker.example.com/a.jpg",      # hôte réel = tracker
    f"https://user:pw@{TEST_MEDIA_HOST}/a.jpg",                  # identifiants
    f"https://{TEST_MEDIA_HOST}.evil.example/a.jpg",             # suffixe trompeur
    f"ftp://{TEST_MEDIA_HOST}/a.jpg",
])
def test_image_url_outside_project_hosts_is_refused(api_client, make_handyman, make_category, image_url):
    owner = make_handyman("url_owner")
    api_client.force_authenticate(owner)
    r = api_client.post(reverse("services-list"),
                        _service_payload(make_category("svc-url"), image_url=image_url), format="json")
    if r.json().get("code"):
        body = _assert_coded(r, "invalid_image_url", 400)
        assert body["fields"]["image_url"][0]["code"] == "invalid_image_url"
    else:  # rejeté dès la validation d'URL (format DRF inchangé)
        assert r.status_code == 400 and "image_url" in r.json()
    assert not Service.objects.filter(handyman=owner).exists()


def test_image_url_on_project_host_is_accepted_and_legacy_values_untouched(
        api_client, make_handyman, make_category, make_service):
    owner = make_handyman("url_ok")
    cat = make_category("svc-url-ok")
    api_client.force_authenticate(owner)
    good = f"https://{TEST_MEDIA_HOST}/service_images/ok.jpg"
    r = api_client.post(reverse("services-list"), _service_payload(cat, image_url=good), format="json")
    assert r.status_code == 201, r.content
    assert r.json()["image_url"] == good
    # Règle appliquée au seul champ modifié : une valeur legacy n'empêche pas l'édition.
    legacy = make_service(owner, cat, "Legacy", image_url="http://old.example.com/x.jpg")
    r = api_client.patch(reverse("services-detail", args=[legacy.pk]), {"title": "Edité"}, format="json")
    assert r.status_code == 200, r.content


def test_destroying_a_booked_service_deactivates_it(api_client, make_handyman, make_user,
                                                     make_category, make_service):
    owner = make_handyman("del_owner")
    cat = make_category("svc-del")
    booked, free = make_service(owner, cat, "Réservé"), make_service(owner, cat, "Libre")
    booking = Booking.objects.create(client=make_user("del_client"), handyman=owner, service=booked,
                                     booking_date=timezone.now() + timedelta(days=1),
                                     address="Rue 1", city="Abidjan", postal_code="00225")
    api_client.force_authenticate(owner)
    assert api_client.delete(reverse("services-detail", args=[booked.pk])).status_code == 204
    booked.refresh_from_db()
    booking.refresh_from_db()
    assert booked.is_active is False and booking.service_id == booked.pk
    assert api_client.delete(reverse("services-detail", args=[free.pk])).status_code == 204
    assert not Service.objects.filter(pk=free.pk).exists()


# ============================== ServiceImage ==============================

@pytest.fixture
def two_artisans_with_image(api_client, make_handyman, make_category, make_service, jpeg_bytes, upload):
    owner, rival = make_handyman("img_owner"), make_handyman("img_rival")
    cat = make_category("svc-img")
    s1, s1b, s2 = (make_service(owner, cat, "S1"), make_service(owner, cat, "S1b"),
                   make_service(rival, cat, "S2"))
    api_client.force_authenticate(owner)
    r = api_client.post(reverse("service-images-list"),
                        {"service": s1.pk, "image": upload("a.jpg", jpeg_bytes())}, format="multipart")
    assert r.status_code == 201, r.content
    api_client.force_authenticate(None)
    return {"owner": owner, "rival": rival, "s1": s1, "s1b": s1b, "s2": s2,
            "image": ServiceImage.objects.get(pk=r.json()["id"])}


def test_service_image_idor_returns_404(api_client, two_artisans_with_image, png_bytes, upload):
    ctx = two_artisans_with_image
    image = ctx["image"]
    url = reverse("service-images-detail", args=[image.pk])
    api_client.force_authenticate(ctx["rival"])

    assert image.pk not in {row["id"] for row in api_client.get(reverse("service-images-list")).json()["results"]}
    assert api_client.get(url).status_code == 404
    assert api_client.patch(url, {"service": ctx["s2"].pk, "alt_text": "volée"}, format="json").status_code == 404
    assert api_client.put(url, {"service": ctx["s2"].pk, "image": upload("b.png", png_bytes(), "image/png")},
                          format="multipart").status_code == 404
    assert api_client.delete(url).status_code == 404
    image.refresh_from_db()
    assert image.service_id == ctx["s1"].pk and image.alt_text in (None, "")


def test_image_can_only_be_attached_to_own_service(api_client, two_artisans_with_image, jpeg_bytes, upload):
    ctx = two_artisans_with_image
    api_client.force_authenticate(ctx["rival"])
    r = api_client.post(reverse("service-images-list"),
                        {"service": ctx["s1"].pk, "image": upload("x.jpg", jpeg_bytes())}, format="multipart")
    assert r.status_code == 400 and "service" in r.json(), r.content
    assert ServiceImage.objects.filter(service=ctx["s1"]).count() == 1


def test_image_service_is_immutable_after_creation(api_client, two_artisans_with_image):
    ctx = two_artisans_with_image
    url = reverse("service-images-detail", args=[ctx["image"].pk])
    api_client.force_authenticate(ctx["owner"])
    for target in (ctx["s1b"], ctx["s2"]):  # son autre service, puis celui d'un concurrent
        r = api_client.patch(url, {"service": target.pk}, format="json")
        assert r.status_code == 400 and "service" in r.json(), r.content
    r = api_client.patch(url, {"alt_text": "Salle de bain"}, format="json")  # édition légitime
    assert r.status_code == 200, r.content
    ctx["image"].refresh_from_db()
    assert ctx["image"].service_id == ctx["s1"].pk and ctx["image"].alt_text == "Salle de bain"


# ===================== Réencodage des images publiques =====================

def test_service_image_is_reencoded_without_exif(api_client, make_handyman, make_category, make_service,
                                                 jpeg_bytes, upload):
    owner = make_handyman("exif_owner")
    service = make_service(owner, make_category("svc-exif"))
    original = jpeg_bytes(40, 20, exif=gps_exif(orientation=6))
    assert Image.open(io.BytesIO(original)).getexif().get_ifd(0x8825)  # GPS bien présent

    api_client.force_authenticate(owner)
    r = api_client.post(reverse("service-images-list"),
                        {"service": service.pk, "image": upload("IMG_maison_cocody.jpg", original)},
                        format="multipart")
    assert r.status_code == 201, r.content
    stored = ServiceImage.objects.get(pk=r.json()["id"])
    data, img = _stored_image(stored.image)
    assert img.format == "JPEG"
    assert not img.getexif() and "exif" not in img.info
    assert b"SpyCam" not in data
    assert img.size == (20, 40)  # orientation appliquée aux pixels avant suppression
    assert "maison" not in stored.image.name and stored.image.name.startswith("service_images/")


def test_transparent_png_stays_png_and_huge_image_is_downscaled(
        api_client, make_handyman, make_category, make_service, png_bytes, jpeg_bytes, upload):
    owner = make_handyman("png_owner")
    service = make_service(owner, make_category("svc-png"))
    api_client.force_authenticate(owner)
    url = reverse("service-images-list")

    r = api_client.post(url, {"service": service.pk, "image": upload("t.png", png_bytes(alpha=True), "image/png")},
                        format="multipart")
    assert r.status_code == 201, r.content
    _, img = _stored_image(ServiceImage.objects.get(pk=r.json()["id"]).image)
    assert img.format == "PNG" and img.mode == "RGBA"

    r = api_client.post(url, {"service": service.pk, "image": upload("big.jpg", jpeg_bytes(4096, 1024))},
                        format="multipart")
    assert r.status_code == 201, r.content
    _, img = _stored_image(ServiceImage.objects.get(pk=r.json()["id"]).image)
    assert img.size == (2048, 512)  # proportions conservées

    r = api_client.post(url, {"service": service.pk, "image": upload("small.jpg", jpeg_bytes(300, 200))},
                        format="multipart")
    assert r.status_code == 201, r.content
    _, img = _stored_image(ServiceImage.objects.get(pk=r.json()["id"]).image)
    assert img.size == (300, 200)  # dimensions raisonnables conservées


def test_non_image_uploads_are_refused(api_client, make_handyman, make_category, make_service, pdf_bytes,
                                       upload):
    owner = make_handyman("bad_owner")
    service = make_service(owner, make_category("svc-bad"))
    api_client.force_authenticate(owner)
    gif = io.BytesIO()
    Image.new("RGB", (8, 8)).save(gif, format="GIF")
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    for name, data, ctype in (("cv.jpg", pdf_bytes(), "image/jpeg"), ("x.svg", svg, "image/svg+xml"),
                              ("anim.gif", gif.getvalue(), "image/gif"), ("vide.jpg", b"\xff\xd8\xff", "image/jpeg")):
        r = api_client.post(reverse("service-images-list"),
                            {"service": service.pk, "image": upload(name, data, ctype)}, format="multipart")
        assert r.status_code == 400 and "image" in r.json(), (name, r.content)
    assert not ServiceImage.objects.filter(service=service).exists()


def test_service_banner_is_reencoded(api_client, make_handyman, make_category, jpeg_bytes, upload):
    owner = make_handyman("banner_owner")
    cat = make_category("svc-banner")
    api_client.force_authenticate(owner)
    payload = _service_payload(cat)
    payload["banner"] = upload("banniere.jpg", jpeg_bytes(exif=gps_exif()))
    r = api_client.post(reverse("services-list"), payload, format="multipart")
    assert r.status_code == 201, r.content
    data, img = _stored_image(Service.objects.get(pk=r.json()["id"]).banner)
    assert not img.getexif() and b"SpyCam" not in data


def test_admin_and_orm_uploads_are_sanitized_too(make_handyman, make_user, make_category, make_service,
                                                 jpeg_bytes, upload):
    """Hors API (admin Django, commandes) : signal pre_save sur les images publiques."""
    owner = make_handyman("orm_owner")
    client = make_user("orm_client")
    service = make_service(owner, make_category("svc-orm"))
    image = ServiceImage.objects.create(service=service, image=upload("orm.jpg", jpeg_bytes(exif=gps_exif())))
    booking = Booking.objects.create(client=client, handyman=owner, service=service, status="completed",
                                     booking_date=timezone.now() - timedelta(days=1),
                                     address="Rue 1", city="Abidjan", postal_code="00225")
    media = ReviewMedia.objects.create(review=Review.objects.create(booking=booking, rating=5),
                                       image=upload("avis.jpg", jpeg_bytes(exif=gps_exif())))
    profile = owner.handyman_profile
    profile.photo = upload("moi.jpg", jpeg_bytes(exif=gps_exif()))
    profile.save()
    for field_file in (image.image, media.image, profile.photo):
        data, img = _stored_image(field_file)
        assert not img.getexif() and b"SpyCam" not in data, field_file.name
    # Un fichier déjà en base n'est pas réécrit par une sauvegarde ordinaire.
    name = profile.photo.name
    profile.bio = "Mise à jour"
    profile.save()
    profile.refresh_from_db()
    assert profile.photo.name == name


# ================================== User ==================================

def test_patch_password_is_refused_and_hash_unchanged(api_client, make_user):
    user = make_user("pwd_user", first_name="Awa")
    old_hash = user.password
    api_client.force_authenticate(user)
    r = api_client.patch(reverse("users-detail", args=[user.pk]),
                         {"password": "Nouveau!Secret-2026", "first_name": "Pirate"}, format="json")
    body = _assert_coded(r, "password_change_endpoint", 400)
    assert body["fields"]["password"][0]["code"] == "password_change_endpoint"
    user.refresh_from_db()
    assert user.password == old_hash and user.check_password(STRONG_PASSWORD)
    assert user.first_name == "Awa"  # requête rejetée en bloc
    r = api_client.put(reverse("users-detail", args=[user.pk]),
                       {"username": "pwd_user", "email": "pwd_user@example.test", "password": "x"}, format="json")
    _assert_coded(r, "password_change_endpoint", 400)


def test_delete_user_is_405(api_client, make_user):
    user = make_user("del_user")
    api_client.force_authenticate(user)
    assert api_client.delete(reverse("users-detail", args=[user.pk])).status_code == 405
    assert User.objects.filter(pk=user.pk).exists()


def test_profile_patch_used_by_flutter_still_works(api_client, make_user):
    user = make_user("flutter_user")
    api_client.force_authenticate(user)
    r = api_client.patch(reverse("users-detail", args=[user.pk]), {
        "email": "nouvel@example.test", "username": "flutter_user2", "first_name": "Koffi",
        "last_name": "Yao", "phone": "0102030405",
    }, format="json")
    assert r.status_code == 200, r.content
    user.refresh_from_db()
    assert (user.email, user.username, user.first_name, user.phone) == (
        "nouvel@example.test", "flutter_user2", "Koffi", "0102030405")


def test_user_type_is_read_only_after_signup(api_client, make_user):
    user = make_user("role_user")
    api_client.force_authenticate(user)
    r = api_client.patch(reverse("users-detail", args=[user.pk]),
                         {"user_type": "handyman", "first_name": "Ama"}, format="json")
    assert r.status_code == 200, r.content
    user.refresh_from_db()
    assert user.user_type == "client" and user.first_name == "Ama"
    assert not HandymanProfile.objects.filter(user=user).exists()


def _signup(api_client, **extra):
    payload = {"username": "nouveau", "email": "nouveau@example.test", "password": STRONG_PASSWORD,
               "first_name": "Ama", "last_name": "Diallo"}
    payload.update(extra)
    return api_client.post(reverse("users-list"), payload, format="json")


def test_legacy_signup_ignores_phone(api_client, make_user):
    make_user("porteur", phone="0505050505")
    r = _signup(api_client, phone="0505050505")  # numéro d'un autre compte : aucun oracle
    assert r.status_code == 201, r.content
    assert r.json()["phone"] is None
    assert User.objects.get(username="nouveau").phone is None
    r = _signup(api_client, username="nouveau2", email="nouveau2@example.test", phone="0700000001")
    assert r.status_code == 201 and User.objects.get(username="nouveau2").phone is None


def test_legacy_signup_conflicts_are_generic(api_client, make_user):
    make_user("awa_exist", email="awa.exist@example.test")
    by_email = _signup(api_client, email="AWA.EXIST@example.test")
    by_username = _signup(api_client, username="Awa_Exist")
    for r in (by_email, by_username):
        body = _assert_coded(r, "signup_unavailable", 400)
        assert "fields" not in body  # ne dit pas QUEL champ est pris
    assert by_email.json() == by_username.json()
    text = by_email.content.decode().lower()
    assert "email" not in text and "username" not in text and "existe" not in text
    assert User.objects.filter(username__iexact="awa_exist").count() == 1


def test_legacy_signup_validates_password(api_client):
    for weak in ("pass1234", "12345678", "court", "Diallo2026"):  # le dernier : similaire au nom
        r = _signup(api_client, password=weak)
        assert r.status_code == 400 and "password" in r.json(), (weak, r.content)
    assert not User.objects.filter(username="nouveau").exists()
    r = _signup(api_client)
    assert r.status_code == 201, r.content
    user = User.objects.get(username="nouveau")
    assert user.check_password(STRONG_PASSWORD) and not user.is_staff and not user.is_superuser
    assert "password" not in r.json()


def test_signup_admin_role_refused_even_for_staff(api_client, make_user):
    api_client.force_authenticate(make_user("staff_signup", is_staff=True))
    r = _signup(api_client, user_type="admin")
    assert r.status_code == 400 and "user_type" in r.json()
    assert not User.objects.filter(username="nouveau").exists()


# ============================== PublicUserMini ==============================

def test_public_user_mini_is_reduced(api_client, artisan, make_category, make_service):
    make_service(artisan, make_category("svc-mini"), "Fuite")
    r = api_client.get(reverse("services-list"), {"handyman": artisan.pk})
    assert r.status_code == 200
    detail = r.json()["results"][0]["handyman_detail"]
    assert detail == {"id": artisan.pk, "first_name": "Awa", "display_name": "Awa K."}


# ================================= Booking =================================

@pytest.fixture
def booking_ctx(make_handyman, make_user, make_category, make_service):
    owner, other = make_handyman("bk_owner", approved=True), make_handyman("bk_other", approved=True)
    cat = make_category("svc-booking")
    return {"owner": owner, "other": other, "client": make_user("bk_client"),
            "service": make_service(owner, cat, "Actif"),
            "inactive": make_service(owner, cat, "Inactif", active=False)}


def _book(api_client, **extra):
    payload = {"booking_date": (timezone.now() + timedelta(days=1)).isoformat(),
               "address": "Rue 12", "city": "Abidjan", "postal_code": "00225"}
    payload.update(extra)
    return api_client.post(reverse("bookings-list"), payload, format="json")


def test_booking_with_mismatched_handyman_is_refused(api_client, booking_ctx):
    api_client.force_authenticate(booking_ctx["client"])
    r = _book(api_client, service=booking_ctx["service"].pk, handyman=booking_ctx["other"].pk)
    body = _assert_coded(r, "handyman_mismatch", 400)
    assert body["fields"]["handyman"][0]["code"] == "handyman_mismatch"
    assert not Booking.objects.exists()


def test_booking_inactive_service_is_refused(api_client, booking_ctx):
    api_client.force_authenticate(booking_ctx["client"])
    _assert_coded(_book(api_client, service=booking_ctx["inactive"].pk), "service_unavailable", 400)
    assert not Booking.objects.exists()


def test_self_booking_is_refused_not_500(api_client, booking_ctx):
    api_client.force_authenticate(booking_ctx["owner"])
    _assert_coded(_book(api_client, service=booking_ctx["service"].pk), "self_booking_forbidden", 400)
    _assert_coded(_book(api_client, handyman=booking_ctx["owner"].pk), "self_booking_forbidden", 400)
    assert not Booking.objects.exists()


def test_booking_without_service_needs_a_handyman_profile(api_client, booking_ctx, make_user):
    api_client.force_authenticate(booking_ctx["client"])
    _assert_coded(_book(api_client, handyman=make_user("pas_artisan").pk), "handyman_unavailable", 400)
    r = _book(api_client)  # ni service ni artisan : erreur DRF classique (pas de 500)
    assert r.status_code == 400 and "handyman" in r.json() and "code" not in r.json()
    assert not Booking.objects.exists()


def test_legitimate_bookings_still_work(api_client, booking_ctx):
    api_client.force_authenticate(booking_ctx["client"])
    r = _book(api_client, service=booking_ctx["service"].pk, handyman=booking_ctx["owner"].pk, type="instant")
    assert r.status_code == 201, r.content
    r = _book(api_client, service=booking_ctx["service"].pk)  # artisan déduit de la prestation
    assert r.status_code == 201, r.content
    assert Booking.objects.get(pk=r.json()["id"]).handyman_id == booking_ctx["owner"].pk
    r = _book(api_client, handyman=booking_ctx["other"].pk)  # demande directe à un artisan
    assert r.status_code == 201, r.content


def test_other_drf_errors_keep_their_format(api_client, booking_ctx):
    api_client.force_authenticate(booking_ctx["client"])
    r = api_client.post(reverse("bookings-list"), {"service": booking_ctx["service"].pk}, format="json")
    assert r.status_code == 400 and "booking_date" in r.json() and "code" not in r.json()
    r = api_client.get(reverse("bookings-detail", args=[999999]))
    assert r.status_code == 404 and set(r.json()) == {"detail"}


# ============================ 0029 : PROTECT ============================

PROTECTED_RELATIONS = [
    (Booking, "client"), (Booking, "handyman"), (Payment, "booking"), (Payout, "handyman"),
    (DepositTransaction, "handyman"), (Invoice, "booking"), (Subscription, "user"),
    (Review, "booking"), (Dispute, "booking"), (PayoutAccount, "handyman"),
    (HandymanDocument, "handyman"),
]


@pytest.mark.parametrize("model,field", PROTECTED_RELATIONS,
                         ids=[f"{m.__name__}.{f}" for m, f in PROTECTED_RELATIONS])
def test_history_relations_are_protected(model, field):
    assert model._meta.get_field(field).remote_field.on_delete is models.PROTECT


def test_migration_0029_is_state_only():
    out = io.StringIO()
    call_command("sqlmigrate", "handy", "0029", stdout=out)
    statements = [line for line in out.getvalue().splitlines()
                  if line.strip() and not line.startswith("--") and line.strip() not in ("BEGIN;", "COMMIT;")]
    assert statements == [], statements


def test_deleting_an_account_no_longer_cascades(booking_ctx):
    booking = Booking.objects.create(client=booking_ctx["client"], handyman=booking_ctx["owner"],
                                     service=booking_ctx["service"],
                                     booking_date=timezone.now() + timedelta(days=1),
                                     address="Rue 1", city="Abidjan", postal_code="00225")
    with pytest.raises(ProtectedError):
        booking_ctx["client"].delete()
    assert Booking.objects.filter(pk=booking.pk).exists()


def test_deleting_a_paid_booking_returns_409(api_client, booking_ctx):
    booking = Booking.objects.create(client=booking_ctx["client"], handyman=booking_ctx["owner"],
                                     service=booking_ctx["service"],
                                     booking_date=timezone.now() + timedelta(days=1),
                                     address="Rue 1", city="Abidjan", postal_code="00225")
    payment = Payment.objects.create(booking=booking, amount=Decimal("5000"), platform_fee=Decimal("550"),
                                     method="cash", status="pending")
    api_client.force_authenticate(booking_ctx["client"])
    r = api_client.delete(reverse("bookings-detail", args=[booking.pk]))
    assert r.status_code == 409 and set(r.json()) == {"detail"}, r.content
    assert Booking.objects.filter(pk=booking.pk).exists() and Payment.objects.filter(pk=payment.pk).exists()
