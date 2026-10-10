"""Continuité des activités : aucune demande, réservation ni mission perdue après fermeture, déconnexion, coupure réseau,
plantage ou changement d'appareil. Idempotence, doublons, versions concurrentes, isolation entre utilisateurs."""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from business.models import InterventionRequest, Organization, Site
from continuity import activities
from continuity.models import IdempotencyRecord
from continuity.tasks import purge_idempotency
from handy.models import Booking
from handy.test_eligibility import artisan, service

User = get_user_model()
pytestmark = pytest.mark.django_db
KEY = "a1b2c3d4-0001-4000-8000-000000000001"


def client_user(name):
    return User.objects.create_user(name, f"{name}@x.test", "pass1234", user_type="client", is_verified=True, first_name=name.title(), last_name="Test")


def api(u=None, **headers):
    c = APIClient(**headers)
    if u:
        c.force_authenticate(u)
    return c


def payload(svc, **extra):
    return {"service": svc.id, "booking_date": (timezone.now() + timedelta(days=2)).replace(microsecond=0).isoformat(),
            "address": "Rue 12", "city": "Abidjan", "postal_code": "00225", **extra}


def booking(c, a, status="pending", **kw):
    return Booking.objects.create(client=c, handyman=a, status=status, address="Rue 12", city="Abidjan",
                                  booking_date=kw.pop("booking_date", timezone.now() + timedelta(days=1)), **kw)


def seen_by(u):
    return {(i["kind"], i["id"]) for i in api(u).get("/handy/me/activities/").json()["activities"]}


# ── Idempotence : double appui, nouvelle tentative après coupure ou plantage ────────────────────────────────────────

def test_same_idempotency_key_never_creates_two_bookings():
    c, a = client_user("i_cli"), artisan("i_art")
    svc, body = service(a), None
    body = payload(svc)
    first = api(c).post("/handy/bookings/", body, format="json", HTTP_IDEMPOTENCY_KEY=KEY)
    assert first.status_code == 201 and "Idempotent-Replay" not in first
    again = api(c).post("/handy/bookings/", body, format="json", HTTP_IDEMPOTENCY_KEY=KEY)   # le téléphone a planté avant la réponse
    assert again.status_code == 201 and again["Idempotent-Replay"] == "true"
    assert again.json()["id"] == first.json()["id"]
    assert Booking.objects.filter(client=c).count() == 1


def test_key_reuse_with_another_request_is_refused_and_keys_are_per_user():
    c, other, a = client_user("k_cli"), client_user("k_other"), artisan("k_art")
    svc = service(a)
    assert api(c).post("/handy/bookings/", payload(svc), format="json", HTTP_IDEMPOTENCY_KEY=KEY).status_code == 201
    different = api(c).post("/handy/bookings/", payload(svc, address="Autre rue"), format="json", HTTP_IDEMPOTENCY_KEY=KEY)
    assert different.status_code == 422 and different.json()["code"] == "idempotency_key_reuse"
    assert Booking.objects.filter(client=c).count() == 1
    # la même clé chez un autre utilisateur est indépendante (aucune fuite de réponse entre comptes)
    mine = api(other).post("/handy/bookings/", payload(svc), format="json", HTTP_IDEMPOTENCY_KEY=KEY)
    assert mine.status_code == 201 and mine.json()["id"] != Booking.objects.filter(client=c).first().id


def test_failed_request_is_not_remembered_so_the_key_can_be_reused_after_correction():
    c, a = client_user("f_cli"), artisan("f_art")
    svc = service(a)
    bad = api(c).post("/handy/bookings/", {**payload(svc), "booking_date": "pas-une-date"}, format="json", HTTP_IDEMPOTENCY_KEY=KEY)
    assert bad.status_code == 400 and not IdempotencyRecord.objects.exists()
    good = api(c).post("/handy/bookings/", payload(svc), format="json", HTTP_IDEMPOTENCY_KEY=KEY)
    assert good.status_code == 201 and Booking.objects.count() == 1


def test_malformed_key_is_refused_and_missing_key_keeps_working():
    c, a = client_user("m_cli"), artisan("m_art")
    svc = service(a)
    assert api(c).post("/handy/bookings/", payload(svc), format="json", HTTP_IDEMPOTENCY_KEY="court").status_code == 400
    assert api(c).post("/handy/bookings/", payload(svc), format="json", HTTP_IDEMPOTENCY_KEY="x" * 90).status_code == 400
    assert api(c).post("/handy/bookings/", payload(svc), format="json").status_code == 201   # ancien client, sans clé
    assert not IdempotencyRecord.objects.exists()


