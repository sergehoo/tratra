"""Avis : mission terminée seulement, client concerné seulement, critères, photos, réponse, anti-manipulation."""
import io
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from handy.models import Booking, Notification, Review
from handy.reviews import review_stats
from handy.test_booking_regression import _booking, _client
from handy.test_eligibility import artisan, service

User = get_user_model()
pytestmark = pytest.mark.django_db
URL = "/handy/reviews/"


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _done(client=None, art=None, status="completed", username="rv_client"):
    client = client or _client(username)
    art = art or artisan("rv_art")
    return client, art, _booking(client, art, service(art, "Plomberie"), status=status)


def _png(size=(40, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, "PNG")
    return SimpleUploadedFile("photo.png", buf.getvalue(), content_type="image/png")


# ---- Création : client concerné, mission terminée --------------------------------------------------

def test_only_the_booking_client_can_review_a_completed_mission():
    client, art, b = _done()
    other = _client("rv_other")
    staff = User.objects.create_user("rv_staff", "s@x.test", "pass1234", is_staff=True)
    payload = {"booking": b.id, "rating": 5}
    for user in (art, other, staff):  # l'artisan, un tiers et le staff n'évaluent jamais à la place du client
        assert _api(user).post(URL, payload, format="json").status_code in (403, 404), user.username
    r = _api(client).post(URL, payload, format="json")
    assert r.status_code == 201, r.content
    assert Review.objects.filter(booking=b).count() == 1


@pytest.mark.parametrize("status", ["pending", "confirmed", "in_progress", "cancelled"])
def test_unfinished_missions_cannot_be_reviewed(status):
    client, _, b = _done(status=status, username=f"rv_{status}")
    r = _api(client).post(URL, {"booking": b.id, "rating": 5}, format="json")
    assert r.status_code == 400 and "booking" in r.json()


def test_one_review_per_mission():
    client, _, b = _done()
    assert _api(client).post(URL, {"booking": b.id, "rating": 4}, format="json").status_code == 201
    again = _api(client).post(URL, {"booking": b.id, "rating": 1}, format="json")
    assert again.status_code == 400
    assert Review.objects.get(booking=b).rating == 4


@pytest.mark.parametrize("rating", [0, 6, -1, "x", None])
def test_global_rating_is_1_to_5(rating):
    client, _, b = _done(username=f"rv_r{rating}")
    r = _api(client).post(URL, {"booking": b.id, "rating": rating}, format="json")
    assert r.status_code == 400 and "rating" in r.json()


def test_criteria_are_optional_and_bounded():
    client, _, b = _done()
    bad = _api(client).post(URL, {"booking": b.id, "rating": 5, "quality": 6}, format="json")
    assert bad.status_code == 400 and "quality" in bad.json()
    r = _api(client).post(URL, {"booking": b.id, "rating": 4, "quality": 5, "punctuality": 3,
                               "comment": "  Bon travail\x07  "}, format="json")
    assert r.status_code == 201, r.content
    body = r.json()
    assert (body["quality"], body["punctuality"], body["professionalism"]) == (5, 3, None)
    assert body["comment"] == "Bon travail"


def test_comment_length_is_limited():
    client, _, b = _done()
    r = _api(client).post(URL, {"booking": b.id, "rating": 5, "comment": "x" * 1001}, format="json")
    assert r.status_code == 400 and "comment" in r.json()


# ---- Modification : fenêtre de 7 jours ---------------------------------------------------------------

def test_author_edits_within_the_window_only():
    client, _, b = _done()
    review = Review.objects.create(booking=b, rating=3)
    api = _api(client)
    url = f"{URL}{review.id}/"
    assert api.patch(url, {"rating": 4, "comment": "Mieux"}, format="json").status_code == 200
    assert api.get(url).json()["can_edit"] is True
    Review.objects.filter(pk=review.pk).update(created_at=timezone.now() - timedelta(days=8))
    assert api.patch(url, {"rating": 5}, format="json").status_code == 403
    assert api.delete(url).status_code == 403
    assert Review.objects.get(pk=review.pk).rating == 4
    assert api.get(url).json()["can_edit"] is False


def test_the_artisan_and_third_parties_cannot_edit_or_delete():
    client, art, b = _done()
    review = Review.objects.create(booking=b, rating=5)
    url = f"{URL}{review.id}/"
    assert _api(art).patch(url, {"rating": 1}, format="json").status_code == 403
    assert _api(art).delete(url).status_code == 403
    assert _api(_client("rv_third")).patch(url, {"rating": 1}, format="json").status_code == 404
    assert Review.objects.get(pk=review.pk).rating == 5


# ---- Réponse publique de l'artisan ---------------------------------------------------------------------

def test_the_artisan_replies_publicly_once_and_can_correct_it():
    client, art, b = _done()
    review = Review.objects.create(booking=b, rating=2, comment="Retard")
    url = f"{URL}{review.id}/reply/"
    assert _api(client).post(url, {"text": "Je réponds à mon propre avis"}, format="json").status_code == 403
    assert _api(_client("rv_t2")).post(url, {"text": "x"}, format="json").status_code == 404
    assert _api(art).post(url, {"text": "   "}, format="json").status_code == 400
    assert _api(art).post(url, {"text": "y" * 601}, format="json").status_code == 400
    r = _api(art).post(url, {"text": "Désolé pour le retard, un imprévu de circulation."}, format="json")
    assert r.status_code == 200 and r.json()["reply"]["text"].startswith("Désolé")
    assert Notification.objects.filter(user=client, notification_type="review_reply").count() == 1
    assert _api(art).post(url, {"text": "Corrigé : embouteillage."}, format="json").json()["reply"]["text"] == "Corrigé : embouteillage."
    assert Review.objects.get(pk=review.pk).reply_text == "Corrigé : embouteillage."
    Review.objects.filter(pk=review.pk).update(reply_at=timezone.now() - timedelta(days=8))
    assert _api(art).post(url, {"text": "Trop tard"}, format="json").status_code == 403


def test_no_reply_on_a_hidden_review():
    client, art, b = _done()
    review = Review.objects.create(booking=b, rating=1, is_hidden=True)
    assert _api(art).post(f"{URL}{review.id}/reply/", {"text": "Non"}, format="json").status_code == 403


# ---- Photos ------------------------------------------------------------------------------------------------

def test_photos_are_limited_sanitised_and_owned_by_the_author():
    client, art, b = _done()
    review = Review.objects.create(booking=b, rating=5)
    url = f"{URL}{review.id}/photos/"
    assert _api(art).post(url, {"image": _png()}, format="multipart").status_code == 403
    assert _api(client).post(url, {}, format="multipart").status_code == 400
    bad = SimpleUploadedFile("x.png", b"%PDF-1.4 not an image", content_type="image/png")
    assert _api(client).post(url, {"image": bad}, format="multipart").status_code == 400
    for _ in range(4):
        r = _api(client).post(url, {"image": _png()}, format="multipart")
        assert r.status_code == 201, r.content
    assert len(r.json()["photos"]) == 4
    assert _api(client).post(url, {"image": _png()}, format="multipart").status_code == 400
    media = review.media.first()
    r = _api(client).delete(f"{url}{media.id}/")
    assert r.status_code == 200 and len(r.json()["photos"]) == 3
    Review.objects.filter(pk=review.pk).update(created_at=timezone.now() - timedelta(days=8))
    assert _api(client).post(url, {"image": _png()}, format="multipart").status_code == 403


# ---- Statistiques réelles, un avis par client -----------------------------------------------------------

def test_stats_are_real_and_one_review_per_client_counts():
    art = artisan("rv_stat")
    svc = service(art, "S")
    assert review_stats(art.id)["average"] is None and review_stats(art.id)["count"] == 0  # aucun chiffre inventé
    c1, c2 = _client("rv_c1"), _client("rv_c2")
    old = Review.objects.create(booking=_booking(c1, art, svc, status="completed"), rating=1, quality=1)
    new = Review.objects.create(booking=_booking(c1, art, svc, status="completed"), rating=5, quality=5, punctuality=4)
    Review.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=3))
    Review.objects.create(booking=_booking(c2, art, svc, status="completed"), rating=3, reply_text="Merci")
    Review.objects.create(booking=_booking(_client("rv_c3"), art, svc, status="completed"), rating=1, is_hidden=True)
    Review.objects.create(booking=_booking(_client("rv_c4"), art, svc, status="pending"), rating=1)  # non terminée
    stats = review_stats(art.id)
    assert stats["count"] == 2                      # c1 (le plus récent) + c2 ; masqué et non terminé exclus
    assert stats["average"] == 4.0                  # (5 + 3) / 2
    assert stats["criteria"]["quality"] == {"average": 5.0, "count": 1}
    assert stats["criteria"]["punctuality"] == {"average": 4.0, "count": 1}
    assert stats["criteria"]["price"] == {"average": None, "count": 0}
    assert stats["distribution"] == {"1": 0, "2": 0, "3": 1, "4": 0, "5": 1}
    assert stats["replied"] == 1 and stats["response_rate"] == 0.5
    art.handyman_profile.refresh_from_db()
    assert art.handyman_profile.rating == 4.0       # la note du profil suit les mêmes règles


