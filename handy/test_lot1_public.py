"""Lot 1 — endpoints publics (landing / recherche anonyme) et suppression des fausses données.

Couvre : /handymen/featured/, /reviews/public/, /public/stats/, filtres & tris de
/services/ et /services/nearby/, services_count des catégories, slides de repli,
puis les correctifs de la revue (intégrité des avis, paramètres bornés, offres B2B,
TTL de signature des médias).
Règle transverse : aucun email / pièce d'identité / position exacte dans un payload public.
"""
import importlib
import json
import os
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from handy.api.views import _decimal_param, search_services_nearby_qs
from handy.models import (
    Booking, HandymanProfile, HeroSlide, Review, Service, ServiceCategory, User,
)

INVALID_BEARER = "Bearer invalid.jwt.token"
SENSITIVE_KEYS = ("email", "cni_number", "license_number", "insurance_info",
                  "location", "phone", "availability")


@pytest.fixture(autouse=True)
def _clear_cache():
    # Throttle anonyme (LocMem) + cache des stats publiques : isolation entre tests.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client(db):
    return APIClient()


# ---------- helpers ----------

def _user(username, user_type="client", first="", last="", **extra):
    return User.objects.create_user(
        username=username, email=f"{username}@secret-mail.test", password="pass1234",
        user_type=user_type, first_name=first, last_name=last, **extra)


def _artisan(username, first="", last="", *, approved=True, online=False, commune="",
             rating=0.0, quality=0, completed=0, skills=(), location=None, active=True,
             quartier="Riviera"):
    user = _user(username, "handyman", first, last, is_active=active)
    profile = user.handyman_profile  # créé par le signal post_save
    profile.is_approved = approved
    profile.online = online
    profile.commune = commune
    profile.quartier = quartier
    profile.rating = rating
    profile.quality_score = quality
    profile.completed_jobs = completed
    profile.cni_number = "CNI-SECRET-123"
    profile.license_number = "LIC-SECRET-456"
    profile.insurance_info = "INS-SECRET-789"
    profile.availability = {"lundi": "8h-18h"}
    profile.location = location
    profile.save()
    if skills:
        profile.skills.set(skills)
    return user


def _cat(name, slug, active=True):
    return ServiceCategory.objects.create(name=name, slug=slug, is_active=active)


def _service(handyman, category, title, price=None, price_type=None, active=True, created_at=None):
    if price_type is None:
        price_type = "quote" if price is None else "fixed"
    svc = Service.objects.create(
        handyman=handyman, category=category, title=title, description="desc",
        price_type=price_type, price=Decimal(price) if price is not None else None,
        is_active=active)
    if created_at is not None:
        Service.objects.filter(pk=svc.pk).update(created_at=created_at)
    return svc


def _booking(client, handyman, service=None, status="completed"):
    return Booking.objects.create(
        client=client, handyman=handyman, service=service,
        booking_date=timezone.now() - timedelta(days=2),
        address="Rue 12", city="Abidjan", postal_code="00225", status=status)


def _ids(response):
    return [row["id"] for row in response.json()["results"]]


def _assert_no_sensitive(payload_text):
    for key in SENSITIVE_KEYS:
        assert f'"{key}"' not in payload_text, key
    for secret in ("secret-mail.test", "CNI-SECRET", "LIC-SECRET", "INS-SECRET"):
        assert secret not in payload_text, secret


# ======================= /handymen/featured/ =======================

@pytest.mark.django_db
def test_featured_only_approved_active_and_no_sensitive_fields(api_client):
    awa = _artisan("awa_f", "Awa", "Kone", commune="Cocody",
                   location=Point(-3.99, 5.36, srid=4326))
    _artisan("pending_f", "Paul", "Yao", approved=False, commune="Cocody")
    _artisan("banned_f", "Ali", "Traore", approved=True, active=False)

    r = api_client.get(reverse("handymen-featured"))
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["count"] == 1
    assert len(body["results"]) == 1
    card = body["results"][0]
    assert card["user_id"] == awa.id
    assert card["display_name"] == "Awa K."
    assert card["is_verified"] is True
    assert card["commune"] == "Cocody"
    assert set(card.keys()) == {
        "id", "display_name", "commune", "rating", "completed_jobs", "experience_years",
        "is_verified", "online", "photo", "user_id", "quartier", "hourly_rate", "skills",
        "services_count"}
    _assert_no_sensitive(r.content.decode())


@pytest.mark.django_db
def test_featured_display_name_fallbacks(api_client):
    _artisan("solo_f", "Mariam", "")
    _artisan("anon_f", "", "Bamba")
    names = {c["display_name"] for c in api_client.get(reverse("handymen-featured")).json()["results"]}
    assert names == {"Mariam", "Membre Tratra"}