def test_double_click_without_key_is_stopped_by_the_duplicate_guard():
    c, a = client_user("d_cli"), artisan("d_art")
    svc = service(a)
    body = payload(svc)
    first = api(c).post("/handy/bookings/", body, format="json")
    second = api(c).post("/handy/bookings/", body, format="json")
    assert first.status_code == 201
    assert second.status_code == 409 and second.json()["code"] == "duplicate_booking" and second.json()["existing_id"] == first.json()["id"]
    assert Booking.objects.count() == 1
    # un autre créneau n'est pas un doublon, ni la même demande après annulation
    assert api(c).post("/handy/bookings/", payload(svc, booking_date=(timezone.now() + timedelta(days=9)).isoformat()), format="json").status_code == 201
    Booking.objects.filter(pk=first.json()["id"]).update(status="cancelled")
    assert api(c).post("/handy/bookings/", body, format="json").status_code == 201


def test_idempotent_transition_replays_without_a_second_change():
    c, a = client_user("t_cli"), artisan("t_art")
    b = booking(c, a, "pending")
    first = api(a).post(f"/handy/bookings/{b.id}/transition/", {"status": "confirmed"}, format="json", HTTP_IDEMPOTENCY_KEY=KEY)
    again = api(a).post(f"/handy/bookings/{b.id}/transition/", {"status": "confirmed"}, format="json", HTTP_IDEMPOTENCY_KEY=KEY)
    assert first.status_code == again.status_code == 200 and again["Idempotent-Replay"] == "true"
    b.refresh_from_db()
    assert b.status == "confirmed" and b.version == 2 and b.timeline.count() == 1


def test_purge_removes_only_expired_keys():
    c = client_user("p_cli")
    old = IdempotencyRecord.objects.create(user=c, scope="x", key="k" * 10, request_hash="h", status_code=200, response={})
    IdempotencyRecord.objects.create(user=c, scope="x", key="j" * 10, request_hash="h", status_code=200, response={})
    IdempotencyRecord.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(hours=49))
    assert purge_idempotency() == 1 and IdempotencyRecord.objects.count() == 1


# ── Écritures concurrentes : versions ───────────────────────────────────────────────────────────────────────────────

def test_version_increments_and_a_stale_version_is_a_conflict_with_the_current_state():
    c, a = client_user("v_cli"), artisan("v_art")
    b = booking(c, a, "pending")
    url = f"/handy/bookings/{b.id}/transition/"
    assert api(a).get(f"/handy/bookings/{b.id}/").json()["version"] == 1
    ok = api(a).post(url, {"status": "confirmed", "expected_version": 1}, format="json")
    assert ok.status_code == 200 and ok.json()["version"] == 2
    # deuxième appareil resté sur la version 1 : conflit, jamais d'écrasement silencieux
    stale = api(a).post(url, {"status": "in_progress", "expected_version": 1}, format="json")
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    assert stale.json()["current"]["status"] == "confirmed" and stale.json()["current"]["version"] == 2
    assert Booking.objects.get(pk=b.pk).status == "confirmed"
    # version à jour : la transition passe ; If-Match équivalent à expected_version
    assert api(a).post(url, {"status": "in_progress"}, format="json", HTTP_IF_MATCH='"2"').status_code == 200
    assert api(a).post(url, {"status": "completed", "expected_version": "x"}, format="json").status_code == 400


def test_replayed_target_with_an_old_version_is_a_noop_not_a_conflict():
    """Le téléphone a envoyé « confirmer », la réponse s'est perdue : le renvoi (version périmée) réussit sans rien refaire."""
    c, a = client_user("r_cli"), artisan("r_art")
    b = booking(c, a, "pending")
    url = f"/handy/bookings/{b.id}/transition/"
    assert api(a).post(url, {"status": "confirmed", "expected_version": 1}, format="json").status_code == 200
    replay = api(a).post(url, {"status": "confirmed", "expected_version": 1}, format="json")
    assert replay.status_code == 200 and replay.json()["version"] == 2
    assert Booking.objects.get(pk=b.pk).timeline.count() == 1


def test_stale_in_memory_copy_cannot_overwrite_another_actors_transition():
    c, a = client_user("s_cli"), artisan("s_art")
    b = booking(c, a, "confirmed")
    copy_a, copy_b = Booking.objects.get(pk=b.pk), Booking.objects.get(pk=b.pk)   # deux appareils lisent le même état
    copy_a.transition_to("in_progress", actor=a)
    with pytest.raises(Exception) as err:
        copy_b.transition_to("cancelled", actor=c, expected_version=2 - 1)       # copie B croit encore à la version 1
    assert getattr(err.value, "code", None) == "version_conflict"
    assert Booking.objects.get(pk=b.pk).status == "in_progress"
    with pytest.raises(Exception):
        Booking.objects.get(pk=b.pk).transition_to("pending")                    # règles métier inchangées


