"""Hybrid Matching : une seule commande, deux modes (AUTO_MATCH / DIRECT_SELECTION), bascule confirmée sans ressaisie ni attribution
concurrente, favoris et réservation rapide, suggestion du mode, droits, idempotence, expiration, notifications, réputation."""
import threading
from datetime import timedelta
from urllib.parse import quote_plus

import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from flash import hybrid, services
from flash.models import DispatchConfig, DispatchEvent, MissionOffer, MissionRequest
from flash.services import FlashError
from handy.models import Booking, FavoriteHandyman, HandymanProfile, Notification
from trust.models import TrustPenalty

pytestmark = pytest.mark.django_db


def cfg(**values):
    c = DispatchConfig.get_solo()
    for k, v in values.items():
        setattr(c, k, v)
    c.save()
    return c


def as_user(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def direct(client_user, plomberie, pro, **kw):
    return services.create_request(client_user, category=plomberie, address="Rue des Jardins, villa 12", commune="Cocody",
                                   amount=kw.pop("amount", 15000), lat=5.36, lng=-3.99, matching="direct", target_id=pro.pk, **kw)


# ═══ DIRECT_SELECTION ═══════════════════════════════════════════════════════════════════════════════════════════════════

def test_direct_selection_proposes_only_to_the_chosen_pro_with_the_same_flash_alert(make_pro, client_user, plomberie,
                                                                                   django_capture_on_commit_callbacks):
    chosen, other = make_pro("choisi", km=3), make_pro("autre", km=1)
    with django_capture_on_commit_callbacks(execute=True):
        req = direct(client_user, plomberie, chosen)
    offers = list(req.offers.all())
    assert [o.handyman_id for o in offers] == [chosen.pk] and offers[0].targeted is True
    assert req.matching == "direct" and req.target == chosen and req.status == "searching"
    n = Notification.objects.get(user=chosen, notification_type="new_mission")
    assert n.title == "Un client vous a choisi · Plomberie" and n.data["direct"] == "1"
    assert not Notification.objects.filter(user=other, notification_type="new_mission").exists()
    assert offers[0].expires_at - offers[0].sent_at >= timedelta(seconds=DispatchConfig.get_solo().direct_offer_timeout_seconds - 1)
    req = services.accept(offers[0].pk, chosen)
    assert req.status == "assigned" and req.booking.handyman == chosen and req.booking.status == "confirmed"


def test_direct_booking_of_a_fixed_price_offer_uses_its_price_and_the_chosen_service(make_pro, make_service, client_user, plomberie):
    pro = make_pro("fixe", service=False)
    svc = make_service(pro, plomberie, title="Débouchage", price="12000")
    r = as_user(client_user).post("/handy/flash/requests/", {"category": plomberie.pk, "address": "Rue 1", "commune": "Cocody",
                                                            "lat": 5.36, "lng": -3.99, "matching": "direct", "target": pro.pk,
                                                            "service": svc.pk}, format="json")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["amount"] == 12000 and body["matching"] == "direct" and body["target"]["id"] == pro.pk and body["service"]["id"] == svc.pk
    req = services.accept(MissionOffer.objects.get(request_id=body["id"]).pk, pro)
    assert req.booking.service == svc and req.booking.total_price == 12000


def test_a_chosen_pro_must_be_eligible_of_the_trade_and_available(make_pro, make_handyman, make_category, client_user, plomberie):
    offline = make_pro("pause", online=False)
    with pytest.raises(FlashError) as e:
        direct(client_user, plomberie, offline)                               # mission immédiate : « Indisponible » respecté
    assert e.value.code == "pro_busy" and e.value.status == 409 and "Indisponible" in e.value.extra["reason"]
    gardener = make_pro("jardinier", category=make_category("jardin-h", name="Jardinage"))
    with pytest.raises(FlashError) as e:
        direct(client_user, plomberie, gardener)
    assert e.value.code == "wrong_trade"
    unverified = make_handyman("pasverifie")
    with pytest.raises(FlashError) as e:
        direct(client_user, plomberie, unverified)
    assert e.value.code == "pro_unavailable"
    assert not MissionRequest.objects.exists()                                # aucune commande à moitié créée


def test_a_chosen_pro_refusing_or_not_answering_leaves_the_choice_to_the_client_without_penalty(
        make_pro, client_user, plomberie, django_capture_on_commit_callbacks):
    pro, other = make_pro("occupe"), make_pro("libre", km=2)
    req = direct(client_user, plomberie, pro)
    with django_capture_on_commit_callbacks(execute=True):
        services.decline(req.offers.get().pk, pro, "busy")
    req.refresh_from_db()
    assert req.status == "awaiting" and req.is_open
    assert not MissionOffer.objects.filter(handyman=other).exists()           # rien n'est relancé sans le client
    n = Notification.objects.get(user=client_user, notification_type="mission_choice")
    assert "n'est pas disponible" in n.message and n.data == {"kind": "flash_request", "id": req.pk}
    assert not TrustPenalty.objects.exists()
    # Sans réponse dans le délai : même issue, motif adapté.
    req2 = direct(client_user, plomberie, other)
    later = timezone.now() + timedelta(seconds=DispatchConfig.get_solo().direct_offer_timeout_seconds + 30)
    services.expire_due(now=later)
    req2.refresh_from_db()
    assert req2.status == "awaiting"
    assert DispatchEvent.objects.filter(request=req2, kind="awaiting", data__reason="n'a pas répondu à temps").exists()


# ═══ Bascule entre modes ════════════════════════════════════════════════════════════════════════════════════════════════

def test_switch_direct_to_auto_needs_confirmation_keeps_the_order_and_never_reoffers_the_first_pro(
        make_pro, client_user, plomberie, django_capture_on_commit_callbacks):
    cfg(wave_size=5)
    chosen, a, b = make_pro("choisi"), make_pro("a", km=2), make_pro("b", km=3)
    req = direct(client_user, plomberie, chosen)
    with pytest.raises(FlashError) as e:
        hybrid.switch(req.pk, client_user, "auto")
    assert e.value.code == "confirmation_required"
    with django_capture_on_commit_callbacks(execute=True):
        switched = hybrid.switch(req.pk, client_user, "auto", confirm=True, expected_version=req.version)
    assert switched.pk == req.pk and switched.matching == "auto" and switched.switches == 1
    assert switched.address == "Rue des Jardins, villa 12" and switched.amount == 15000              # aucune ressaisie
    statuses = {o.handyman_id: o.status for o in switched.offers.all()}
    assert statuses[chosen.pk] == "withdrawn" and statuses[a.pk] == statuses[b.pk] == "pending"
    with pytest.raises(FlashError):
        services.accept(MissionOffer.objects.get(request=req, handyman=chosen).pk, chosen)           # l'ancienne proposition est close
    assert DispatchEvent.objects.filter(request=req, kind="switched", data__to="auto").exists()


def test_switch_auto_to_direct_withdraws_the_waves_before_the_targeted_offer(make_pro, make_request, client_user):
    cfg(wave_size=2)
    a, b, chosen = make_pro("a", km=1), make_pro("b", km=2), make_pro("choisi", km=4)
    req = make_request()
    first_wave = list(req.offers.values_list("handyman_id", flat=True))
    assert set(first_wave) == {a.pk, b.pk}
    with pytest.raises(FlashError) as e:
        hybrid.switch(req.pk, client_user, "direct", target_id=a.pk, confirm=True)
    assert e.value.code == "already_contacted"
    req = hybrid.switch(req.pk, client_user, "direct", target_id=chosen.pk, confirm=True)
    assert {o.handyman_id: o.status for o in req.offers.all()} == {a.pk: "withdrawn", b.pk: "withdrawn", chosen.pk: "pending"}
    assert req.offers.get(handyman=chosen).targeted is True and req.target == chosen
    with pytest.raises(FlashError) as e:
        hybrid.switch(req.pk, client_user, "auto", confirm=True, expected_version=req.version - 1)
    assert e.value.code == "version_conflict"


def test_switch_after_assignment_is_refused(make_pro, client_user, plomberie):
    pro = make_pro("rapide")
    req = direct(client_user, plomberie, pro)
    services.accept(req.offers.get().pk, pro)
    with pytest.raises(FlashError) as e:
        hybrid.switch(req.pk, client_user, "auto", confirm=True)
    assert e.value.code == "already_assigned" and e.value.status == 409


@pytest.mark.django_db(transaction=True)
def test_switch_and_acceptance_racing_never_produce_two_attributions(make_pro, client_user, plomberie):
    for attempt in range(4):
        pro = make_pro(f"course{attempt}")
        other = make_pro(f"remplacant{attempt}", km=2)
        req = direct(client_user, plomberie, pro)
        offer = req.offers.get()
        barrier, results = threading.Barrier(2), {}

        def accept():
            try:
                barrier.wait()
                services.accept(offer.pk, pro)
                results["accept"] = "ok"
            except FlashError as e:
                results["accept"] = e.code
            finally:
                connection.close()

        def switch():
            try:
                barrier.wait()
                hybrid.switch(req.pk, client_user, "direct", target_id=other.pk, confirm=True)
                results["switch"] = "ok"
            except FlashError as e:
                results["switch"] = e.code
            finally:
                connection.close()

        threads = [threading.Thread(target=accept), threading.Thread(target=switch)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert sorted(results.values()).count("ok") == 1, results
        req.refresh_from_db()
        assert Booking.objects.filter(flash_request=req).count() == (1 if results["accept"] == "ok" else 0)
        assert MissionOffer.objects.filter(request=req, status="accepted").count() <= 1
        MissionRequest.objects.filter(pk=req.pk, status__in=MissionRequest.OPEN).update(status="cancelled")
        Booking.objects.filter(flash_request=req).update(status="cancelled")


def test_switch_through_the_api_is_idempotent_and_private(make_pro, client_user, plomberie, make_user):
    chosen, other = make_pro("choisi"), make_pro("autre", km=2)
    req = direct(client_user, plomberie, chosen)
    api = as_user(client_user)
    body = {"to": "direct", "target": other.pk, "confirm": True}
    r1 = api.post(f"/handy/flash/requests/{req.pk}/switch/", body, format="json", HTTP_IDEMPOTENCY_KEY="switch-0000001")
    r2 = api.post(f"/handy/flash/requests/{req.pk}/switch/", body, format="json", HTTP_IDEMPOTENCY_KEY="switch-0000001")
    assert r1.status_code == r2.status_code == 200 and r2["Idempotent-Replay"] == "true"
    assert MissionOffer.objects.filter(request=req, handyman=other).count() == 1 and r1.json()["switches"] == 1
    assert as_user(make_user("intrus")).post(f"/handy/flash/requests/{req.pk}/switch/", body, format="json").status_code == 404
    assert APIClient().get("/handy/flash/pros/?category=1").status_code == 401


# ═══ Choisir son professionnel, favoris, suggestion ═════════════════════════════════════════════════════════════════════

def test_pros_list_shows_profiles_reviews_badges_and_favorites_first_without_private_data(make_pro, client_user, plomberie):
    near, fav = make_pro("proche", km=1), make_pro("favori", km=6, phone="+2250700009999")
    make_pro("absent", online=False)
    FavoriteHandyman.objects.create(client=client_user, handyman=fav)
    r = as_user(client_user).get(f"/handy/flash/pros/?category={plomberie.pk}&lat=5.36&lng=-3.99&sort=distance")
    rows = r.json()["results"]
    assert [p["id"] for p in rows] == [fav.pk, near.pk]                       # favori d'abord, puis le plus proche ; « Indisponible » absent
    card = rows[1]
    assert {"name", "photo", "trust_score", "badges", "rating", "reviews", "distance_km", "offers", "why"} <= set(card)
    assert card["distance_km"] == pytest.approx(1.0, abs=0.05) and card["offers"][0]["price"] == 5000
    assert "+225" not in str(rows) and "@" not in str(rows)


def test_favorites_and_quick_booking(make_pro, make_handyman, client_user, plomberie):
    fav = make_pro("habituel")
    api = as_user(client_user)
    assert api.post("/handy/me/favorites/", {"handyman": fav.pk}, format="json").status_code == 201
    assert api.post("/handy/me/favorites/", {"handyman": fav.pk}, format="json").status_code == 201   # pas de doublon
    assert FavoriteHandyman.objects.filter(client=client_user).count() == 1
    rows = api.get("/handy/me/favorites/").json()["results"]
    assert rows[0]["id"] == fav.pk and rows[0]["bookable"] is True and rows[0]["trades"] == ["Plomberie"]
    assert api.post("/handy/me/favorites/", {"handyman": make_handyman("inconnu").pk}, format="json").status_code == 404
    svc = rows[0]["offers"][0]
    quick = api.post("/handy/flash/requests/", {"category": plomberie.pk, "address": "Rue 1", "commune": "Cocody", "lat": 5.36, "lng": -3.99,
                                                "matching": "direct", "target": fav.pk, "service": svc["id"]}, format="json")
    assert quick.status_code == 201 and quick.json()["target"]["id"] == fav.pk and quick.json()["amount"] == 5000
    assert api.delete(f"/handy/me/favorites/{fav.pk}/").json()["results"] == []


def test_mode_suggestion_follows_the_kind_of_mission_and_remembers_the_client_choice(make_pro, client_user, plomberie):
    make_pro("dispo")
    api = as_user(client_user)
    now = api.get(f"/handy/flash/suggest/?category={plomberie.pk}&lat=5.36&lng=-3.99").json()
    assert now["suggested"] == "auto" and now["immediate"] is True and now["remembered"] is False
    later = quote_plus((timezone.now() + timedelta(days=2)).isoformat())
    planned = api.get(f"/handy/flash/suggest/?category={plomberie.pk}&lat=5.36&lng=-3.99&when={later}").json()
    assert planned["suggested"] == "direct"
    quote = api.get(f"/handy/flash/suggest/?category={plomberie.pk}&mode=quote").json()
    assert quote["suggested"] == "auto"
    services.create_request(client_user, category=plomberie, address="Rue 1", commune="Cocody", amount=15000, lat=5.36, lng=-3.99)
    again = api.get(f"/handy/flash/suggest/?category={plomberie.pk}&lat=5.36&lng=-3.99&when={later}").json()
    assert again["remembered"] is True and again["preselected"] == "auto" and again["suggested"] == "direct"


def test_awaiting_choice_closes_after_the_window_and_relaunch_keeps_the_choice(make_pro, client_user, plomberie,
                                                                              django_capture_on_commit_callbacks):
    pro, second = make_pro("a"), make_pro("b", km=2)
    req = direct(client_user, plomberie, pro)
    with django_capture_on_commit_callbacks(execute=True):
        services.decline(req.offers.get().pk, pro)
    req.refresh_from_db()
    later = timezone.now() + timedelta(hours=DispatchConfig.get_solo().quote_window_hours + 1)
    with django_capture_on_commit_callbacks(execute=True):
        assert hybrid.close_stale_awaiting(now=later) == 1
    req.refresh_from_db()
    assert req.status == "unfulfilled"
    r = as_user(client_user).post(f"/handy/flash/requests/{req.pk}/relaunch/", {"target": second.pk}, format="json")
    assert r.status_code == 201 and r.json()["matching"] == "direct" and r.json()["target"]["id"] == second.pk