@pytest.mark.django_db
def test_featured_filters_ordering_and_limit(api_client):
    plomb = _cat("Plomberie L1", "plomberie-l1")
    elec = _cat("Electricite L1", "electricite-l1")
    a = _artisan("a_f", "Ama", "Diallo", online=True, quality=10, commune="Cocody", skills=[plomb])
    b = _artisan("b_f", "Ben", "Kouassi", quality=90, commune="Yopougon", skills=[elec])
    c = _artisan("c_f", "Cheick", "Sow", quality=50, commune="Cocody Angré")
    _service(c, plomb, "Fuite", price="8000")  # catégorie via un service actif, sans skill
    d = _artisan("d_f", "Didier", "Ble", quality=99, commune="Marcory")
    _service(d, plomb, "Inactif", price="8000", active=False)  # service inactif : ne compte pas

    url = reverse("handymen-featured")

    def users(params=None):
        return [x["user_id"] for x in api_client.get(url, params or {}).json()["results"]]

    # en ligne d'abord, puis score qualité décroissant
    assert users() == [a.id, d.id, b.id, c.id]
    assert set(users({"category": plomb.id})) == {a.id, c.id}
    assert set(users({"categories": f"{elec.id},{plomb.id}"})) == {a.id, b.id, c.id}
    assert len(users({"categories": "abc,,-3"})) == 4  # valeurs invalides ignorées
    assert set(users({"commune": "cocody"})) == {a.id, c.id}
    assert users({"online": "1"}) == [a.id]

    r = api_client.get(url, {"limit": 1})
    assert r.json()["count"] == 4 and len(r.json()["results"]) == 1
    assert len(api_client.get(url, {"limit": 0}).json()["results"]) == 1   # borné à 1
    assert len(api_client.get(url, {"limit": 999}).json()["results"]) == 4  # borné à 24
    assert len(api_client.get(url, {"limit": "abc"}).json()["results"]) == 4  # défaut 8


@pytest.mark.django_db
def test_featured_is_public_even_with_invalid_bearer(api_client):
    _artisan("tok_f", "Awa", "Kone")
    api_client.credentials(HTTP_AUTHORIZATION=INVALID_BEARER)
    r = api_client.get(reverse("handymen-featured"))
    assert r.status_code == 200, r.content
    assert r.json()["count"] == 1


# ======================= /reviews/public/ =======================

@pytest.mark.django_db
def test_public_reviews_count_average_order_and_privacy(api_client):
    cat = _cat("Plomberie R1", "plomberie-r1")
    artisan = _artisan("art_r", "Awa", "Kone")
    client = _user("cli_r", first="Jean", last="Dupont")
    svc = _service(artisan, cat, "Réparation fuite", price="10000")

    now = timezone.now()
    specs = [  # (rating, comment, âge en heures)
        (5, "Super travail, très pro", 50),
        (4, "", 40),
        (3, "   ", 30),
        (4, None, 20),
        (2, "Correct mais en retard", 10),
    ]
    reviews = []
    for rating, comment, age in specs:
        rev = Review.objects.create(booking=_booking(client, artisan, svc),
                                    rating=rating, comment=comment)
        Review.objects.filter(pk=rev.pk).update(created_at=now - timedelta(hours=age))
        reviews.append(rev)

    api_client.credentials(HTTP_AUTHORIZATION=INVALID_BEARER)
    r = api_client.get(reverse("reviews-public"))
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["count"] == 5
    assert body["average"] == 3.6
    # seulement les avis commentés, du plus récent au plus ancien
    assert [x["id"] for x in body["results"]] == [reviews[4].id, reviews[0].id]
    first = body["results"][0]
    assert first["author"] == "Jean D."
    assert first["artisan"] == "Awa K."
    assert first["category"] == "Plomberie R1"
    assert first["rating"] == 2
    assert set(first.keys()) == {"id", "rating", "comment", "author", "artisan", "category", "created_at"}
    _assert_no_sensitive(r.content.decode())

    assert len(api_client.get(reverse("reviews-public"), {"limit": 1}).json()["results"]) == 1


@pytest.mark.django_db
def test_public_reviews_empty_state(api_client):
    r = api_client.get(reverse("reviews-public"))
    assert r.status_code == 200
    assert r.json() == {"count": 0, "average": None, "results": []}


# ======================= /public/stats/ =======================

@pytest.mark.django_db
def test_public_stats_real_values_and_cache(api_client):
    url = reverse("public-stats")
    assert url == "/handy/public/stats/"
    base = api_client.get(url).json()
    cache.clear()

    c1, c2 = _cat("Stat A", "stat-a"), _cat("Stat B", "stat-b")
    _cat("Stat off", "stat-off", active=False)
    a = _artisan("st_a", "Awa", "Kone", online=True)
    b = _artisan("st_b", "Ben", "Yao")
    _artisan("st_c", "Cy", "Zan", approved=False, online=True)  # non vérifié : ne compte pas
    _artisan("st_d", "Dan", "Ble", active=False, online=True)  # compte désactivé : ne compte pas
    s1 = _service(a, c1, "S1", price="1000")
    _service(b, c2, "S2", price="2000")
    _service(b, c2, "S3 off", price="2000", active=False)
    client = _user("st_cli", first="Jean", last="Dupont")
    Review.objects.create(booking=_booking(client, a, s1), rating=5, comment="Top")
    Review.objects.create(booking=_booking(client, b), rating=4, comment="")
    _booking(client, a, s1, status="pending")

    api_client.credentials(HTTP_AUTHORIZATION=INVALID_BEARER)
    r = api_client.get(url)
    assert r.status_code == 200, r.content
    data = r.json()
    assert set(data.keys()) == {"categories", "services", "artisans_verified", "artisans_online",
                                "missions_completed", "reviews_count", "rating_average"}
    assert data["categories"] - base["categories"] == 2
    assert data["services"] - base["services"] == 2
    assert data["artisans_verified"] - base["artisans_verified"] == 2
    assert data["artisans_online"] - base["artisans_online"] == 1
    assert data["missions_completed"] - base["missions_completed"] == 2
    assert data["reviews_count"] - base["reviews_count"] == 2
    if base["reviews_count"] == 0:
        assert data["rating_average"] == 4.5

    # Mise en cache 60 s : un nouveau service n'apparaît qu'après expiration / purge.
    _service(a, c1, "S4", price="1500")
    assert api_client.get(url).json()["services"] == data["services"]
    cache.clear()
    assert api_client.get(url).json()["services"] == data["services"] + 1


