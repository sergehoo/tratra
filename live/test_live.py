"""Tratra Live : suivi GPS consenti, limité à la mission, contrôlé côté serveur, temps réel et purge."""
import json
from datetime import timedelta
from urllib.parse import quote

import pytest
from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.urls import re_path
from django.utils import timezone
from rest_framework.test import APIClient

from handy.models import Booking, JobTracking, Notification
from handy.test_booking_regression import _client
from handy.test_eligibility import artisan, service
from live import realtime, routing, tasks
from live.consumers import LiveConsumer
from live.models import LivePosition, TrackingSession
from trust.models import AuditEvent

User = get_user_model()
pytestmark = pytest.mark.django_db

ABIDJAN = (5.3600, -4.0083)       # lat, lng — lieu d'intervention
NEARBY = (5.3700, -4.0083)        # ≈ 1,1 km


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


def api(user=None):
    c = APIClient()
    if user:
        c.force_authenticate(user)
    return c


def mission(art, client, *, status="confirmed", in_hours=1, with_location=True):
    b = Booking.objects.create(client=client, handyman=art, service=service(art, f"Dépannage {Booking.objects.count()}"),
                               status=status, address="Rue 1", city="Abidjan",
                               booking_date=timezone.now() + timedelta(hours=in_hours))
    if with_location:
        Booking.objects.filter(pk=b.pk).update(job_location=Point(ABIDJAN[1], ABIDJAN[0], srid=4326))
        b.refresh_from_db()
    return b


def url(b, action=""):
    return f"/handy/bookings/{b.id}/live/{action}"


def ping(lat_lng, **extra):
    return {"lat": lat_lng[0], "lng": lat_lng[1], "accuracy": 8, "speed": 6.5, "heading": 90,
            "captured_at": timezone.now().isoformat(), **extra}


def en_route(art, b):
    r = api(art).post(url(b, "en-route/"), {"consent": True}, format="json")
    assert r.status_code == 200, r.content
    return r.json()


# ---- Accès : uniquement les participants -----------------------------------------------------------------

@pytest.mark.parametrize("action,method", [("", "get"), ("consent/", "post"), ("en-route/", "post"),
                                           ("arrived/", "post"), ("position/", "post"), ("ticket/", "post")])
def test_strangers_and_anonymous_get_nothing(action, method):
    art, cli, out = artisan("lv_art"), _client("lv_cli"), _client("lv_out")
    b = mission(art, cli)
    assert getattr(api(), method)(url(b, action)).status_code == 401
    r = getattr(api(out), method)(url(b, action), {"share": True, "consent": True, "lat": 5, "lng": -4}, format="json")
    assert r.status_code == 404 and r.json()["code"] == "not_found"
    assert not TrackingSession.objects.exists() and not LivePosition.objects.exists()


def test_each_participant_sees_the_role_specific_state():
    art, cli = artisan("lv_art2"), _client("lv_cli2")
    b = mission(art, cli)
    a, c = api(art).get(url(b)).json(), api(cli).get(url(b)).json()
    assert a["role"] == "artisan" and c["role"] == "client" and a["phase"] == c["phase"] == "confirmed"
    assert a["can"]["start_route"] is True and c["can"]["start_route"] is False
    assert c["artisan"]["position"] is None and a["client"]["position"] is None


# ---- « Je suis en route » ---------------------------------------------------------------------------------

def test_en_route_needs_explicit_consent_the_artisan_and_a_confirmed_mission():
    art, cli = artisan("lv_art3"), _client("lv_cli3")
    b = mission(art, cli)
    assert api(art).post(url(b, "en-route/"), {}, format="json").json()["code"] == "consent_required"
    assert api(art).post(url(b, "en-route/"), {"consent": "oui"}, format="json").status_code == 400
    assert api(cli).post(url(b, "en-route/"), {"consent": True}, format="json").status_code == 403
    pending = mission(art, cli, status="pending")
    assert api(art).post(url(pending, "en-route/"), {"consent": True}, format="json").json()["code"] == "booking_not_confirmed"
    far = mission(art, cli, in_hours=48)
    assert api(art).post(url(far, "en-route/"), {"consent": True}, format="json").json()["code"] == "outside_window"
    assert not TrackingSession.objects.filter(en_route_at__isnull=False).exists()