def test_patch_with_a_stale_version_conflicts_and_valid_patch_bumps_the_version():
    c, a = client_user("u_cli"), artisan("u_art")
    b = booking(c, a, "pending")
    url = f"/handy/bookings/{b.id}/"
    ok = api(c).patch(url, {"description": "Fuite sous l'évier", "expected_version": 1}, format="json")
    assert ok.status_code == 200 and ok.json()["version"] == 2
    stale = api(c).patch(url, {"description": "Autre", "expected_version": 1}, format="json")
    assert stale.status_code == 409 and stale.json()["current"]["description"] == "Fuite sous l'évier"
    assert api(c).patch(url, {"status": "completed"}, format="json").json()["status"] == "pending"   # le statut ne se change pas par PATCH


# ── Reprise : activités en cours ────────────────────────────────────────────────────────────────────────────────────

def test_activities_list_my_active_items_with_role_deeplink_and_resume_label():
    c, a, other = client_user("a_cli"), artisan("a_art"), client_user("a_other")
    svc = service(a, "Dépannage fuite")
    running = booking(c, a, "in_progress", service=svc)
    waiting = booking(c, a, "pending", service=svc, booking_date=timezone.now() + timedelta(days=3))
    booking(c, a, "completed")
    booking(c, a, "cancelled")
    booking(other, a, "confirmed")
    mine = api(c).get("/handy/me/activities/").json()
    assert [i["id"] for i in mine["activities"]] == [running.id, waiting.id]                     # en cours d'abord, finies exclues
    first = mine["primary"]
    assert (first["kind"], first["role"], first["version"], first["deeplink"]) == ("booking", "client", 1, f"tratra://booking/{running.id}")
    assert first["resume_label"] == "Suivre ma réservation" and first["title"] == "Dépannage fuite"
    assert first["counterpart"] == "Membre Tratra" and "x.test" not in str(mine)               # nom public seulement, jamais l'e-mail
    pro = api(a).get("/handy/me/activities/").json()
    assert pro["primary"]["kind"] == "mission" and pro["primary"]["resume_label"] == "Reprendre ma mission"
    assert pro["primary"]["deeplink"].startswith("tratra://mission/")
    empty = api(client_user("a_nobody")).get("/handy/me/activities/").json()
    assert (empty["has_active"], empty["primary"], empty["activities"]) == (False, None, [])


def test_activities_never_expose_coordinates_or_the_full_address():
    c, a = client_user("g_cli"), artisan("g_art")
    booking(c, a, "in_progress")
    text = api(a).get("/handy/me/activities/").content.decode()
    for forbidden in ("lat", "lng", "location", "Rue 12", "polyline", "@x.test", "token"):
        assert forbidden not in text, forbidden


def test_activities_are_isolated_and_require_authentication():
    c1, c2, a = client_user("z_c1"), client_user("z_c2"), artisan("z_art")
    b1, b2 = booking(c1, a, "confirmed"), booking(c2, a, "confirmed")
    assert seen_by(c1) == {("booking", b1.id)} and seen_by(c2) == {("booking", b2.id)}
    assert seen_by(a) == {("mission", b1.id), ("mission", b2.id)}
    assert api().get("/handy/me/activities/").status_code in (401, 403)
    assert api(c1).get(f"/handy/bookings/{b2.id}/history/").status_code == 404                 # historique d'un tiers
    assert api(c1).post(f"/handy/bookings/{b2.id}/transition/", {"status": "cancelled"}, format="json").status_code == 404


def test_business_requests_only_for_their_requester():
    c, outsider, a = client_user("b_req"), client_user("b_out"), artisan("b_art")
    org = Organization.objects.create(name="Hôtel Ivoire", owner=c) if hasattr(Organization, "owner") else Organization.objects.create(name="Hôtel Ivoire")
    site = Site.objects.create(organization=org, name="Siège")
    r = InterventionRequest.objects.create(organization=org, number="INT-2026-0001", site=site, requested_by=c, title="Climatisation en panne")
    assert ("business_request", r.id) in seen_by(c) and ("business_request", r.id) not in seen_by(outsider)
    r.status = "completed"; r.save()
    assert ("business_request", r.id) not in seen_by(c)


def test_changes_since_lets_a_second_device_learn_what_happened():
    c, a = client_user("w_cli"), artisan("w_art")
    b = booking(c, a, "confirmed")
    cursor = api(c).get("/handy/me/activities/").json()["server_time"]               # téléphone 1 : état connu
    api(a).post(f"/handy/bookings/{b.id}/transition/", {"status": "cancelled"}, format="json")   # l'artisan annule
    second_phone = api(c).get(f"/handy/me/activities/?since={cursor}").json()          # téléphone 2 (même compte) se synchronise
    assert second_phone["has_active"] is False and second_phone["activities"] == []
    change = second_phone["changes"][0]
    assert (change["id"], change["status"], change["active"], change["version"]) == (b.id, "cancelled", False, 2)
    assert api(c).get("/handy/me/activities/?since=pas-une-date").status_code == 400
    assert api(client_user("w_other")).get(f"/handy/me/activities/?since={cursor}").json()["changes"] == []