@pytest.mark.django_db
def test_public_stats_empty_rating_is_null(api_client):
    data = api_client.get(reverse("public-stats")).json()
    if data["reviews_count"] == 0:
        assert data["rating_average"] is None


# ======================= /services/ =======================

@pytest.mark.django_db
def test_services_public_payload_hides_email_and_embeds_artisan(api_client):
    cat = _cat("Peinture S1", "peinture-s1")
    awa = _artisan("awa_s", "Awa", "Kone", commune="Cocody", rating=4.5, completed=12)
    svc = _service(awa, cat, "Peinture salon", price="25000")
    # artisan sans profil (compte « client » ayant un service) -> artisan = None, pas de 500
    no_profile = _user("np_s", "client", "Nina", "Paul")
    svc2 = _service(no_profile, cat, "Sans profil", price="1000")

    r = api_client.get(reverse("services-list"), {"is_active": "true", "categories": cat.id})
    assert r.status_code == 200, r.content
    rows = {row["id"]: row for row in r.json()["results"]}
    row = rows[svc.id]
    assert set(row["handyman_detail"].keys()) == {"id", "first_name", "last_name", "user_type", "is_verified"}
    assert row["artisan"]["display_name"] == "Awa K."
    assert row["artisan"]["is_verified"] is True
    assert row["artisan"]["commune"] == "Cocody"
    assert row["artisan"]["completed_jobs"] == 12
    assert row["distance_km"] is None
    assert rows[svc2.id]["artisan"] is None
    _assert_no_sensitive(r.content.decode())

    detail = api_client.get(reverse("services-detail", args=[svc.id]))
    assert detail.status_code == 200
    assert "email" not in detail.json()["handyman_detail"]
    assert detail.json()["artisan"]["display_name"] == "Awa K."


@pytest.fixture
def catalogue(db):
    """3 catégories, 3 artisans (A vérifié en ligne, B vérifié hors ligne, C non vérifié)."""
    c1, c2, c3 = _cat("Cat1 L1", "cat1-l1"), _cat("Cat2 L1", "cat2-l1"), _cat("Cat3 L1", "cat3-l1")
    a = _artisan("a_s", "Ama", "Diallo", online=True, commune="Cocody", rating=4.8,
                 location=Point(-3.99, 5.36, srid=4326))
    b = _artisan("b_s", "Ben", "Kouassi", commune="Yopougon", rating=3.0,
                 location=Point(-4.07, 5.34, srid=4326))  # ~9 km de A
    c = _artisan("c_s", "Cheick", "Sow", approved=False, commune="Cocody",
                 location=Point(-5.03, 7.69, srid=4326))  # Bouaké, ~300 km
    t0 = timezone.now() - timedelta(days=10)
    s = {
        "a1": _service(a, c1, "A1", price="10000", created_at=t0),
        "a2": _service(a, c2, "A2", price="5000", price_type="hourly", created_at=t0 + timedelta(hours=1)),
        "b1": _service(b, c2, "B1", price="20000", created_at=t0 + timedelta(hours=2)),
        "c1": _service(c, c3, "C1", price=None, created_at=t0 + timedelta(hours=3)),
        "b2_off": _service(b, c1, "B2", price="1000", active=False, created_at=t0 + timedelta(hours=4)),
    }
    return {"cats": (c1, c2, c3), "users": (a, b, c), "svc": s}


@pytest.mark.django_db
def test_services_filters(api_client, catalogue):
    c1, c2, c3 = catalogue["cats"]
    a, b, c = catalogue["users"]
    s = catalogue["svc"]
    url = reverse("services-list")
    scope = f"{c1.id},{c2.id},{c3.id}"

    def ids(**params):
        params.setdefault("categories", scope)
        r = api_client.get(url, params)
        assert r.status_code == 200, r.content
        return set(_ids(r))

    # aucun filtre is_active implicite (comportement historique conservé)
    assert ids() == {s["a1"].id, s["a2"].id, s["b1"].id, s["c1"].id, s["b2_off"].id}
    active = {s["a1"].id, s["a2"].id, s["b1"].id, s["c1"].id}
    assert ids(is_active="true") == active
    assert ids(is_active="true", categories=f"{c1.id},{c2.id}") == {s["a1"].id, s["a2"].id, s["b1"].id}
    assert ids(categories=f"{c1.id},abc") == {s["a1"].id, s["b2_off"].id}
    assert ids(is_active="true", commune="cocody") == {s["a1"].id, s["a2"].id, s["c1"].id}
    assert ids(is_active="true", verified="1") == {s["a1"].id, s["a2"].id, s["b1"].id}
    assert ids(is_active="true", online="1") == {s["a1"].id, s["a2"].id}
    assert ids(is_active="true", min_price="6000") == {s["a1"].id, s["b1"].id}
    assert ids(is_active="true", max_price="10000") == {s["a1"].id, s["a2"].id}
    assert ids(is_active="true", min_price="abc", max_price="NaN") == active  # invalides ignorés
    assert ids(handyman=b.id) == {s["b1"].id, s["b2_off"].id}