def test_en_route_starts_sharing_notifies_the_client_and_is_audited():
    art, cli = artisan("lv_art4"), _client("lv_cli4")
    cli.first_name = "Awa"
    art.first_name = "Moussa"
    art.save()
    b = mission(art, cli)
    state = en_route(art, b)
    assert state["phase"] == "en_route" and state["consent"]["artisan"] is True
    assert Notification.objects.filter(user=cli, notification_type="live_en_route").count() == 1
    assert "Moussa est en route" in Notification.objects.get(user=cli, notification_type="live_en_route").message
    assert AuditEvent.objects.filter(action="live.en_route").exists()
    en_route(art, b)  # idempotent : pas de seconde notification
    assert Notification.objects.filter(user=cli, notification_type="live_en_route").count() == 1


def test_an_unverified_artisan_cannot_start_the_route():
    art, cli = artisan("lv_art5"), _client("lv_cli5")
    b = mission(art, cli)
    art.is_active = False
    art.save()
    r = api(art).post(url(b, "en-route/"), {"consent": True}, format="json")
    assert r.status_code in (401, 403, 409, 404) or r.json().get("code") == "not_verified"


# ---- Positions ---------------------------------------------------------------------------------------------

def test_no_position_is_accepted_before_the_route_starts_or_without_consent():
    art, cli = artisan("lv_art6"), _client("lv_cli6")
    b = mission(art, cli)
    r = api(art).post(url(b, "position/"), ping(NEARBY), format="json")
    assert r.status_code == 409 and r.json()["code"] == "tracking_not_active"
    r = api(cli).post(url(b, "position/"), ping(NEARBY), format="json")
    assert r.status_code == 409 and r.json()["code"] == "tracking_not_active"
    assert not LivePosition.objects.exists()


def test_artisan_positions_reach_the_client_with_a_real_distance_and_eta():
    art, cli = artisan("lv_art7"), _client("lv_cli7")
    b = mission(art, cli)
    en_route(art, b)
    r = api(art).post(url(b, "position/"), ping(NEARBY), format="json")
    assert r.status_code == 201, r.content
    mine = r.json()
    assert mine["artisan"]["position"]["lat"] == pytest.approx(NEARBY[0])
    seen = api(cli).get(url(b)).json()
    pos = seen["artisan"]["position"]
    assert pos["lat"] == pytest.approx(NEARBY[0]) and pos["stale"] is False and pos["age_seconds"] <= 5
    assert seen["destination"]["source"] == "booking"
    route = seen["route"]
    assert route["source"] == "estimate" and 1000 < route["distance_m"] < 1300  # ≈ 1,1 km mesurés, pas inventés
    assert route["eta_minutes"] >= 1 and route["polyline"][0] == [NEARBY[0], NEARBY[1]]
    assert seen["client"]["position"] is None  # le client n'a rien partagé


def test_a_real_routing_service_replaces_the_estimate(monkeypatch):
    art, cli = artisan("lv_art8"), _client("lv_cli8")
    b = mission(art, cli)
    en_route(art, b)
    monkeypatch.setattr(routing, "osrm_route", lambda o, d: {
        "eta_seconds": 540, "distance_m": 2400, "polyline": [[5.37, -4.0083], [5.365, -4.005], [5.36, -4.0083]], "source": "osrm"})
    api(art).post(url(b, "position/"), ping(NEARBY), format="json")
    route = api(cli).get(url(b)).json()["route"]
    assert route["source"] == "osrm" and route["eta_minutes"] == 9 and route["distance_m"] == 2400
    assert len(route["polyline"]) == 3


def test_routing_failure_falls_back_to_an_honest_estimate(monkeypatch):
    art, cli = artisan("lv_art9"), _client("lv_cli9")
    b = mission(art, cli)
    en_route(art, b)
    monkeypatch.setattr(routing, "osrm_route", lambda o, d: None)
    api(art).post(url(b, "position/"), ping(NEARBY), format="json")
    assert api(cli).get(url(b)).json()["route"]["source"] == "estimate"


def test_without_a_known_destination_there_is_no_eta():
    art, cli = artisan("lv_art10"), _client("lv_cli10")
    b = mission(art, cli, with_location=False)
    en_route(art, b)
    api(art).post(url(b, "position/"), ping(NEARBY), format="json")
    seen = api(cli).get(url(b)).json()
    assert seen["destination"] is None and seen["route"] is None


