"""Éligibilité des artisans : publication publique ET missions (handy/eligibility.py).

Règle : compte actif + profil approuvé + KYC approuvé (pièce d'identité) + profil complet.
"""
from datetime import timedelta

import pytest
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from handy.eligibility import is_publishable, publishable
from handy.models import (
    Booking, HandymanDocument, HandymanProfile, Service, ServiceCategory, TimeOff, User,
)
from handy.services.matching import match_artisans
from handy.testing import make_eligible

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def artisan(username, *, eligible=True, active=True, online=False):
    user = User.objects.create_user(
        username=username, email=f"{username}@x.test", password="pass1234",
        user_type="handyman", is_active=active)
    profile = user.handyman_profile
    if eligible:
        make_eligible(profile, category=ServiceCategory.objects.get_or_create(
            slug="plomberie", defaults={"name": "Plomberie"})[0])
    profile.online = online
    profile.location = Point(-4.0083, 5.36, srid=4326)
    profile.save()
    return user


def service(user, title="Dépannage", active=True):
    cat = ServiceCategory.objects.get_or_create(slug="plomberie", defaults={"name": "Plomberie"})[0]
    return Service.objects.create(
        handyman=user, category=cat, title=title, description="d", price_type="fixed", price=5000,
        is_active=active)


# ---- La règle : SQL et Python concordent -----------------------------------------------------

BREAKERS = {
    "complet": lambda p: None,
    "non_approuve": lambda p: setattr(p, "is_approved", False),
    "sans_bio": lambda p: setattr(p, "bio", ""),
    "sans_experience": lambda p: setattr(p, "experience_years", 0),
    "sans_zone": lambda p: setattr(p, "commune", ""),
    "sans_photo": lambda p: setattr(p, "photo", ""),
    "sans_specialite": lambda p: p.skills.clear(),
    "kyc_en_attente": lambda p: HandymanDocument.objects.filter(handyman=p).update(status="pending"),
    "kyc_rejete": lambda p: HandymanDocument.objects.filter(handyman=p).update(status="rejected"),
    "sans_document": lambda p: HandymanDocument.objects.filter(handyman=p).delete(),
}


def test_licence_cni_assurance_ne_sont_pas_requises():
    """Champs en lecture seule dans l'API : l'artisan ne peut pas les renseigner lui-même."""
    user = artisan("sans_numeros")
    p = user.handyman_profile
    p.license_number = p.cni_number = p.insurance_info = None
    p.save()
    assert is_publishable(HandymanProfile.objects.get(pk=p.pk)) is True


def test_checklist_reflects_the_rule():
    from handy.eligibility import profile_checklist
    user = artisan("liste", eligible=False)
    items = {i["key"]: i["done"] for i in profile_checklist(user.handyman_profile)}
    assert items == {"bio": False, "skills": False, "experience": False, "zone": False,
                     "photo": False, "kyc": False, "approval": False}
    make_eligible(user.handyman_profile)
    assert all(i["done"] for i in profile_checklist(HandymanProfile.objects.get(user=user)))


@pytest.mark.parametrize("case", sorted(BREAKERS))
def test_rule_sql_matches_python(case):
    user = artisan(f"a_{case}")
    profile = user.handyman_profile
    BREAKERS[case](profile)
    profile.save()
    profile = HandymanProfile.objects.get(pk=profile.pk)
    expected = case == "complet"
    assert is_publishable(profile) is expected
    assert publishable().filter(pk=profile.pk).exists() is expected


def test_inactive_account_is_not_publishable():
    user = artisan("inactif", active=False)
    assert not publishable().filter(user=user).exists()
    assert is_publishable(HandymanProfile.objects.get(user=user)) is False


# ---- Publication ------------------------------------------------------------------------------

def test_public_services_only_from_eligible_artisans():
    ok = service(artisan("ok"), "Service OK")
    service(artisan("incomplet", eligible=False), "Service incomplet")
    service(artisan("suspendu", active=False), "Service suspendu")
    service(artisan("autre"), "Service désactivé", active=False)
    r = APIClient().get(reverse("services-list"))
    assert r.status_code == 200
    assert [s["id"] for s in r.json()["results"]] == [ok.id]


def test_public_stats_count_only_eligible():
    artisan("e1", online=True)
    artisan("e2")
    artisan("non", eligible=False, online=True)
    r = APIClient().get("/handy/public/stats/")
    assert r.status_code == 200
    assert r.json()["artisans_verified"] == 2
    assert r.json()["artisans_online"] == 1


def test_match_excludes_ineligible():
    cat = ServiceCategory.objects.get_or_create(slug="plomberie", defaults={"name": "Plomberie"})[0]
    good = artisan("m_ok", online=True)
    bad = artisan("m_bad", eligible=False, online=True)
    bad.handyman_profile.skills.add(cat)
    ids = [p.user_id for p in match_artisans(5.36, -4.0083, cat.id)]
    assert good.id in ids and bad.id not in ids