@pytest.mark.django_db
def test_services_sorts(api_client, catalogue):
    c1, c2, c3 = catalogue["cats"]
    s = catalogue["svc"]
    url = reverse("services-list")
    base = {"is_active": "true", "categories": f"{c1.id},{c2.id},{c3.id}"}

    def order(**params):
        r = api_client.get(url, {**base, **params})
        assert r.status_code == 200, r.content
        return _ids(r)

    a1, a2, b1, c1s = s["a1"].id, s["a2"].id, s["b1"].id, s["c1"].id
    assert order() == [c1s, b1, a2, a1]                      # défaut : -created_at
    assert order(sort="recent") == [c1s, b1, a2, a1]
    assert order(sort="price_asc") == [a2, a1, b1, c1s]      # sur devis (NULL) en dernier
    assert order(sort="price_desc") == [b1, a1, a2, c1s]     # NULL en dernier aussi
    assert order(sort="rating") == [a2, a1, b1, c1s]         # 4.8 > 3.0 > 0, puis récents
    assert order(sort="n_importe_quoi") == [c1s, b1, a2, a1]  # valeur inconnue ignorée
    # ?ordering= (DRF) reste prioritaire sur ?sort=
    assert order(sort="price_desc", ordering="created_at") == [a1, a2, b1, c1s]


@pytest.mark.django_db
def test_services_nearby_filters_and_distance(api_client, catalogue):
    c1, c2, c3 = catalogue["cats"]
    s = catalogue["svc"]
    url = reverse("services-nearby")
    origin = {"lat": "5.36", "lng": "-3.99", "radius_km": "20"}
    api_client.credentials(HTTP_AUTHORIZATION=INVALID_BEARER)  # endpoint public : jeton ignoré

    r = api_client.get(url, origin)
    assert r.status_code == 200, r.content
    rows = r.json()["results"]
    assert [row["id"] for row in rows][:2] in ([s["a1"].id, s["a2"].id], [s["a2"].id, s["a1"].id])
    assert {row["id"] for row in rows} == {s["a1"].id, s["a2"].id, s["b1"].id}  # C hors rayon, B2 inactif
    dist = {row["id"]: row["distance_km"] for row in rows}
    assert dist[s["a1"].id] == pytest.approx(0, abs=0.05)
    assert 5 < dist[s["b1"].id] < 15
    assert all("email" not in row["handyman_detail"] for row in rows)

    def ids(**params):
        resp = api_client.get(url, {**origin, **params})
        assert resp.status_code == 200, resp.content
        return set(_ids(resp))

    assert ids(categories=str(c2.id)) == {s["a2"].id, s["b1"].id}
    assert ids(categories=f"{c1.id},xyz") == {s["a1"].id}
    assert ids(commune="yop") == {s["b1"].id}
    assert ids(verified="1", online="1") == {s["a1"].id, s["a2"].id}
    assert ids(category_id=str(c1.id)) == {s["a1"].id}
    assert ids(max_price="10000") == {s["a1"].id, s["a2"].id}


@pytest.mark.django_db
def test_services_nearby_bad_params(api_client):
    url = reverse("services-nearby")
    assert api_client.get(url).status_code == 400
    assert api_client.get(url, {"lat": "5.36"}).status_code == 400
    assert api_client.get(url, {"lat": "abc", "lng": "-3.99"}).status_code == 400
    assert api_client.get(url, {"lat": "95", "lng": "-3.99"}).status_code == 400
    assert api_client.get(url, {"lat": "5.36", "lng": "-3.99", "radius_km": "-1"}).status_code == 400
    assert api_client.get(url, {"lat": "5.36", "lng": "-3.99", "category_id": "999999"}).status_code == 400
    assert api_client.get(url, {"lat": "5.36", "lng": "-3.99", "category_id": "abc"}).status_code == 400


# ======================= /categories/ =======================