def test_client_position_is_opt_in_revocable_and_used_as_destination():
    art, cli = artisan("lv_art11"), _client("lv_cli11")
    b = mission(art, cli, with_location=False)
    en_route(art, b)
    assert api(cli).post(url(b, "position/"), ping(ABIDJAN), format="json").status_code == 409  # pas de consentement
    assert api(art).get(url(b)).json()["client"]["position"] is None
    assert api(cli).post(url(b, "consent/"), {"share": True}, format="json").status_code == 200
    assert api(cli).post(url(b, "position/"), ping(ABIDJAN), format="json").status_code == 201
    seen_by_artisan = api(art).get(url(b)).json()
    assert seen_by_artisan["client"]["position"]["lat"] == pytest.approx(ABIDJAN[0])
    assert seen_by_artisan["destination"]["source"] == "client_position"
    api(art).post(url(b, "position/"), ping(NEARBY), format="json")
    assert api(cli).get(url(b)).json()["route"]["distance_m"] > 1000
    # retrait du consentement : arrêt immédiat ET effacement des positions du client
    r = api(cli).post(url(b, "consent/"), {"share": False}, format="json")
    assert r.json()["client"]["position"] is None
    assert not LivePosition.objects.filter(role="client").exists()
    assert api(cli).post(url(b, "position/"), ping(ABIDJAN), format="json").status_code == 409
    assert api(art).get(url(b)).json()["client"]["position"] is None


def test_the_artisan_can_stop_sharing_and_resume_while_en_route():
    art, cli = artisan("lv_art12"), _client("lv_cli12")
    b = mission(art, cli)
    en_route(art, b)
    api(art).post(url(b, "position/"), ping(NEARBY), format="json")
    api(art).post(url(b, "consent/"), {"share": False}, format="json")
    assert not LivePosition.objects.filter(role="artisan").exists()
    seen = api(cli).get(url(b)).json()
    assert seen["artisan"]["position"] is None and seen["route"] is None and seen["phase"] == "en_route"
    assert api(art).post(url(b, "position/"), ping(NEARBY), format="json").status_code == 409
    assert api(art).post(url(b, "consent/"), {"share": True}, format="json").status_code == 200
    cache.clear()
    assert api(art).post(url(b, "position/"), ping(NEARBY), format="json").status_code == 201


@pytest.mark.parametrize("payload,code", [
    ({"lat": 95, "lng": 0}, "invalid_position"), ({"lat": 5, "lng": 181}, "invalid_position"),
    ({"lat": "abc", "lng": 0}, "invalid_position"),
    ({"lng": 0}, "invalid_position"),
    ({"lat": 5, "lng": -4, "speed": -3}, "invalid_position"), ({"lat": 5, "lng": -4, "heading": 400}, "invalid_position"),
])
def test_invalid_positions_are_refused(payload, code):
    art, cli = artisan("lv_art13"), _client("lv_cli13")
    b = mission(art, cli)
    en_route(art, b)
    r = api(art).post(url(b, "position/"), payload, format="json")
    assert r.status_code == 400 and r.json()["code"] == code
    assert not LivePosition.objects.exists()


def test_nan_coordinates_are_refused():
    art, cli = artisan("lv_art13n"), _client("lv_cli13n")
    b = mission(art, cli)
    en_route(art, b)
    r = api(art).post(url(b, "position/"), data='{"lat": NaN, "lng": 0}', content_type="application/json")
    assert r.status_code == 400  # refusé dès l'analyse du JSON (NaN n'est pas une valeur JSON valide)
    assert not LivePosition.objects.exists()


def test_stale_future_and_too_frequent_positions_are_refused():
    art, cli = artisan("lv_art14"), _client("lv_cli14")
    b = mission(art, cli)
    en_route(art, b)
    old = ping(NEARBY, captured_at=(timezone.now() - timedelta(minutes=10)).isoformat())
    assert api(art).post(url(b, "position/"), old, format="json").json()["code"] == "stale_position"
    future = ping(NEARBY, captured_at=(timezone.now() + timedelta(minutes=10)).isoformat())
    assert api(art).post(url(b, "position/"), future, format="json").json()["code"] == "invalid_position"
    assert api(art).post(url(b, "position/"), ping(NEARBY), format="json").status_code == 201
    r = api(art).post(url(b, "position/"), ping(NEARBY), format="json")
    assert r.status_code == 429 and r.json()["code"] == "too_frequent"
    assert LivePosition.objects.count() == 1


