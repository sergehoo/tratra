"""Parcours réel de bout en bout, avec DEUX sessions distinctes (jetons obtenus par la vraie connexion) :
réservation → acceptation → GPS → ETA → arrivée → QR → intervention → avis → badges.

Chaque participant (client, artisan, tiers, anonyme) a son propre client HTTP : aucune session n'est partagée.
Aucun OTP n'est contourné : la connexion testée est la connexion normale (identifiant + mot de passe)."""
import io
import json
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from handy.models import Booking, HandymanProfile, Notification, Review
from handy.test_booking_regression import _client
from handy.test_eligibility import artisan, service
from live.models import LivePosition, TrackingSession
from trust.models import BookingPass

User = get_user_model()
pytestmark = pytest.mark.django_db

DEST = (5.36, -4.0083)            # lieu d'intervention (adresse du client)
FAR = (5.38, -4.0083)             # ≈ 2,2 km
NEAR = (5.365, -4.0083)           # ≈ 0,55 km
ARTISAN_HOME = (5.25, -3.9)       # position enregistrée du profil artisan : ne doit JAMAIS fuiter


@pytest.fixture(autouse=True)
def _env(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    cache.clear()
    yield
    cache.clear()


def login(username, password="pass1234") -> APIClient:
    """Vraie connexion HTTP → jeton d'accès propre à ce participant."""
    r = APIClient().post("/handy/auth/login/", {"username": username, "password": password}, format="json")
    assert r.status_code == 200, r.content
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.json()['access']}")
    return c


def png(color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), color).save(buf, "PNG")
    return SimpleUploadedFile("photo.png", buf.getvalue(), content_type="image/png")


def ping(lat_lng, **extra):
    return {"lat": lat_lng[0], "lng": lat_lng[1], "accuracy": 9, "speed": 7, "heading": 180,
            "captured_at": timezone.now().isoformat(), **extra}