@pytest.mark.django_db
def test_categories_services_count_and_inactive_hidden(api_client):
    a = _artisan("cat_a", "Awa", "Kone")
    full = _cat("Zlot Plein", "zlot-plein")
    empty = _cat("Zlot Vide", "zlot-vide")
    off = _cat("Zlot Off", "zlot-off", active=False)
    _service(a, full, "S1", price="1000")
    _service(a, full, "S2", price="1000")
    _service(a, full, "S3 inactif", price="1000", active=False)
    _service(a, off, "S4", price="1000")

    url = reverse("categories-list")
    r = api_client.get(url, {"search": "zlot", "page_size": 100, "ordering": "name"})
    assert r.status_code == 200, r.content
    rows = r.json()["results"]
    assert [x["slug"] for x in rows] == ["zlot-plein", "zlot-vide"]  # inactive masquée
    counts = {x["slug"]: x["services_count"] for x in rows}
    assert counts == {"zlot-plein": 2, "zlot-vide": 0}

    r = api_client.get(url, {"search": "zlot", "ordering": "-services_count"})
    assert [x["slug"] for x in r.json()["results"]] == ["zlot-plein", "zlot-vide"]

    assert api_client.get(reverse("categories-detail", args=[off.id])).status_code == 404
    assert api_client.get(reverse("categories-detail", args=[empty.id])).status_code == 200

    staff = _user("staff_cat", "admin", is_staff=True)
    api_client.force_authenticate(user=staff)
    slugs = {x["slug"] for x in api_client.get(url, {"search": "zlot"}).json()["results"]}
    assert slugs == {"zlot-plein", "zlot-vide", "zlot-off"}


# ======================= /slides/ (repli mobile) =======================

DEAD_IMAGES = ("1581579188871-cfe9b0b2ce6c", "1621905251918-3850a8f4257b")


@pytest.mark.django_db
def test_hero_slides_fallback_has_no_fake_promo(api_client):
    assert not HeroSlide.objects.exists()
    cat = _cat("Plomberie H1", "plomberie-h1")
    a = _artisan("hs_a", "Awa", "Kone")
    _service(a, cat, "Fuite", price="5000")

    r = api_client.get(reverse("slides-list"))
    assert r.status_code == 200, r.content
    slides = r.json()
    assert len(slides) >= 2
    for slide in slides:
        text = f"{slide['title']} {slide['subtitle']}"
        assert "%" not in text and "-20" not in text
        assert "certifi" not in text.lower()
        assert slide["image"].startswith("https://images.unsplash.com/photo-")
        assert not any(dead in slide["image"] for dead in DEAD_IMAGES)
        # contrat Flutter (HeroSlideModel.fromJson)
        assert {"title", "subtitle", "image", "gradient", "cta_label", "cta_action", "ctaParams"} <= set(slide)
        assert isinstance(slide["gradient"], list) and len(slide["gradient"]) == 2
    titles = [x["title"] for x in slides]
    assert "Artisans vérifiés" in titles
    verified = next(x for x in slides if x["title"] == "Artisans vérifiés")
    assert verified["subtitle"] == "Identité et documents contrôlés"


@pytest.mark.django_db
def test_hero_slides_category_slide_uses_real_count(api_client):
    Service.objects.update(is_active=False)
    cat = _cat("Zz Electricite H2", "zz-electricite-h2")
    a = _artisan("hs_b", "Awa", "Kone")
    _service(a, cat, "Prise", price="5000")
    slides = api_client.get(reverse("slides-list")).json()
    cat_slides = [x for x in slides if x["cta_action"] == "open_category"]
    assert len(cat_slides) == 1
    assert cat_slides[0]["ctaParams"] == {"category_id": cat.id}
    assert cat_slides[0]["subtitle"] == "1 service proposé sur Tratra"

    Service.objects.update(is_active=False)
    slides = api_client.get(reverse("slides-list")).json()
    assert not [x for x in slides if x["cta_action"] == "open_category"]  # pas de catégorie vide mise en avant


# ======================= Correctifs de revue du Lot 1 =======================

# ---------- #3 : min_price / max_price démesurés -> jamais de 500 ----------

def test_decimal_param_is_bounded_to_price_column():
    assert _decimal_param("1e131072") == Decimal("99999999.99")
    assert _decimal_param("-1e131072") == Decimal("-99999999.99")
    assert _decimal_param("1e-20000") == Decimal("0.00")
    assert _decimal_param(" 12.5 ") == Decimal("12.50")
    for raw in (None, "", "  ", "abc", "NaN", "sNaN", "Infinity", "-inf", "1\x00"):
        assert _decimal_param(raw) is None, raw


@pytest.mark.django_db
def test_huge_or_tiny_prices_never_500(api_client, catalogue):
    c1, c2, c3 = catalogue["cats"]
    s = catalogue["svc"]
    scope = {"is_active": "true", "categories": f"{c1.id},{c2.id},{c3.id}"}
    nearby = {"lat": "5.36", "lng": "-3.99", "radius_km": "20"}
    priced = {s["a1"].id, s["a2"].id, s["b1"].id}  # c1 est « sur devis » (prix NULL)

    def ids(url, **params):
        r = api_client.get(url, params)
        assert r.status_code == 200, (params, r.content)
        return set(_ids(r))

    services = reverse("services-list")
    assert ids(services, **scope, min_price="1e131072") == set()             # au-delà de tout prix
    assert ids(services, **scope, max_price="1E+999999") == priced           # pas de plafond
    assert ids(services, **scope, min_price="1e-20000") == priced            # ~0
    assert ids(services, **scope, min_price="-1e131072", max_price="-1e131072") == set()

    url = reverse("services-nearby")
    assert ids(url, **nearby, min_price="1e131072") == set()
    assert ids(url, **nearby, max_price="1E+999999") == priced
    assert ids(url, **nearby, min_price="1e-20000") == priced