def test_an_old_position_is_flagged_stale_never_presented_as_live():
    art, cli = artisan("lv_art15"), _client("lv_cli15")
    b = mission(art, cli)
    en_route(art, b)
    api(art).post(url(b, "position/"), ping(NEARBY), format="json")
    LivePosition.objects.update(captured_at=timezone.now() - timedelta(seconds=200))
    pos = api(cli).get(url(b)).json()["artisan"]["position"]
    assert pos["stale"] is True and pos["age_seconds"] >= 199


# ---- Arrivée, fin de mission ------------------------------------------------------------------------------

def test_arrival_stops_all_sharing_and_records_the_distance():
    art, cli = artisan("lv_art16"), _client("lv_cli16")
    b = mission(art, cli)
    en_route(art, b)
    api(cli).post(url(b, "consent/"), {"share": True}, format="json")
    api(art).post(url(b, "position/"), ping(ABIDJAN), format="json")
    assert api(art).post(url(b, "arrived/")).status_code == 200
    s = TrackingSession.objects.get(booking=b)
    assert s.arrived_at and s.arrival_distance_m is not None and s.arrival_distance_m < 50
    assert not s.artisan_sharing and not s.client_sharing
    seen = api(cli).get(url(b)).json()
    assert seen["phase"] == "arrived" and seen["artisan"]["position"] is None and seen["route"] is None
    assert Notification.objects.filter(user=cli, notification_type="live_arrived").count() == 1
    api(art).post(url(b, "arrived/"))  # idempotent
    assert Notification.objects.filter(user=cli, notification_type="live_arrived").count() == 1
    cache.clear()
    for who in (art, cli):  # plus aucune position acceptée après l'arrivée
        assert api(who).post(url(b, "position/"), ping(ABIDJAN), format="json").status_code == 409


def test_only_the_artisan_can_declare_the_arrival():
    art, cli = artisan("lv_art17"), _client("lv_cli17")
    b = mission(art, cli)
    assert api(cli).post(url(b, "arrived/")).status_code == 403
    assert not TrackingSession.objects.filter(arrived_at__isnull=False).exists()


@pytest.mark.parametrize("final", ["completed", "cancelled"])
def test_completed_or_cancelled_missions_stop_everything(final):
    art, cli = artisan(f"lv_art18_{final}"), _client(f"lv_cli18_{final}")
    b = mission(art, cli)
    en_route(art, b)
    api(cli).post(url(b, "consent/"), {"share": True}, format="json")
    api(art).post(url(b, "position/"), ping(NEARBY), format="json")
    Booking.objects.get(pk=b.pk)
    b2 = Booking.objects.get(pk=b.pk)
    if final == "completed":
        b2.status = "in_progress"
        b2.save()
        b2.transition_to("completed")
    else:
        b2.transition_to("cancelled")
    s = TrackingSession.objects.get(booking=b)
    assert not s.artisan_sharing and not s.client_sharing
    seen = api(cli).get(url(b)).json()
    assert seen["phase"] == final and seen["artisan"]["position"] is None and seen["client"]["position"] is None
    cache.clear()
    assert api(art).post(url(b, "position/"), ping(NEARBY), format="json").status_code == 409


def test_the_state_machine_is_enforced_server_side_and_the_legacy_route_is_gone():
    art, cli = artisan("lv_art19"), _client("lv_cli19")
    b = mission(art, cli, status="pending")
    # le client ne peut ni confirmer, ni démarrer, ni terminer : seulement annuler
    for target in ("confirmed", "in_progress", "completed"):
        assert api(cli).post(f"/handy/bookings/{b.id}/transition/", {"status": target}, format="json").status_code == 403
    assert api(art).post(f"/handy/bookings/{b.id}/transition/", {"status": "confirmed"}, format="json").status_code == 200
    assert api(cli).post(f"/handy/bookings/{b.id}/track/", {"lat": 5, "lng": -4}, format="json").status_code == 410
    assert api(art).post(f"/handy/bookings/{b.id}/track/", {"lat": 5, "lng": -4}, format="json").status_code == 410
    assert not JobTracking.objects.exists()
    assert api(cli).post(f"/handy/bookings/{b.id}/transition/", {"status": "cancelled"}, format="json").status_code == 200


