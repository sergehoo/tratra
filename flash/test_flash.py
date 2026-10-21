"""Tratra Flash & Smart Dispatch : filtrage, classement expliqué, vagues, refus et expiration, attribution atomique et idempotente,
concurrence PostgreSQL, devis, confidentialité, disponibilité, push prioritaire (FCM simulé)."""
import threading
from datetime import timedelta

import pytest
from django.contrib.gis.geos import Point
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from flash import services
from flash.models import DispatchConfig, DispatchEvent, MissionOffer, MissionRequest
from flash.services import FlashError
from handy.models import AvailabilitySlot, Booking, HandymanProfile, Notification, TimeOff

pytestmark = pytest.mark.django_db


def cfg(**values):
    c = DispatchConfig.get_solo()
    for k, v in values.items():
        setattr(c, k, v)
    c.save()
    return c


def offers_of(req, **filters):
    return list(MissionOffer.objects.filter(request=req, **filters).order_by("wave", "rank"))


def as_user(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


# ═══ Filtrage ════════════════════════════════════════════════════════════════════════════════════════════════════════

def test_only_eligible_available_pros_of_the_trade_and_zone_receive_the_mission(make_pro, make_handyman, make_category,
                                                                                make_service, make_request, client_user, plomberie):
    cfg(wave_size=10)
    ok = make_pro("ok")
    offline = make_pro("offline", online=False)
    far = make_pro("far", km=60)
    other_trade = make_pro("jardinier", category=make_category("jardinage-flash", name="Jardinage"))
    unverified = make_handyman("unverified", location=Point(-3.99, 5.37, srid=4326), online=True)
    make_service(unverified, plomberie)
    on_leave = make_pro("conge")
    TimeOff.objects.create(handyman=on_leave.handyman_profile, start=timezone.now() - timedelta(hours=1), end=timezone.now() + timedelta(hours=5))
    busy = make_pro("occupe")
    Booking.objects.create(client=client_user, handyman=busy, status="confirmed", address="x", city="Abidjan", booking_date=timezone.now())
    req = make_request()
    contacted = {o.handyman_id for o in offers_of(req)}
    assert contacted == {ok.pk}
    ranked, rejected = services.candidates(req, DispatchConfig.get_solo(), explain=True)
    reasons = {r["user_id"]: r["reason"] for r in rejected}
    assert reasons[offline.pk].startswith("Indisponible")
    assert reasons[far.pk] == "Hors zone"
    assert reasons[on_leave.pk] == "Absence déclarée"
    assert reasons[busy.pk] == "Autre mission au même moment"
    assert reasons[ok.pk] == "Déjà sollicité pour cette demande"
    assert other_trade.pk not in reasons and unverified.pk not in reasons     # jamais candidats : métier, vérification


def test_the_client_never_receives_his_own_request_and_hours_are_respected(make_pro, make_request, client_user):
    cfg(wave_size=10)
    pro = make_pro("horaires")
    tomorrow_9 = timezone.localtime(timezone.now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    AvailabilitySlot.objects.create(handyman=pro.handyman_profile, weekday=(tomorrow_9.weekday() + 1) % 7,
                                    start_time=tomorrow_9.time(), end_time=tomorrow_9.replace(hour=17).time())
    req = services.create_request(pro, category=req_cat(), address="A", commune="Cocody", amount=12000,
                                  scheduled_for=tomorrow_9, lat=5.36, lng=-3.99)
    assert offers_of(req) == [] and req.status == MissionRequest.UNFULFILLED   # son propre besoin + hors horaires
    assert DispatchEvent.objects.filter(request=req, kind="no_candidate").exists()


def req_cat():
    from handy.models import ServiceCategory

    return ServiceCategory.objects.get(slug="plomberie-flash")


def test_scheduled_missions_ignore_the_instant_switch_but_immediate_ones_never_do(make_pro, make_request):
    cfg(wave_size=10)
    paused = make_pro("pause", online=False)
    immediate = make_request()
    assert offers_of(immediate) == []
    later = make_request(minutes=60 * 24)
    assert [o.handyman_id for o in offers_of(later)] == [paused.pk]


# ═══ Classement ══════════════════════════════════════════════════════════════════════════════════════════════════════

def test_ranking_is_explained_and_new_pros_get_neutral_values_not_zero(make_pro, make_request):
    cfg(wave_size=10)
    make_pro("nouveau", km=2)
    req = make_request()
    offer = offers_of(req)[0]
    crit = {c["key"]: c for c in offer.score_detail["criteria"]}
    assert set(crit) == {"distance", "trust", "rating", "reactivity", "fairness"}
    for key in ("trust", "rating", "reactivity"):
        assert crit[key]["measured"] is False and crit[key]["value"] == DispatchConfig.get_solo().neutral_value
    assert crit["fairness"]["value"] == 1.0                    # aucune mission récente : favorisé, pas pénalisé
    assert abs(sum(c["points"] for c in crit.values()) - offer.score) < 0.5
    assert offer.distance_km == pytest.approx(2.0, abs=0.05)


def test_weights_are_configurable(make_pro, make_request):
    near, far = make_pro("proche", km=1), make_pro("loin", km=10)
    HandymanProfile.objects.filter(user=far).update(trust_score=100)
    HandymanProfile.objects.filter(user=near).update(trust_score=20)
    cfg(wave_size=1, weight_distance=100, weight_trust=0, weight_rating=0, weight_reactivity=0, weight_fairness=0)
    assert offers_of(make_request())[0].handyman_id == near.pk
    MissionRequest.objects.update(status=MissionRequest.CANCELLED)
    MissionOffer.objects.update(status=MissionOffer.WITHDRAWN)
    cfg(weight_distance=0, weight_trust=100)
    assert offers_of(make_request())[0].handyman_id == far.pk


# ═══ Vagues, refus, expiration ═══════════════════════════════════════════════════════════════════════════════════════

def test_refusals_trigger_the_next_wave_at_once_and_carry_no_penalty(make_pro, make_request, django_capture_on_commit_callbacks):
    cfg(wave_size=2, max_waves=3)
    a, b, c = make_pro("a", km=1), make_pro("b", km=2), make_pro("c", km=3)
    req = make_request()
    first = offers_of(req)
    assert [o.handyman_id for o in first] == [a.pk, b.pk] and all(o.wave == 1 for o in first)
    with django_capture_on_commit_callbacks(execute=True):
        services.decline(first[0].pk, a, "busy")
    assert len(offers_of(req)) == 2                             # B attend encore : pas de nouvelle vague
    with django_capture_on_commit_callbacks(execute=True):
        services.decline(first[1].pk, b)
    second = offers_of(req, wave=2)
    assert [o.handyman_id for o in second] == [c.pk]
    from trust.models import TrustPenalty

    assert not TrustPenalty.objects.exists()
    assert services.decline(first[0].pk, a).status == MissionOffer.DECLINED   # rejeu : sans erreur ni effet


def test_expiry_moves_to_the_next_wave_then_the_request_is_unfulfilled(make_pro, make_request, client_user):
    cfg(wave_size=1, max_waves=2)
    a, b = make_pro("a", km=1), make_pro("b", km=2)
    req = make_request()
    later = timezone.now() + timedelta(seconds=DispatchConfig.get_solo().offer_timeout_seconds + 30)
    services.expire_due(now=later)
    assert [o.status for o in offers_of(req)] == [MissionOffer.EXPIRED, MissionOffer.PENDING]
    services.expire_due(now=later + timedelta(seconds=200))
    req.refresh_from_db()
    assert req.status == MissionRequest.UNFULFILLED
    kinds = list(DispatchEvent.objects.filter(request=req).values_list("kind", flat=True))
    assert kinds.count("wave") == 2 and kinds.count("expired") == 2 and "unfulfilled" in kinds
    with pytest.raises(FlashError) as e:
        services.accept(offers_of(req)[1].pk, b)
    assert e.value.code in ("request_closed", "offer_expired")


def test_repeated_silence_pauses_availability_without_any_reputation_effect(make_pro, make_request, make_user,
                                                                            django_capture_on_commit_callbacks):
    cfg(wave_size=1, max_waves=1, auto_pause_after_missed=2, max_active_requests_per_client=10)
    pro = make_pro("silencieux")
    clients = [make_user(f"cli{i}") for i in range(2)]
    t = timezone.now()
    for cli in clients:
        make_request(client=cli)
        t += timedelta(seconds=DispatchConfig.get_solo().offer_timeout_seconds + 30)
        with django_capture_on_commit_callbacks(execute=True):
            services.expire_due(now=t)
    profile = HandymanProfile.objects.get(user=pro)
    assert profile.online is False
    assert Notification.objects.filter(user=pro, notification_type="mission_paused").count() == 1
    from trust.models import TrustPenalty

    assert not TrustPenalty.objects.filter(user=pro).exists()


# ═══ Attribution ═════════════════════════════════════════════════════════════════════════════════════════════════════

def test_firm_acceptance_creates_one_confirmed_booking_and_closes_the_others(make_pro, make_request, client_user,
                                                                           django_capture_on_commit_callbacks):
    cfg(wave_size=3)
    a, b, c = make_pro("a"), make_pro("b", km=2), make_pro("c", km=3)
    with django_capture_on_commit_callbacks(execute=True):
        req = make_request(amount=18000)
    offer_a, offer_b, _ = offers_of(req)
    assert Notification.objects.filter(user=a, notification_type="new_mission", is_read=False).count() == 1
    with django_capture_on_commit_callbacks(execute=True):
        services.accept(offer_b.pk, b)
    req.refresh_from_db()
    booking = req.booking
    assert req.status == MissionRequest.ASSIGNED and req.assigned_to == b
    assert booking.status == "confirmed" and booking.handyman == b and booking.client == client_user
    assert booking.total_price == 18000 and booking.transport_fee == 0 and booking.address == "Rue des Jardins, villa 12"
    assert {o.handyman_id: o.status for o in offers_of(req)} == {a.pk: "withdrawn", b.pk: "accepted", c.pk: "withdrawn"}
    assert not Notification.objects.filter(user=b, notification_type="booking_request").exists()   # il vient d'accepter
    assert Notification.objects.filter(user=client_user, notification_type="booking_confirmed").exists()
    assert Notification.objects.filter(user=a, dedupe_key=f"flash:offer:{offer_a.pk}", is_read=True).exists()   # alerte close
    with pytest.raises(FlashError) as e:
        services.accept(offer_a.pk, a)
    assert e.value.code == "already_assigned" and e.value.status == 409
    assert services.accept(offer_b.pk, b).booking_id == booking.pk          # rejeu du gagnant : même résultat
    assert Booking.objects.filter(handyman=b).count() == 1


def test_accepting_through_the_api_is_idempotent(make_pro, make_request):
    pro = make_pro("api")
    offer = offers_of(make_request())[0]
    api = as_user(pro)
    r1 = api.post(f"/handy/flash/offers/{offer.pk}/accept/", {}, format="json", HTTP_IDEMPOTENCY_KEY="flash-accept-0001")
    r2 = api.post(f"/handy/flash/offers/{offer.pk}/accept/", {}, format="json", HTTP_IDEMPOTENCY_KEY="flash-accept-0001")
    assert r1.status_code == r2.status_code == 200 and r2["Idempotent-Replay"] == "true"
    assert r1.json()["status"] == "accepted" and r1.json()["booking"] == r2.json()["booking"]
    assert Booking.objects.filter(handyman=pro).count() == 1


def test_an_expired_offer_cannot_be_accepted(make_pro, make_request):
    pro = make_pro("lent")
    offer = offers_of(make_request())[0]
    with pytest.raises(FlashError) as e:
        services.accept(offer.pk, pro, now=offer.expires_at + timedelta(seconds=30))
    assert e.value.code == "offer_expired"


@pytest.mark.django_db(transaction=True)
def test_concurrent_acceptances_assign_the_mission_exactly_once(make_pro, make_request):
    cfg(wave_size=6)
    pros = [make_pro(f"rapide{i}", km=1 + i) for i in range(6)]
    req = make_request()
    offers = {o.handyman_id: o.pk for o in offers_of(req)}
    barrier, results = threading.Barrier(len(pros)), []

    def run(pro):
        try:
            barrier.wait()
            services.accept(offers[pro.pk], pro)
            results.append("ok")
        except FlashError as e:
            results.append(e.code)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(p,)) for p in pros]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1 and set(results) - {"ok"} <= {"already_assigned"}
    assert MissionOffer.objects.filter(request=req, status="accepted").count() == 1
    assert Booking.objects.filter(flash_request=req).count() == 1 and Booking.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_one_pro_cannot_win_two_overlapping_missions_at_the_same_time(make_pro, make_request, make_user):
    cfg(wave_size=1, max_active_requests_per_client=5)
    pro = make_pro("double")
    r1 = make_request(client=make_user("c1"))
    MissionOffer.objects.filter(request=r1).update(expires_at=timezone.now() + timedelta(minutes=5))
    # 2e demande : la proposition en attente l'exclurait ; on la crée directement pour simuler deux alertes simultanées.
    r2 = MissionRequest.objects.create(client=make_user("c2"), category=r1.category, address="B", commune="Cocody", location=r1.location,
                                       scheduled_for=r1.scheduled_for, is_immediate=True, amount=15000, wave=1)
    o2 = MissionOffer.objects.create(request=r2, handyman=pro, wave=1, rank=1, score=50, expires_at=timezone.now() + timedelta(minutes=5))
    o1 = offers_of(r1)[0]
    barrier, results = threading.Barrier(2), []

    def run(offer_id):
        try:
            barrier.wait()
            services.accept(offer_id, pro)
            results.append("ok")
        except FlashError as e:
            results.append(e.code)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(oid,)) for oid in (o1.pk, o2.pk)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["ok", "schedule_conflict"]
    assert Booking.objects.filter(handyman=pro, status="confirmed").count() == 1