# ---------- #5 / #10 : intégrité des avis ----------

@pytest.fixture
def review_ctx(db):
    cat = _cat("Plomberie AV", "plomberie-av")
    artisan = _artisan("art_av", "Awa", "Kone")
    client = _user("cli_av", first="Jean", last="Dupont")
    other = _user("oth_av", first="Marie", last="Kouame")
    svc = _service(artisan, cat, "Fuite", price="10000")
    return {"artisan": artisan, "client": client, "other": other, "svc": svc}


def _rating_of(user):
    return HandymanProfile.objects.get(user=user).rating


@pytest.mark.django_db
def test_review_create_requires_own_completed_booking(api_client, review_ctx):
    artisan, client, svc = review_ctx["artisan"], review_ctx["client"], review_ctx["svc"]
    url = reverse("reviews-list")
    pending = _booking(client, artisan, svc, status="pending")
    someone_else = _booking(review_ctx["other"], artisan, svc)
    done = _booking(client, artisan, svc)

    api_client.force_authenticate(user=client)
    r = api_client.post(url, {"booking": pending.id, "rating": 1, "comment": "Nul"}, format="json")
    assert r.status_code == 400 and "booking" in r.json(), r.content
    assert not Review.objects.filter(booking=pending).exists()

    r = api_client.post(url, {"booking": someone_else.id, "rating": 1}, format="json")
    assert r.status_code == 403
    assert not Review.objects.filter(booking=someone_else).exists()

    r = api_client.post(url, {"booking": done.id, "rating": 4, "comment": "Bien"}, format="json")
    assert r.status_code == 201, r.content
    assert _rating_of(artisan) == 4.0
    # Un seul avis par mission : 400 explicite, pas d'IntegrityError (500).
    assert api_client.post(url, {"booking": done.id, "rating": 5}, format="json").status_code == 400

    # L'artisan noté ne peut pas créer d'avis sur sa propre mission (il n'en est pas le client)…
    api_client.force_authenticate(user=artisan)
    assert api_client.post(url, {"booking": done.id, "rating": 5}, format="json").status_code == 403
    # … ni s'auto-évaluer : la base refuse une réservation dont il serait aussi le client.
    with transaction.atomic(), pytest.raises(IntegrityError):
        _booking(artisan, artisan, svc)


@pytest.mark.django_db
def test_review_only_author_can_edit_or_delete(api_client, review_ctx):
    artisan, client, svc = review_ctx["artisan"], review_ctx["client"], review_ctx["svc"]
    booking = _booking(client, artisan, svc)
    review = Review.objects.create(booking=booking, rating=1, comment="Travail bâclé")
    detail = reverse("reviews-detail", args=[review.id])

    # L'artisan noté peut lire l'avis, jamais le réécrire ni le supprimer.
    api_client.force_authenticate(user=artisan)
    assert api_client.get(detail).status_code == 200
    r = api_client.patch(detail, {"rating": 5, "comment": "Travail parfait"}, format="json")
    assert r.status_code == 403, r.content
    r = api_client.put(detail, {"booking": booking.id, "rating": 5, "comment": "Top"}, format="json")
    assert r.status_code == 403
    assert api_client.delete(detail).status_code == 403
    review.refresh_from_db()
    assert (review.rating, review.comment) == (1, "Travail bâclé")

    # L'auteur ne peut pas rattacher son avis à la mission d'un autre client.
    other_booking = _booking(review_ctx["other"], artisan, svc)
    api_client.force_authenticate(user=client)
    r = api_client.patch(detail, {"booking": other_booking.id}, format="json")
    assert r.status_code == 400 and "booking" in r.json(), r.content
    review.refresh_from_db()
    assert review.booking_id == booking.id

    # L'auteur peut corriger sa note (la note de l'artisan suit), puis supprimer l'avis.
    r = api_client.patch(detail, {"booking": booking.id, "rating": 3}, format="json")
    assert r.status_code == 200, r.content
    assert _rating_of(artisan) == 3.0
    assert api_client.delete(detail).status_code == 204
    assert _rating_of(artisan) == 0


@pytest.mark.django_db
def test_only_reviews_of_completed_missions_are_published(api_client, review_ctx):
    artisan, client, svc = review_ctx["artisan"], review_ctx["client"], review_ctx["svc"]
    stats_url = reverse("public-stats")
    base = api_client.get(stats_url).json()
    cache.clear()

    Review.objects.create(booking=_booking(client, artisan, svc), rating=5, comment="Très bon travail")
    # Avis antérieurs au contrôle, sur des missions non terminées.
    Review.objects.create(booking=_booking(review_ctx["other"], artisan, svc, status="pending"),
                          rating=1, comment="Faux avis sur mission en attente")
    Review.objects.create(booking=_booking(_user("third_av"), artisan, svc, status="cancelled"),
                          rating=1, comment="Avis sur mission annulée")

    body = api_client.get(reverse("reviews-public")).json()
    assert body["count"] == 1
    assert body["average"] == 5.0
    assert [x["comment"] for x in body["results"]] == ["Très bon travail"]

    stats = api_client.get(stats_url).json()
    assert stats["reviews_count"] - base["reviews_count"] == 1
    if base["reviews_count"] == 0:
        assert stats["rating_average"] == 5.0

    # Le tri « Mieux notés » repose sur HandymanProfile.rating (signal) : mêmes règles.
    assert _rating_of(artisan) == 5.0