# ---- Données, purge ----------------------------------------------------------------------------------------

def test_history_is_minimal_and_expired_positions_are_purged():
    art, cli = artisan("lv_art20"), _client("lv_cli20")
    done, active = mission(art, cli, status="confirmed"), mission(art, cli)
    for b in (done, active):
        en_route(art, b)
        api(art).post(url(b, "position/"), ping(NEARBY), format="json")
        cache.clear()
    assert LivePosition.objects.count() == 2
    assert tasks.purge() == 0  # tout est récent : rien à supprimer
    Booking.objects.filter(pk=done.pk).update(status="completed", updated_at=timezone.now() - timedelta(hours=25))
    assert tasks.purge() == 1
    assert LivePosition.objects.filter(session__booking=active).count() == 1
    LivePosition.objects.update(received_at=timezone.now() - timedelta(hours=7))
    assert tasks.purge() == 1 and not LivePosition.objects.exists()


def test_job_coordinates_are_optional_on_booking_creation():
    art, cli = artisan("lv_art21"), _client("lv_cli21")
    svc = service(art, "Dépannage")
    base = {"service": svc.id, "handyman": art.id, "booking_date": (timezone.now() + timedelta(days=1)).isoformat(),
            "address": "Rue 1", "city": "Abidjan", "postal_code": "00225"}
    r = api(cli).post("/handy/bookings/", {**base, "lat": 5.36, "lng": -4.0083}, format="json")
    assert r.status_code == 201, r.content
    assert Booking.objects.get(pk=r.json()["id"]).job_location.y == pytest.approx(5.36)
    r = api(cli).post("/handy/bookings/", base, format="json")
    assert r.status_code == 201 and Booking.objects.get(pk=r.json()["id"]).job_location is None
    assert api(cli).post("/handy/bookings/", {**base, "lat": 91, "lng": 0}, format="json").status_code == 400


# ---- Intégration confiance : ponctualité mesurée sur l'arrivée réelle ------------------------------------------

def test_punctuality_uses_the_real_arrival_but_ignores_a_far_away_claim():
    from trust import metrics
    from trust.models import TrustConfig
    art, cli = artisan("lv_art22"), _client("lv_cli22")
    cfg = TrustConfig.get_solo()
    planned = timezone.now() - timedelta(days=2)
    ok = Booking.objects.create(client=cli, handyman=art, status="completed", address="x", city="x", booking_date=planned)
    late = Booking.objects.create(client=cli, handyman=art, status="completed", address="x", city="x", booking_date=planned)
    for b, arrived, dist in ((ok, planned + timedelta(minutes=5), 40), (late, planned + timedelta(minutes=5), 3000)):
        TrackingSession.objects.create(booking=b, arrived_at=arrived, arrival_distance_m=dist)
    from handy.models import BookingTimeline
    t = BookingTimeline.objects.create(booking=late, status="in_progress")
    BookingTimeline.objects.filter(pk=t.pk).update(at=planned + timedelta(minutes=50))  # démarrage réel tardif
    result = metrics.punctuality(art.handyman_profile, cfg)
    assert result["sample"] == 2 and result["on_time"] == 1  # l'arrivée déclarée à 3 km est ignorée → en retard


# ---- Temps réel (WebSocket) --------------------------------------------------------------------------------

def _app():
    return URLRouter([re_path(r"ws/live/(?P<booking_id>\d+)/$", LiveConsumer.as_asgi())])


async def _connect(path):
    comm = WebsocketCommunicator(_app(), path)
    connected, code = await comm.connect()
    return comm, connected, code


