"""Aucune donnée d'un compte ne doit survivre ou fuiter vers un autre (proxy, CDN, navigateur, session)."""
import pytest
from rest_framework.test import APIClient

from handy.models import Booking, Conversation, User

pytestmark = pytest.mark.django_db


def test_personal_endpoints_are_never_cached():
    me = User.objects.create_user("nocache", "n@x.test", "pass1234")
    c = APIClient()
    c.force_authenticate(me)
    for name in ("/handy/me/dashboard/", "/handy/me/services/", "/handy/me/conversations/", "/handy/me/reviews/"):
        r = c.get(name)
        assert r.status_code == 200, name
        assert "no-store" in r["Cache-Control"] and "private" in r["Cache-Control"], name


def test_each_account_only_sees_its_own_data():
    a = User.objects.create_user("iso_a", "a@x.test", "pass1234")
    b = User.objects.create_user("iso_b", "b@x.test", "pass1234")
    h = User.objects.create_user("iso_h", "h@x.test", "pass1234", user_type="handyman")
    booking = Booking.objects.create(client=a, handyman=h, address="x", city="Abidjan",
                                     booking_date="2030-01-01T10:00:00Z")
    conv = Conversation.objects.create(booking=booking)
    conv.participants.set([a, h])
    ca, cb = APIClient(), APIClient()
    ca.force_authenticate(a)
    cb.force_authenticate(b)
    assert ca.get("/handy/me/dashboard/").json()["client"]["bookings"]["total"] == 1
    assert cb.get("/handy/me/dashboard/").json()["client"]["bookings"]["total"] == 0
    assert [c["id"] for c in ca.get("/handy/me/conversations/").json()["results"]] == [conv.id]
    assert cb.get("/handy/me/conversations/").json()["results"] == []
    assert cb.get(f"/handy/me/conversations/{conv.id}/messages/").status_code == 404
    assert cb.get(f"/handy/bookings/{booking.id}/").status_code == 404
    assert cb.get(f"/handy/bookings/?client={a.id}").json()["results"] == []  # filtrer ne contourne pas le cloisonnement