# ---------- #9 / #15 : « Commune ou quartier » ----------

@pytest.mark.django_db
def test_commune_param_matches_commune_or_quartier(api_client):
    cat = _cat("Quartier Q1", "quartier-q1")
    a = _artisan("q_a", "Awa", "Kone", commune="Cocody", quartier="Palmeraie",
                 location=Point(-3.99, 5.36, srid=4326))
    b = _artisan("q_b", "Ben", "Yao", commune="Yopougon", quartier="Niangon",
                 location=Point(-4.0, 5.35, srid=4326))
    sa = _service(a, cat, "Fuite", price="5000")
    sb = _service(b, cat, "Prise", price="5000")

    def service_ids(url, **params):
        r = api_client.get(url, {"categories": cat.id, **params})
        assert r.status_code == 200, r.content
        return set(_ids(r))

    services, nearby = reverse("services-list"), reverse("services-nearby")
    origin = {"lat": "5.36", "lng": "-3.99"}
    assert service_ids(services, commune="palmeraie") == {sa.id}   # quartier
    assert service_ids(services, commune="yopougon") == {sb.id}    # commune
    assert service_ids(nearby, commune="NIANGON", **origin) == {sb.id}

    featured = api_client.get(reverse("handymen-featured"), {"commune": "palmeraie"}).json()
    assert [x["user_id"] for x in featured["results"]] == [a.id]


# ---------- #12 : /services/nearby/ paginé sans doublon ni trou ----------

@pytest.mark.django_db
def test_nearby_pagination_is_total_and_stable(api_client):
    cat = _cat("Ex aequo N1", "ex-aequo-n1")
    artisan = _artisan("tie_a", "Awa", "Kone", rating=4.0, location=Point(-3.99, 5.36, srid=4326))
    # > 24 lignes à distance, note et prix identiques : sans clé unique, Postgres
    # peut ordonner les ex aequo différemment d'une page (LIMIT/OFFSET) à l'autre.
    created = Service.objects.bulk_create([
        Service(handyman=artisan, category=cat, title=f"S{i}", description="d",
                price_type="quote" if i % 2 else "fixed",
                price=None if i % 2 else Decimal("5000"))
        for i in range(30)
    ])
    fixed = sorted(svc.id for svc in created if svc.price is not None)
    quote = sorted(svc.id for svc in created if svc.price is None)

    url = reverse("services-nearby")
    params = {"lat": "5.36", "lng": "-3.99", "categories": cat.id, "page_size": 12}
    seen = []
    for page in (1, 2, 3):
        r = api_client.get(url, {**params, "page": page})
        assert r.status_code == 200, r.content
        assert r.json()["count"] == 30
        seen.extend(_ids(r))
    assert len(seen) == len(set(seen)) == 30
    # distance, note, prix (sur devis en dernier), puis id.
    assert seen == fixed + quote

    qs = search_services_nearby_qs(Point(-3.99, 5.36, srid=4326))
    assert qs.query.order_by[-1] == "id"


# ---------- #13 : la recherche par mot-clé couvre le métier ----------

@pytest.mark.django_db
def test_service_search_matches_category_name_and_slug(api_client):
    plomb = _cat("Plomberie K1", "plomberie-k1")
    menage = _cat("Ménage K1", "menage-k1")
    a = _artisan("kw_a", "Awa", "Kone")
    s_plomb = _service(a, plomb, "Réparations", price="5000")
    s_menage = _service(a, menage, "Grand nettoyage", price="5000")
    url = reverse("services-list")

    def ids(term):
        r = api_client.get(url, {"is_active": "true", "search": term, "page_size": 100})
        assert r.status_code == 200, r.content
        return set(_ids(r))

    found = ids("plomberie")
    assert s_plomb.id in found and s_menage.id not in found
    found = ids("menage")  # sans accent : trouvé via le slug
    assert s_menage.id in found and s_plomb.id not in found


# ---------- #14 : services_count des artisans à la une ----------

@pytest.mark.django_db
def test_featured_exposes_active_services_count(api_client):
    cat = _cat("Compte F1", "compte-f1")
    busy = _artisan("cnt_a", "Awa", "Kone", quality=90)
    idle = _artisan("cnt_b", "Ben", "Yao", quality=10, skills=[cat])
    _service(busy, cat, "S1", price="1000")
    _service(busy, cat, "S2", price="1000")
    _service(busy, cat, "S3 inactif", price="1000", active=False)

    url = reverse("handymen-featured")
    counts = {x["user_id"]: x["services_count"] for x in api_client.get(url).json()["results"]}
    assert counts == {busy.id: 2, idle.id: 0}

    body = api_client.get(url, {"category": cat.id}).json()  # filtre EXISTS + annotation
    assert body["count"] == 2
    assert {x["user_id"]: x["services_count"] for x in body["results"]} == counts