def _numbers(obj):
    """Toutes les valeurs numériques (ou textes numériques) d'une réponse JSON, clés et horodatages exclus."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _numbers(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _numbers(v)
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, (int, float)):
        yield float(obj)
    elif isinstance(obj, str):
        try:
            yield float(obj)
        except ValueError:
            return


def no_position_leak(responses, *needles):
    """Aucune réponse ne contient les coordonnées de l'artisan (position en direct ni position enregistrée).
    Comparaison sur les VALEURS numériques, pas sur le texte : « 5.25 » apparaît par hasard dans un horodatage."""
    values = [v for r in responses for v in _numbers(r.json() if hasattr(r, "json") else r)]
    for n in needles:
        target = float(n)
        assert not any(abs(v - target) < 1e-6 for v in values), f"fuite de position : {n}"


def test_full_journey_with_two_distinct_sessions():
    art_user = artisan("e2e_art", online=True)
    art_user.handyman_profile.location = Point(ARTISAN_HOME[1], ARTISAN_HOME[0], srid=4326)
    art_user.handyman_profile.save()
    svc = service(art_user, "Dépannage plomberie")
    cli_user = _client("e2e_cli")
    out_user = _client("e2e_out")
    profile_id = art_user.handyman_profile.pk

    client, artisan_api, outsider, anon = login("e2e_cli"), login("e2e_art"), login("e2e_out"), APIClient()
    assert client._credentials != artisan_api._credentials != outsider._credentials  # jetons distincts

    # ── 1. Découverte publique : seul le badge VERIFIE, pas de score sans activité, aucune position ──
    listing = anon.get("/handy/services/").json()["results"]
    card = next(s["artisan"] for s in listing if s["id"] == svc.id)
    assert [b["code"] for b in card["badges"]] == ["VERIFIE"] and card["trust_score"] is None
    passport = anon.get(f"/handy/handymen/{profile_id}/trust/").json()
    assert [b["code"] for b in passport["badges"]] == ["VERIFIE"] and passport["score"]["value"] is None
    no_position_leak([anon.get("/handy/services/"), anon.get("/handy/handymen/featured/"), anon.get(f"/handy/handymen/{profile_id}/trust/")],
                     "5.25", "-3.9")

    # ── 2. Réservation par le client ──
    when = (timezone.now() + timedelta(hours=1)).isoformat()
    r = client.post("/handy/bookings/", {"service": svc.id, "handyman": art_user.id, "booking_date": when, "address": "Rue des Jardins",
                                         "city": "Abidjan", "postal_code": "00225", "type": "scheduled",
                                         "lat": DEST[0], "lng": DEST[1]}, format="json")
    assert r.status_code == 201, r.content
    bid = r.json()["id"]
    live = f"/handy/bookings/{bid}/live/"
    assert Booking.objects.get(pk=bid).status == "pending"
    assert outsider.get(f"/handy/bookings/{bid}/").status_code == 404                     # tiers : réservation inexistante
    assert artisan_api.get(f"/handy/bookings/{bid}/").status_code == 200

    # ── 3. Acceptation : seul l'artisan confirme ──
    assert client.post(f"/handy/bookings/{bid}/transition/", {"status": "confirmed"}, format="json").status_code == 403
    assert outsider.post(f"/handy/bookings/{bid}/transition/", {"status": "confirmed"}, format="json").status_code == 404
    assert artisan_api.post(f"/handy/bookings/{bid}/transition/", {"status": "confirmed"}, format="json").status_code == 200
    assert Booking.objects.get(pk=bid).status == "confirmed"

    # ── 4. GPS : rien n'est localisé tant que l'artisan n'est pas « en route » ──
    before = client.get(live).json()
    assert before["phase"] == "confirmed" and before["artisan"]["position"] is None and before["route"] is None
    assert artisan_api.post(f"{live}position/", ping(FAR), format="json").status_code == 409
    assert client.post(f"{live}position/", ping(DEST), format="json").status_code == 409   # pas de consentement client
    assert artisan_api.post(f"{live}en-route/", {}, format="json").json()["code"] == "consent_required"
    assert client.post(f"{live}en-route/", {"consent": True}, format="json").status_code == 403

    en_route = artisan_api.post(f"{live}en-route/", {"consent": True}, format="json")
    assert en_route.status_code == 200 and en_route.json()["phase"] == "en_route"
    assert Notification.objects.filter(user=cli_user, notification_type="live_en_route").count() == 1

    # ── 5. GPS + ETA réels (calculés depuis les positions reçues) ──
    assert artisan_api.post(f"{live}position/", ping(FAR), format="json").status_code == 201
    far_view = client.get(live).json()
    assert far_view["artisan"]["position"]["lat"] == pytest.approx(FAR[0]) and far_view["artisan"]["position"]["stale"] is False
    eta_far = far_view["route"]
    assert eta_far["source"] == "estimate" and 2000 < eta_far["distance_m"] < 2400 and eta_far["eta_minutes"] >= 1
    cache.clear()
    assert artisan_api.post(f"{live}position/", ping(NEAR), format="json").status_code == 201
    near_route = client.get(live).json()["route"]
    assert near_route["distance_m"] < eta_far["distance_m"] and near_route["eta_seconds"] < eta_far["eta_seconds"]   # il se rapproche
    # le tiers et l'anonyme ne voient rien ; le client ne voit jamais la position enregistrée du profil
    assert outsider.get(live).status_code == 404 and anon.get(live).status_code == 401
    no_position_leak([client.get(f"/handy/bookings/{bid}/"), client.get("/handy/me/dashboard/"), client.get("/handy/bookings/"),
                      client.get("/handy/users/me/"), outsider.get("/handy/services/"), client.get("/handy/handymen/featured/")],
                     "5.25", "-3.9", "5.365", "5.38")

    # ── 6. Arrivée : tous les partages s'arrêtent ──
    cache.clear()
    assert artisan_api.post(f"{live}arrived/").status_code == 200
    arrived = client.get(live).json()
    assert arrived["phase"] == "arrived" and arrived["artisan"]["position"] is None and arrived["route"] is None
    assert arrived["consent"] == {"artisan": False, "client": False}
    for who in (artisan_api, client):
        assert who.post(f"{live}position/", ping(NEAR), format="json").status_code == 409
    assert Notification.objects.filter(user=cli_user, notification_type="live_arrived").count() == 1
    session = TrackingSession.objects.get(booking_id=bid)
    assert session.arrival_distance_m is not None and session.arrival_distance_m < 700

    # ── 7. QR de mission : émis par l'artisan, scanné par le client, usage unique ──
    pass_a = artisan_api.post(f"/handy/bookings/{bid}/identity-pass/")
    assert pass_a.status_code == 201
    token_a = pass_a.json()["token"]
    assert client.post(f"/handy/bookings/{bid}/identity-pass/").status_code == 403         # le client n'émet pas de QR
    assert outsider.post("/handy/verify/pass/", {"token": token_a}, format="json").status_code == 404
    assert artisan_api.post("/handy/verify/pass/", {"token": token_a}, format="json").status_code == 404
    ok = client.post("/handy/verify/pass/", {"token": token_a}, format="json")
    assert ok.status_code == 200 and ok.json()["matches_booking"] is True and ok.json()["booking_id"] == bid
    assert "email" not in json.dumps(ok.json()).lower()
    assert client.post("/handy/verify/pass/", {"token": token_a}, format="json").json()["code"] == "used"       # réutilisé
    pass_b = artisan_api.post(f"/handy/bookings/{bid}/identity-pass/").json()["token"]
    pass_c = artisan_api.post(f"/handy/bookings/{bid}/identity-pass/").json()["token"]
    assert client.post("/handy/verify/pass/", {"token": pass_b}, format="json").json()["code"] == "replaced"    # remplacé
    BookingPass.objects.filter(booking_id=bid, revoked_at__isnull=True, used_at__isnull=True).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert client.post("/handy/verify/pass/", {"token": pass_c}, format="json").json()["code"] == "expired"     # expiré
    pass_d = artisan_api.post(f"/handy/bookings/{bid}/identity-pass/").json()["token"]
    art_user.is_active = False
    art_user.save()
    assert client.post("/handy/verify/pass/", {"token": pass_d}, format="json").json()["code"] == "revoked"     # identité révoquée
    assert anon.get(f"/handy/verify/id/{artisan_api.get('/handy/me/tratra-id/').json()['tratra_id'] if False else 'TR-ZZZZ-ZZZZ'}/").status_code == 404
    art_user.is_active = True
    art_user.save()
    assert client.get(f"/handy/bookings/{bid}/identity/").json()["verified"] is True

    # ── 8. Intervention : démarrer / terminer = artisan uniquement ──
    assert client.post(f"/handy/bookings/{bid}/transition/", {"status": "in_progress"}, format="json").status_code == 403
    assert artisan_api.post(f"/handy/bookings/{bid}/transition/", {"status": "in_progress"}, format="json").status_code == 200
    assert client.post(f"/handy/bookings/{bid}/transition/", {"status": "completed"}, format="json").status_code == 403
    assert artisan_api.post(f"/handy/bookings/{bid}/transition/", {"status": "completed"}, format="json").status_code == 200
    done = client.get(live).json()
    assert done["phase"] == "completed" and done["artisan"]["position"] is None and done["client"]["position"] is None
    assert HandymanProfile.objects.get(pk=profile_id).completed_jobs == 1

    # ── 9. Avis : note, critères, commentaire, photo — puis réponse publique de l'artisan ──
    assert outsider.post("/handy/reviews/", {"booking": bid, "rating": 5}, format="json").status_code in (403, 404)
    assert artisan_api.post("/handy/reviews/", {"booking": bid, "rating": 5}, format="json").status_code in (403, 404)
    rv = client.post("/handy/reviews/", {"booking": bid, "rating": 5, "quality": 5, "punctuality": 5, "professionalism": 4,
                                         "communication": 5, "price": 4, "comment": "Arrivé à l'heure, travail propre."}, format="json")
    assert rv.status_code == 201, rv.content
    rid = rv.json()["id"]
    assert client.post("/handy/reviews/", {"booking": bid, "rating": 1}, format="json").status_code == 400      # un avis par mission
    assert client.post(f"/handy/reviews/{rid}/photos/", {"image": png()}, format="multipart").status_code == 201
    assert artisan_api.post(f"/handy/reviews/{rid}/photos/", {"image": png()}, format="multipart").status_code == 403
    assert outsider.post(f"/handy/reviews/{rid}/reply/", {"text": "Merci"}, format="json").status_code in (403, 404)
    assert client.post(f"/handy/reviews/{rid}/reply/", {"text": "Je réponds à mon propre avis"}, format="json").status_code in (403, 404)
    rep = artisan_api.post(f"/handy/reviews/{rid}/reply/", {"text": "Merci pour votre confiance !"}, format="json")
    assert rep.status_code == 200 and rep.json()["reply"]["text"] == "Merci pour votre confiance !"
    mine = client.get("/handy/me/reviews/").json()
    given = next(x for x in mine["given"] if x["id"] == rid)
    assert given["reply"]["text"] and len(given["photos"]) == 1 and given["criteria"]["price"] == 4
    # les photos sont servies en URL ABSOLUE (une URL relative serait résolue contre le site web, donc introuvable)
    assert given["photos"][0].startswith("http") and "/media/" in given["photos"][0]
    assert artisan_api.get("/handy/me/reviews/").json()["received"][0]["photos"][0].startswith("http")
    received = next(x for x in artisan_api.get("/handy/me/reviews/").json()["received"] if x["id"] == rid)
    assert received["can_reply"] is True and received["author"] == "Awa" or received["author"]
    public = anon.get(f"/handy/handymen/{profile_id}/reviews/").json()
    row = public["results"][0]
    assert row["comment"].startswith("Arrivé") and row["reply"]["text"] and len(row["photos"]) == 1 and row["author"]
    assert public["stats"]["count"] == 1 and public["stats"]["average"] == 5.0
    assert public["stats"]["criteria"]["quality"]["average"] == 5.0

    # ── 10. Badges : VERIFIE seulement (un avis ne suffit pas à publier un score), ponctualité mesurée sans « 0 % » ──
    after = anon.get(f"/handy/handymen/{profile_id}/trust/").json()
    assert [b["code"] for b in after["badges"]] == ["VERIFIE"]
    assert after["satisfaction"]["count"] == 1 and after["score"]["value"] is None
    assert after["punctuality"]["rate"] is None and after["punctuality"]["sample"] == 1   # échantillon insuffisant : non publié
    # l'historique de positions existe en base mais aucune API ne le sert hors mission
    assert LivePosition.objects.filter(session__booking_id=bid).count() == 2
    final = [client.get(live), artisan_api.get(live), anon.get(f"/handy/handymen/{profile_id}/trust/"), anon.get(f"/handy/handymen/{profile_id}/reviews/"),
             client.get("/handy/me/reviews/"), client.get(f"/handy/bookings/{bid}/")]
    no_position_leak(final, "5.25", "-3.9", "5.365", "5.38")


def test_badges_are_cumulative_and_unverified_profiles_show_nouveau():
    from trust.test_trust import certify, missions
    pro = artisan("e2e_pro", online=True)
    certify(pro)
    missions(pro, 16)
    api_pro, anon = login("e2e_pro"), APIClient()
    assert [b["code"] for b in api_pro.get("/handy/me/trust/").json()["badges"]] == ["VERIFIE", "EXPERT", "SUR"]
    public = anon.get(f"/handy/handymen/{pro.handyman_profile.pk}/trust/").json()
    assert [b["code"] for b in public["badges"]] == ["VERIFIE", "EXPERT", "SUR"] and public["score"]["value"] >= 80
    assert [b["code"] for b in anon.get("/handy/services/", {"badge": "SUR"}).json()["results"][0]["artisan"]["badges"]] == ["VERIFIE", "EXPERT", "SUR"] \
        if service(pro, "S") else True

    fresh = artisan("e2e_fresh", eligible=False)
    mine = login("e2e_fresh").get("/handy/me/trust/").json()
    assert [b["code"] for b in mine["badges"]] == ["NOUVEAU"] and mine["identity"]["verified"] is False and mine["score"]["value"] is None
    assert anon.get(f"/handy/handymen/{fresh.handyman_profile.pk}/trust/").status_code == 404          # non publié
    assert all("NOUVEAU" not in [b["code"] for b in s["artisan"]["badges"]] for s in anon.get("/handy/services/").json()["results"])
    # le tableau de bord de l'artisan non vérifié expose lui aussi son badge NOUVEAU
    dash = login("e2e_fresh").get("/handy/me/dashboard/").json()
    assert [b["code"] for b in dash["provider"]["badges"]] == ["NOUVEAU"]


def test_two_sessions_never_share_identity_or_rights():
    art_user, cli_user = artisan("e2e_art2"), _client("e2e_cli2")
    artisan_api, client = login("e2e_art2"), login("e2e_cli2")
    assert client.get("/handy/users/me/").json()["username"] == "e2e_cli2"
    assert artisan_api.get("/handy/users/me/").json()["username"] == "e2e_art2"
    assert client.get("/handy/me/trust/").status_code == 404            # le client n'a pas de profil artisan
    assert client.get("/handy/me/tratra-id/").status_code == 404
    assert artisan_api.get("/handy/me/trust/").status_code == 200
    # un jeton falsifié ou expiré est refusé, sans retomber sur une autre session
    forged = APIClient()
    forged.credentials(HTTP_AUTHORIZATION="Bearer " + "x" * 40)
    assert forged.get("/handy/me/dashboard/").status_code == 401
    b = Booking.objects.create(client=cli_user, handyman=art_user, service=service(art_user, "S"), status="confirmed", address="x", city="x",
                               booking_date=timezone.now() + timedelta(hours=1))
    assert client.post(f"/handy/bookings/{b.id}/live/en-route/", {"consent": True}, format="json").status_code == 403
    assert artisan_api.post(f"/handy/bookings/{b.id}/identity-pass/").status_code == 201
    assert artisan_api.post("/handy/reviews/", {"booking": b.id, "rating": 5}, format="json").status_code in (400, 403, 404)


def test_leak_check_flags_real_coordinates_but_not_lookalike_timestamps():
    """Le contrôle de fuite doit rester fiable : faux positif sur « …05.259Z » = test instable (constaté)."""
    harmless = [{"created": "2026-10-10T11:45:05.259379Z", "lat": 5.36, "lng": -4.0083}]
    no_position_leak(harmless, "5.25", "-3.9")
    for leaked in ({"position": {"lat": 5.25}}, {"nested": [{"home": "5.250000"}]}, {"lng": -3.9}):
        with pytest.raises(AssertionError):
            no_position_leak([leaked], "5.25", "-3.9")