# ═══ Sur devis ═══════════════════════════════════════════════════════════════════════════════════════════════════════

def test_quote_mode_lets_the_client_choose_and_the_window_closes(make_pro, make_request, client_user, django_capture_on_commit_callbacks):
    cfg(wave_size=2, max_quotes=2)
    a, b = make_pro("a"), make_pro("b", km=2)
    req = make_request(mode="quote")
    oa, ob = offers_of(req)
    with pytest.raises(FlashError):
        services.accept(oa.pk, a)                                   # pas d'acceptation ferme sur devis
    with django_capture_on_commit_callbacks(execute=True):
        services.send_quote(oa.pk, a, 25000, "Pièces comprises")
        services.send_quote(ob.pk, b, 22000)
    assert Notification.objects.filter(user=client_user, notification_type="mission_quote").count() == 2
    req.refresh_from_db()
    assert req.status == MissionRequest.QUOTING and req.quote_deadline is not None
    payload = as_user(client_user).get(f"/handy/flash/requests/{req.pk}/").json()
    assert sorted(q["amount"] for q in payload["quotes"]) == [22000, 25000]
    r = as_user(client_user).post(f"/handy/flash/requests/{req.pk}/quotes/{ob.pk}/accept/", {}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "assigned" and r.json()["assigned_to"]["id"] == b.pk
    req.refresh_from_db()
    assert req.booking.total_price == 22000
    assert MissionOffer.objects.get(pk=oa.pk).status == MissionOffer.WITHDRAWN


def test_quote_window_elapsed_without_choice(make_pro, make_request):
    cfg(wave_size=1, max_quotes=1)
    a = make_pro("a")
    req = make_request(mode="quote")
    services.send_quote(offers_of(req)[0].pk, a, 20000)
    services.launch_wave(req.pk)
    req.refresh_from_db()
    assert req.status == MissionRequest.QUOTING
    services.expire_due(now=req.quote_deadline + timedelta(minutes=1))
    req.refresh_from_db()
    assert req.status == MissionRequest.UNFULFILLED


# ═══ Confidentialité, droits, client ═════════════════════════════════════════════════════════════════════════════════

def test_before_acceptance_the_pro_sees_no_private_client_data(make_pro, make_request, client_user):
    pro = make_pro("discret")
    offer = offers_of(make_request(description="Fuite sous l'évier"))[0]
    data = as_user(pro).get(f"/handy/flash/offers/{offer.pk}/").json()
    assert data["category"] == "Plomberie" and data["zone"] == "Cocody" and data["amount"] == "15000" and data["seconds_left"] > 0
    assert "address" not in data and "client_name" not in data
    flat = str(data)
    assert "Rue des Jardins" not in flat and "Awa" not in flat and "+225" not in flat
    assert MissionOffer.objects.get(pk=offer.pk).seen_at is not None
    data = as_user(pro).post(f"/handy/flash/offers/{offer.pk}/accept/", {}, format="json").json()
    assert data["address"] == "Rue des Jardins, villa 12" and data["client_name"] == "Awa"


def test_requests_and_offers_are_private_to_their_owner(make_pro, make_request, make_user):
    pro = make_pro("p")
    req = make_request()
    offer = offers_of(req)[0]
    intruder = as_user(make_user("intrus"))
    assert intruder.get(f"/handy/flash/requests/{req.pk}/").status_code == 404
    assert intruder.get(f"/handy/flash/offers/{offer.pk}/").status_code == 404
    assert intruder.post(f"/handy/flash/offers/{offer.pk}/accept/", {}, format="json").status_code == 404


def test_client_api_creates_cancels_and_relaunches(make_pro, client_user, plomberie):
    make_pro("p")
    api = as_user(client_user)
    r = api.post("/handy/flash/requests/", {"category": plomberie.pk, "address": "Rue 1", "commune": "Cocody", "amount": "15 000",
                                            "lat": 5.36, "lng": -3.99}, format="json", HTTP_IDEMPOTENCY_KEY="flash-req-000001")
    assert r.status_code == 201, r.content
    again = api.post("/handy/flash/requests/", {"category": plomberie.pk, "address": "Rue 1", "commune": "Cocody", "amount": "15 000",
                                                "lat": 5.36, "lng": -3.99}, format="json", HTTP_IDEMPOTENCY_KEY="flash-req-000001")
    assert again.json()["id"] == r.json()["id"] and MissionRequest.objects.count() == 1
    body = r.json()
    assert body["status"] == "searching" and body["progress"]["contacted"] == 1 and body["amount"] == 15000
    assert api.post(f"/handy/flash/requests/{body['id']}/relaunch/", {}, format="json").status_code == 409
    c = api.post(f"/handy/flash/requests/{body['id']}/cancel/", {}, format="json").json()
    assert c["status"] == "cancelled" and c["can_relaunch"] is True
    assert MissionOffer.objects.get(request_id=body["id"]).status == MissionOffer.WITHDRAWN
    relaunched = api.post(f"/handy/flash/requests/{body['id']}/relaunch/", {}, format="json")
    assert relaunched.status_code == 201 and relaunched.json()["id"] != body["id"]
    bad = api.post("/handy/flash/requests/", {"category": plomberie.pk, "address": "Rue 1", "commune": "Cocody", "amount": 200}, format="json")
    assert bad.status_code == 400 and bad.json()["code"] == "amount_too_low"


# ═══ Disponibilité ═══════════════════════════════════════════════════════════════════════════════════════════════════

def test_availability_state_and_the_existing_presence_switch(make_pro, make_handyman, make_request):
    pro = make_pro("dispo", online=False)
    r = as_user(pro).post("/handy/handymen/presence/", {"online": True}, format="json")
    assert r.status_code == 200 and r.json() == {"online": True}          # contrat historique inchangé
    stranger = make_handyman("pasverifie")
    assert as_user(stranger).post("/handy/handymen/presence/", {"online": True}, format="json").status_code == 403
    state = as_user(pro).get("/handy/flash/availability/").json()
    assert state["online"] is True and state["eligible"] is True and state["missed_streak"] == 0
    make_request()
    assert as_user(pro).get("/handy/flash/availability/").json()["pending_offers"] == 1
    # Approuvé mais dossier incomplet : « Disponible » possible (contrat historique) mais AUCUNE mission proposée (règle d'éligibilité).
    half = make_handyman("demi", location=Point(-3.99, 5.361, srid=4326))
    HandymanProfile.objects.filter(user=half).update(is_approved=True, online=True)
    state = as_user(half).get("/handy/flash/availability/").json()
    assert state["eligible"] is False and state["reason"]
    assert not MissionOffer.objects.filter(handyman=half).exists()


# ═══ Push prioritaire (FCM simulé) ═══════════════════════════════════════════════════════════════════════════════════

def test_new_mission_push_is_a_data_message_for_flash_capable_phones_and_never_sent_once_closed(
        make_pro, make_request, settings, monkeypatch, django_capture_on_commit_callbacks, tmp_path):
    from handy import push
    from handy.models import Device
    from handy.tasks import send_notification_push
    from handy.test_push import FakeHTTP

    import json as _json
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    sa = tmp_path / "sa.json"
    sa.write_text(_json.dumps({"project_id": "tratra-test", "client_email": "p@x.test", "private_key": pem, "token_uri": "https://oauth.test/token"}))
    settings.FCM_CREDENTIALS_FILE = str(sa)
    push.reset_cache()
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)

    pro = make_pro("sonnerie")
    Device.objects.create(user=pro, device_token="new-app", device_type="android", capabilities=["flash1"])
    Device.objects.create(user=pro, device_token="old-app", device_type="android")
    Device.objects.create(user=pro, device_token="iphone", device_type="ios")
    with django_capture_on_commit_callbacks(execute=True):
        req = make_request()
    msgs = {kw["json"]["message"]["token"]: kw["json"]["message"] for url, kw in http.calls if "fcm.googleapis" in url}
    assert set(msgs) == {"new-app", "old-app", "iphone"}
    new = msgs["new-app"]
    assert "notification" not in new and new["data"]["t"] == "new_mission" and new["data"]["kind"] == "flash_offer"
    assert new["android"]["priority"] == "high" and int(new["android"]["ttl"][:-1]) <= DispatchConfig.get_solo().offer_timeout_seconds
    assert new["data"]["zone"] == "Cocody" and "Rue des Jardins" not in str(new)
    assert 0 < int(new["data"]["expires_in"]) <= DispatchConfig.get_solo().offer_timeout_seconds
    assert new["data"]["title"] == "Nouvelle mission · Plomberie" and "pour répondre" in new["data"]["body"]
    old = msgs["old-app"]["android"]["notification"]
    assert old["channel_id"] == "tratra_new_missions" and old["sound"] == "tratra_flash" and old["visibility"] == "PRIVATE"
    assert msgs["iphone"]["apns"]["payload"]["aps"]["sound"] == "tratra_flash.caf"
    assert msgs["iphone"]["apns"]["payload"]["aps"]["category"] == "NEW_MISSION"
    n = Notification.objects.get(user=pro, notification_type="new_mission")
    assert n.push_status == "sent" and n.category == "flash"

    # Proposition close : l'alerte est retirée (signal silencieux) et un push en retard n'est jamais envoyé.
    http.calls.clear()
    offer = offers_of(req)[0]
    with django_capture_on_commit_callbacks(execute=True):
        services.decline(offer.pk, pro)
    closed = [kw["json"]["message"] for url, kw in http.calls if "fcm.googleapis" in url]
    assert [m["token"] for m in closed] == ["new-app"] and closed[0]["data"] == {"t": "flash_closed", "offer": str(offer.pk), "status": "declined"}
    Notification.objects.filter(pk=n.pk).update(push_status="queued")
    assert send_notification_push(n.pk) == {"skipped": "obsolete"}
    assert Notification.objects.get(pk=n.pk).push_status == "obsolete"
    push.reset_cache()


def test_device_registration_keeps_only_known_capabilities(make_user):
    u = make_user("appareil")
    r = as_user(u).post("/handy/devices/", {"device_token": "tok-1", "device_type": "android", "capabilities": ["flash1", "inconnue"]},
                        format="json")
    assert r.status_code == 201 and r.json()["capabilities"] == ["flash1"]
    r = as_user(u).post("/handy/devices/", {"device_token": "tok-1", "device_type": "android"}, format="json")
    assert r.json()["capabilities"] == []   # ancienne version de l'application : alerte classique