# ---------- #16 : octet NUL dans ?commune= -> jamais de 500 ----------

@pytest.mark.django_db
def test_nul_byte_in_commune_never_500(api_client, catalogue):
    assert api_client.get(reverse("services-list"), {"commune": "a\x00b"}).status_code == 200
    r = api_client.get(reverse("services-nearby"), {"lat": "5.36", "lng": "-3.99", "commune": "\x00"})
    assert r.status_code == 200, r.content
    assert r.json()["count"] == 3  # commune vide après nettoyage : aucun filtre
    r = api_client.get(reverse("handymen-featured"), {"commune": "\x00"})
    assert r.status_code == 200, r.content
    assert api_client.get(reverse("handymen-featured"), {"commune": "Coco\x00dy"}).status_code == 200


# ---------- #7 : offres Entreprise sans fonctionnalité fictive ----------

NONEXISTENT_B2B = {"Comptes collaborateurs", "Facturation centralisée",
                   "Gestionnaire de compte dédié", "SLA prioritaire"}


@pytest.mark.django_db
def test_business_plans_no_longer_promise_missing_features(api_client):
    r = api_client.get(reverse("subscription-plans-list"), {"audience": "business"})
    assert r.status_code == 200, r.content
    rows = r.json()["results"] if isinstance(r.json(), dict) else r.json()
    for plan in rows:
        assert not NONEXISTENT_B2B & set(plan["features"]), plan


@pytest.mark.django_db
def test_clean_business_plan_features_migration_roundtrip():
    from django.apps import apps as django_apps

    from handy.models import SubscriptionPlan
    migration = importlib.import_module("handy.migrations.0028_clean_business_plan_features")
    monthly, _ = SubscriptionPlan.objects.update_or_create(
        slug="entreprise-mensuel",
        defaults={"name": "Entreprise", "audience": "business", "price": Decimal("25000"),
                  "features": list(migration.SEEDED["entreprise-mensuel"])})
    yearly, _ = SubscriptionPlan.objects.update_or_create(
        slug="entreprise-annuel",
        defaults={"name": "Entreprise (annuel)", "audience": "business", "price": Decimal("250000"),
                  "interval": "yearly", "features": ["Offre négociée", "SLA prioritaire"]})

    migration.clean_features(django_apps, None)
    monthly.refresh_from_db()
    yearly.refresh_from_db()
    assert monthly.features == migration.CLEANED["entreprise-mensuel"]
    assert yearly.features == ["Offre négociée"]  # retouche admin conservée, promesse fictive retirée

    migration.restore_features(django_apps, None)
    monthly.refresh_from_db()
    yearly.refresh_from_db()
    assert monthly.features == migration.SEEDED["entreprise-mensuel"]
    assert yearly.features == ["Offre négociée"]  # non écrite par le nettoyage : laissée telle quelle


# ---------- #2 / #8 / #11 : TTL de signature médias publics ≠ KYC ----------

_S3_ENV = {
    "DJANGO_SETTINGS_MODULE": "tratra.settings",
    "DJANGO_ENV": "dev",
    "MINIO_ENABLED": "True",
    "KYC_STORAGE_BUCKET_NAME": "kyc-test",
    "AWS_ACCESS_KEY_ID": "test-key",
    "AWS_SECRET_ACCESS_KEY": "test-secret",
    "AWS_STORAGE_BUCKET_NAME": "media-test",
    "AWS_S3_ENDPOINT_URL": "https://minio.invalid",
    "KYC_SIGNED_URL_TTL_SECONDS": "300",
}
_PROBE = (
    "import json, django; django.setup(); "
    "from django.conf import settings; from django.core.files.storage import storages; "
    "print(json.dumps({'media': storages['default'].querystring_expire, "
    "'kyc': storages['private_kyc'].querystring_expire, "
    "'aws': settings.AWS_QUERYSTRING_EXPIRE}))"
)


def _probe_settings(**overrides):
    """Charge les settings MinIO dans un processus neuf (ils sont lus à l'import)."""
    env = {k: v for k, v in os.environ.items() if k != "MEDIA_SIGNED_URL_TTL_SECONDS"}
    env.update(_S3_ENV, **overrides)
    return subprocess.run([sys.executable, "-c", _PROBE], cwd=str(settings.BASE_DIR), env=env,
                          capture_output=True, text=True, timeout=120)


def test_public_media_ttl_is_decoupled_from_kyc_ttl():
    proc = _probe_settings()
    assert proc.returncode == 0, proc.stderr[-2000:]
    ttl = json.loads(proc.stdout.strip().splitlines()[-1])
    assert ttl == {"media": 604800, "kyc": 300, "aws": 604800}

    proc = _probe_settings(MEDIA_SIGNED_URL_TTL_SECONDS="86400")
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == {"media": 86400, "kyc": 300, "aws": 86400}

    for bad in ("60", "999999"):
        proc = _probe_settings(MEDIA_SIGNED_URL_TTL_SECONDS=bad)
        assert proc.returncode != 0
        assert "MEDIA_SIGNED_URL_TTL_SECONDS" in proc.stderr
