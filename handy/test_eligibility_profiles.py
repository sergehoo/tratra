"""Éligibilité sur TOUTES les fiches publiques d'artisans, y compris par accès direct (id connu)."""
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from handy.models import HandymanProfile
from handy.test_eligibility import BREAKERS, artisan, service

User = get_user_model()
pytestmark = pytest.mark.django_db

SENSITIVE = ("email", "phone", "cni_number", "license_number", "insurance_info", "location", "kyc", "document")


def _viewer(username="viewer"):
    c = APIClient()
    c.force_authenticate(User.objects.create_user(username, f"{username}@x.test", "pass1234"))
    return c


@pytest.mark.parametrize("case", [k for k in BREAKERS if k != "complet"])
def test_every_ineligibility_hides_the_artisan_everywhere(case):
    user = artisan("hid_" + case, online=True)
    profile = user.handyman_profile
    BREAKERS[case](profile)
    profile.save()
    svc = service(user, "Service " + case)
    anon, viewer = APIClient(), _viewer("v_" + case)

    # liste « artisans mis en avant »
    assert [c["user_id"] for c in anon.get(reverse("handymen-featured")).json()["results"]] == []
    # accès DIRECT par identifiant : aucun accès tiers, mêmes réponses qu'un profil inexistant
    assert viewer.get(f"/handy/handymen/{profile.id}/").status_code == 404
    assert anon.get(f"/handy/handymen/{profile.id}/").status_code in (401, 403, 404)
    ghost = HandymanProfile.objects.order_by("-id").first().id + 1000
    assert viewer.get(f"/handy/handymen/{ghost}/").status_code == 404
    # son service : liste, recherche, fiche, proximité
    assert svc.id not in {s["id"] for s in anon.get(reverse("services-list")).json()["results"]}
    assert svc.id not in {s["id"] for s in anon.get(reverse("services-list"), {"search": "Service"}).json()["results"]}
    assert anon.get(reverse("services-detail", args=[svc.id])).status_code == 404
    assert viewer.get(reverse("services-detail", args=[svc.id])).status_code == 404
    near = anon.get(reverse("services-nearby"), {"lat": "5.36", "lng": "-4.0083", "radius_km": "50"})
    assert svc.id not in {s["id"] for s in near.json()["results"]}
    # lui-même et le staff gardent l'accès
    owner = APIClient()
    owner.force_authenticate(user)
    assert owner.get(f"/handy/handymen/{profile.id}/").status_code == 200
    assert owner.get(reverse("services-detail", args=[svc.id])).status_code == 200
    staff = APIClient()
    staff.force_authenticate(User.objects.create_user("staff_" + case, "s@x.test", "pass1234", is_staff=True))
    assert staff.get(f"/handy/handymen/{profile.id}/").status_code == 200


def test_eligible_artisan_is_public_by_direct_access_without_sensitive_data():
    user = artisan("direct_ok", online=True)
    profile = user.handyman_profile
    profile.cni_number, profile.license_number, profile.insurance_info = "CNI-1", "LIC-1", "INS-1"
    profile.save()
    r = _viewer().get(f"/handy/handymen/{profile.id}/")
    assert r.status_code == 200
    body = r.content.decode().lower()
    assert not any(word in r.json() for word in SENSITIVE), r.json().keys()
    assert not any(secret in body for secret in ("cni-1", "lic-1", "ins-1", "direct_ok@x.test"))
    featured = [c["user_id"] for c in APIClient().get(reverse("handymen-featured")).json()["results"]]
    assert featured == [user.id]


def test_a_user_only_lists_their_own_profile():
    mine = artisan("own_a")
    artisan("own_b")
    c = APIClient()
    c.force_authenticate(mine)
    ids = {p["id"] for p in c.get("/handy/handymen/").json()["results"]}
    assert ids == {mine.handyman_profile.id}