# ---- Urgent -----------------------------------------------------------------------------------

def test_urgent_means_online_now_and_not_on_timeoff():
    online = service(artisan("u_online", online=True), "En ligne")
    service(artisan("u_offline", online=False), "Hors ligne")
    away = artisan("u_conge", online=True)
    service(away, "En congé")
    now = timezone.now()
    TimeOff.objects.create(handyman=away.handyman_profile, start=now - timedelta(hours=1),
                           end=now + timedelta(hours=1))
    client = APIClient()
    for flag in ("1", "true"):
        r = client.get(reverse("services-list"), {"urgent": flag})
        assert [s["id"] for s in r.json()["results"]] == [online.id], flag
    # Sans le paramètre : tout le catalogue publié (3 services).
    assert client.get(reverse("services-list")).json()["count"] == 3


# ---- Missions ---------------------------------------------------------------------------------

def _book(client, svc):
    return client.post("/handy/bookings/", {
        "service": svc.id, "handyman": svc.handyman_id, "booking_date": (timezone.now() + timedelta(days=2)).isoformat(),
        "address": "Rue 12", "city": "Abidjan", "postal_code": "00225", "type": "scheduled",
    }, format="json")


def test_booking_requires_eligible_handyman():
    client_user = User.objects.create_user(
        username="cli", email="cli@x.test", password="pass1234", user_type="client")
    api = APIClient()
    api.force_authenticate(client_user)
    good = service(artisan("b_ok"))
    bad = service(artisan("b_bad", eligible=False))
    r_bad = _book(api, bad)
    assert r_bad.status_code == 400, r_bad.content
    assert "handyman" in r_bad.json() or "handyman" in str(r_bad.json())
    assert not Booking.objects.filter(service=bad).exists()
    r_ok = _book(api, good)
    assert r_ok.status_code == 201, r_ok.content


def test_category_name_filter_is_applied():
    """L'app mobile filtre par nom de catégorie (`category__name`) : le filtre doit être réel."""
    a = service(artisan("c_ok"), "Plomberie A")
    other_cat = ServiceCategory.objects.create(name="Électricité", slug="electricite")
    b = Service.objects.create(handyman=a.handyman, category=other_cat, title="Prises", description="d",
                               price_type="fixed", price=1000, is_active=True)
    client = APIClient()
    r = client.get(reverse("services-list"), {"category__name": "Électricité"})
    assert [s["id"] for s in r.json()["results"]] == [b.id]
    r = client.get(reverse("services-list"), {"category__name": "plomberie"})
    assert [s["id"] for s in r.json()["results"]] == [a.id]


# ---- Surfaces publiques : fiches, catégories, avis, propriétaire ---------------------------------

def test_service_detail_is_hidden_unless_published_or_owner():
    ok = service(artisan("det_ok"), "Publié")
    hidden = service(artisan("det_inc", eligible=False), "Non publié")
    off = service(artisan("det_off"), "Désactivé", active=False)
    anon = APIClient()
    assert anon.get(reverse("services-detail", args=[ok.id])).status_code == 200
    for s in (hidden, off):
        assert anon.get(reverse("services-detail", args=[s.id])).status_code == 404
    # un autre compte connecté ne le voit pas non plus
    other = APIClient()
    other.force_authenticate(User.objects.create_user("autre_c", "a@x.test", "pass1234"))
    assert other.get(reverse("services-detail", args=[hidden.id])).status_code == 404
    # le propriétaire garde l'accès à ses propres services, publiés ou non
    owner = APIClient()
    owner.force_authenticate(hidden.handyman)
    assert owner.get(reverse("services-detail", args=[hidden.id])).status_code == 200


def test_category_counts_and_public_reviews_ignore_unpublished_artisans():
    ok = service(artisan("cnt_ok"), "A")
    service(artisan("cnt_bad", eligible=False), "B")
    cat = ok.category
    row = next(c for c in APIClient().get(reverse("categories-list")).json()["results"] if c["id"] == cat.id)
    assert row["services_count"] == 1
    r = APIClient().get(reverse("services-list"), {"categories": cat.id})
    assert r.json()["count"] == 1
    assert APIClient().get("/handy/public/stats/").json()["services"] == 1


def test_owner_lists_own_services_but_public_listing_stays_restricted():
    me = artisan("mine", eligible=False)
    own = service(me, "Brouillon", active=False)
    pub = service(artisan("pub"), "Public")
    c = APIClient()
    c.force_authenticate(me)
    ids = {s["id"] for s in c.get(reverse("services-list"), {"handyman": me.id}).json()["results"]}
    assert ids == {own.id}
    public_ids = {s["id"] for s in c.get(reverse("services-list")).json()["results"]}
    assert public_ids == {pub.id}