@pytest.mark.django_db(transaction=True)
def test_websocket_requires_a_valid_participant_ticket_and_streams_each_viewers_own_state():
    art, cli, out = artisan("lv_ws_art"), _client("lv_ws_cli"), _client("lv_ws_out")
    b = mission(art, cli)

    async def scenario():
        # sans billet, billet falsifié, billet d'un autre utilisateur, billet d'une autre mission : refusés
        bad = [f"/ws/live/{b.id}/", f"/ws/live/{b.id}/?ticket=nimportequoi",
               f"/ws/live/{b.id}/?ticket={realtime.make_ticket(out.id, b.id)}",
               f"/ws/live/{b.id}/?ticket={realtime.make_ticket(cli.id, b.id + 1)}"]
        for path in bad:
            comm, connected, _ = await _connect(path)
            assert connected is False, path
        # le navigateur encode le billet (« : » devient %3A) : il doit être décodé côté serveur
        art_comm, ok1, _ = await _connect(f"/ws/live/{b.id}/?ticket={quote(realtime.make_ticket(art.id, b.id), safe='')}")
        cli_comm, ok2, _ = await _connect(f"/ws/live/{b.id}/?ticket={quote(realtime.make_ticket(cli.id, b.id), safe='')}")
        assert ok1 and ok2
        first_art, first_cli = await art_comm.receive_json_from(), await cli_comm.receive_json_from()
        assert first_art["state"]["role"] == "artisan" and first_cli["state"]["role"] == "client"
        # le flux est en lecture seule : un message du client n'a aucun effet
        await cli_comm.send_json_to({"type": "position", "lat": 1, "lng": 1})
        assert await database_sync_to_async(LivePosition.objects.count)() == 0

        # Une action métier diffuse à CHAQUE participant son propre état
        await database_sync_to_async(lambda: api(art).post(url(b, "en-route/"), {"consent": True}, format="json"))()
        got_art, got_cli = await art_comm.receive_json_from(), await cli_comm.receive_json_from()
        assert got_art["state"]["phase"] == got_cli["state"]["phase"] == "en_route"
        assert got_art["state"]["role"] == "artisan" and got_cli["state"]["role"] == "client"
        await art_comm.disconnect()
        await cli_comm.disconnect()

    async_to_sync(scenario)()


def test_ticket_endpoint_is_for_participants_and_short_lived():
    art, cli, out = artisan("lv_tk_art"), _client("lv_tk_cli"), _client("lv_tk_out")
    b = mission(art, cli)
    assert api(out).post(url(b, "ticket/")).status_code == 404
    t = api(cli).post(url(b, "ticket/")).json()
    assert t["path"] == f"/ws/live/{b.id}/" and t["expires_in"] == 60
    assert realtime.read_ticket(t["ticket"]) == (cli.id, b.id)
    assert realtime.read_ticket(t["ticket"] + "x") is None


@pytest.mark.django_db(transaction=True)
def test_websocket_pushes_never_carry_a_position_outside_the_authorized_phase():
    """Flux temps réel d'un client : position pendant le trajet, plus aucune coordonnée après l'arrivée ou la clôture."""
    art, cli = artisan("lv_wsl_art"), _client("lv_wsl_cli")
    b = mission(art, cli)

    def coords(state):
        return json.dumps(state)

    async def scenario():
        comm, ok, _ = await _connect(f"/ws/live/{b.id}/?ticket={quote(realtime.make_ticket(cli.id, b.id), safe='')}")
        assert ok
        first = (await comm.receive_json_from())["state"]
        assert first["artisan"]["position"] is None and first["route"] is None            # rien avant « en route »
        await database_sync_to_async(lambda: api(art).post(url(b, "en-route/"), {"consent": True}, format="json"))()
        await comm.receive_json_from()
        await database_sync_to_async(lambda: api(art).post(url(b, "position/"), ping(NEARBY), format="json"))()
        live_state = (await comm.receive_json_from())["state"]
        assert live_state["artisan"]["position"]["lat"] == pytest.approx(NEARBY[0])         # pendant le trajet : oui
        await database_sync_to_async(lambda: api(art).post(url(b, "arrived/")))()
        after = (await comm.receive_json_from())["state"]
        assert after["phase"] == "arrived" and "5.37" not in coords(after) and after["artisan"]["position"] is None
        await database_sync_to_async(lambda: Booking.objects.get(pk=b.pk).transition_to("in_progress"))()
        started = (await comm.receive_json_from())["state"]
        assert "5.37" not in coords(started) and started["phase"] == "in_progress"
        await comm.disconnect()

    async_to_sync(scenario)()