# ---- Endpoint public --------------------------------------------------------------------------------------

def test_public_reviews_endpoint_for_eligible_artisans_only():
    art = artisan("rv_pub")
    svc = service(art, "S")
    c = _client("rv_pc")
    review = Review.objects.create(booking=_booking(c, art, svc, status="completed"), rating=5, quality=5,
                                   comment="Parfait", reply_text="Merci !", reply_at=timezone.now())
    Review.objects.create(booking=_booking(_client("rv_pc2"), art, svc, status="completed"), rating=1, is_hidden=True)
    anon = APIClient()
    r = anon.get(f"/handy/handymen/{art.handyman_profile.id}/reviews/")
    assert r.status_code == 200, r.content
    body = r.json()
    assert [x["id"] for x in body["results"]] == [review.id]
    item = body["results"][0]
    assert item["criteria"] == {"quality": 5} and item["reply"]["text"] == "Merci !"
    assert item["author"].startswith("Rv_pc".title()[:2]) or item["author"]  # « Prénom N. », jamais d'e-mail
    assert "@" not in r.content.decode()
    assert body["stats"]["count"] == 1 and body["stats"]["average"] == 5.0
    hidden = artisan("rv_pub_bad", eligible=False)
    assert anon.get(f"/handy/handymen/{hidden.handyman_profile.id}/reviews/").status_code == 404


def test_dashboard_reviews_expose_reply_and_edit_rights():
    client, art, b = _done()
    review = Review.objects.create(booking=b, rating=4, quality=4)
    received = _api(art).get("/handy/me/reviews/").json()["received"][0]
    given = _api(client).get("/handy/me/reviews/").json()["given"][0]
    assert received["can_reply"] is True and received["criteria"] == {"quality": 4}
    assert given["can_edit"] is True
    review.refresh_from_db()