def test_history_lists_status_events_with_role_only():
    c, a = client_user("h_cli"), artisan("h_art")
    b = booking(c, a, "pending")
    api(a).post(f"/handy/bookings/{b.id}/transition/", {"status": "confirmed"}, format="json")
    api(a).post(f"/handy/bookings/{b.id}/transition/", {"status": "in_progress"}, format="json")
    h = api(c).get(f"/handy/bookings/{b.id}/history/").json()
    assert [(e["previous_status"], e["status"], e["by"]) for e in h["events"]] == [("pending", "confirmed", "handyman"), ("confirmed", "in_progress", "handyman")]
    assert h["version"] == 3 and "h_art" not in str(h)


# ── Déconnexion, reconnexion, jeton expiré, changement de téléphone ─────────────────────────────────────────────────

def test_logout_never_cancels_a_mission_and_login_restores_it():
    c, a = client_user("o_cli"), artisan("o_art")
    b = booking(c, a, "in_progress")
    refresh = RefreshToken.for_user(a)
    out = APIClient().post("/handy/auth/logout/", {"refresh": str(refresh)}, format="json")      # déconnexion volontaire
    assert out.status_code == 200
    assert Booking.objects.get(pk=b.pk).status == "in_progress"                                    # la mission continue
    assert APIClient().post("/handy/auth/refresh/", {"refresh": str(refresh)}, format="json").status_code == 401   # jeton révoqué
    login = APIClient().post("/handy/auth/login/", {"username": "o_art", "password": "pass1234"}, format="json")
    assert login.status_code == 200
    token = login.json()["access"]
    restored = APIClient(HTTP_AUTHORIZATION=f"Bearer {token}").get("/handy/me/activities/").json()
    assert restored["primary"]["id"] == b.id and restored["primary"]["status"] == "in_progress"


def test_an_expired_access_token_is_refused_but_the_activity_is_untouched():
    c, a = client_user("e_cli"), artisan("e_art")
    b = booking(c, a, "confirmed")
    stale = APIClient(HTTP_AUTHORIZATION="Bearer jeton.expire.invalide")
    assert stale.get("/handy/me/activities/").status_code == 401
    assert stale.post(f"/handy/bookings/{b.id}/transition/", {"status": "in_progress"}, format="json").status_code == 401
    assert Booking.objects.get(pk=b.pk).status == "confirmed"


def test_new_phone_sees_the_same_activities_and_two_devices_converge():
    c, a = client_user("n_cli"), artisan("n_art")
    b = booking(c, a, "confirmed")
    phone_a, phone_b = api(c), api(c)                                                              # même compte, deux appareils
    assert phone_a.get("/handy/me/activities/").json()["primary"] == phone_b.get("/handy/me/activities/").json()["primary"]
    api(a).post(f"/handy/bookings/{b.id}/transition/", {"status": "in_progress"}, format="json")
    for phone in (phone_a, phone_b):
        assert phone.get("/handy/me/activities/").json()["primary"]["status"] == "in_progress"


def test_a_mission_survives_no_activity_at_all_after_everything_is_closed():
    """Fermeture de l'application = aucun appel serveur : l'état n'est lié ni à une session ni à un appareil."""
    c, a = client_user("x_cli"), artisan("x_art")
    b = booking(c, a, "in_progress")
    activities.active_for(a)                                    # lecture seule : aucun effet de bord
    assert Booking.objects.get(pk=b.pk).status == "in_progress" and Booking.objects.get(pk=b.pk).version == 1


# ── Concurrence réelle (deux connexions, verrou de ligne) ───────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_identical_transitions_apply_exactly_once():
    import threading

    c, a = client_user("c_cli"), artisan("c_art")
    b = booking(c, a, "confirmed")
    barrier, results = threading.Barrier(2), []

    def worker():
        try:
            barrier.wait(timeout=10)
            copy = Booking.objects.get(pk=b.pk)
            copy.transition_to("in_progress", actor=a)
            results.append("ok")
        except Exception as exc:  # noqa: BLE001 - on observe l'issue de chaque appel
            results.append(type(exc).__name__)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(timeout=30) for t in threads]
    final = Booking.objects.get(pk=b.pk)
    assert results == ["ok", "ok"]                         # la seconde voit l'état de la première : rien à refaire
    assert (final.status, final.version) == ("in_progress", 2)
    assert final.timeline.count() == 1                     # une seule entrée d'historique, un seul changement de version
