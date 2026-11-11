"""Tratra Flash, recherche façon VTC : rayons progressifs (100 m → 200 km), accord du client au-delà de 30 km, mode Propositions
(offres de prix, contre-offres, expiration, choix explicite), désistement du pro retenu, annulation, concurrence, temps réel et
confidentialité des positions. FCM jamais réel (conftest), aucun SMS."""
import json
import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from flash import services
from flash.models import DispatchConfig, DispatchEvent, MissionOffer, MissionRequest
from flash.services import FlashError
from handy.models import Booking, Notification

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


def kinds(req):
    return list(DispatchEvent.objects.filter(request=req).order_by("id").values_list("kind", flat=True))


# ═══ Rayons progressifs ══════════════════════════════════════════════════════════════════════════════════════════════

def test_radius_grows_step_by_step_and_never_contacts_a_pro_twice(make_pro, make_request):
    cfg(wave_size=1)
    a, b = make_pro("a", km=0.05), make_pro("b", km=0.07)
    c, d = make_pro("c", km=3), make_pro("d", km=8)
    req = make_request()
    req.refresh_from_db()
    assert req.radius_m == 100 and req.eligible_count == 2 and req.next_step_at is not None
    assert offers_of(req)[0].handyman_id == a.pk                       # le plus proche d'abord, dans le premier palier
    services.expire_due(now=req.next_step_at + timedelta(seconds=1))   # palier échu : l'autre pro du même palier, pas d'extension
    req.refresh_from_db()
    assert req.radius_m == 100 and [o.handyman_id for o in offers_of(req)] == [a.pk, b.pk]
    services.expire_due(now=req.next_step_at + timedelta(seconds=1))   # personne d'autre à 100 m : 500 m et 1 km vides → 5 km
    req.refresh_from_db()
    assert req.radius_m == 5000 and offers_of(req)[-1].handyman_id == c.pk
    radius = DispatchEvent.objects.filter(request=req, kind="radius").last()
    assert radius.data == {"from_m": 100, "radius_m": 5000, "skipped": 2}
    services.expire_due(now=req.next_step_at + timedelta(seconds=1))
    req.refresh_from_db()
    assert req.radius_m == 10000 and [o.handyman_id for o in offers_of(req)] == [a.pk, b.pk, c.pk, d.pk]
    # Les propositions des premiers paliers restent valables pendant l'extension ; le premier qui accepte l'emporte.
    assert all(o.status == MissionOffer.PENDING for o in offers_of(req))
    services.accept(offers_of(req)[1].pk, b)
    req.refresh_from_db()
    assert req.status == MissionRequest.ASSIGNED and req.next_step_at is None
    assert sorted(o.status for o in offers_of(req)) == ["accepted", "withdrawn", "withdrawn", "withdrawn"]


def test_pending_offers_are_capped_and_the_search_waits_for_answers(make_pro, make_request):
    cfg(wave_size=2, max_pending_offers=2, max_waves=10)
    pros = [make_pro(f"p{i}", km=0.05 + i * 0.001) for i in range(3)]
    req = make_request()
    assert len(offers_of(req)) == 2
    req.refresh_from_db()
    services.expire_due(now=req.next_step_at + timedelta(seconds=1))
    assert len(offers_of(req)) == 2                                     # plafond atteint : personne de plus n'est sollicité
    services.decline(offers_of(req)[0].pk, pros[0])
    req.refresh_from_db()
    services.launch_wave(req.pk, now=req.next_step_at)                   # refus (après validation) : la place libérée sert aussitôt
    assert [o.handyman_id for o in offers_of(req)][-1] == pros[2].pk    # une place libérée : le suivant


def test_a_progressive_wave_never_reads_pros_outside_the_current_radius(make_pro, client_user, plomberie):
    from django.contrib.gis.geos import Point

    from flash.conftest import COCODY

    config = DispatchConfig.get_solo()
    make_pro("voisin", km=0.05)
    req = MissionRequest(client=client_user, category=plomberie, commune="Cocody", scheduled_for=timezone.now(), is_immediate=True,
                         location=Point(COCODY[1], COCODY[0], srid=4326))

    def measure():
        services.candidates(req, config, explain=True, radius_km=0.1, outside=False)   # réglages et caches spatiaux
        with CaptureQueriesContext(connection) as ctx:
            result = services.candidates(req, config, explain=True, radius_km=0.1, outside=False)
        return result, len(ctx)

    (_, _), few = measure()
    for i in range(12):
        make_pro(f"loin{i}", km=150 + i)
    (ranked, rejected), many = measure()
    assert [c.profile.user.username for c in ranked] == ["voisin"]
    assert rejected == [] and many == few      # les pros hors du palier ne sont même pas lus (préfiltre de l'index spatial)


# ═══ Au-delà de 30 km ════════════════════════════════════════════════════════════════════════════════════════════════

def test_beyond_30_km_the_client_must_agree(make_pro, make_request, client_user, django_capture_on_commit_callbacks):
    far = make_pro("loin", km=40)
    with django_capture_on_commit_callbacks(execute=True):
        req = make_request()
    req.refresh_from_db()
    assert offers_of(req) == [] and req.status == MissionRequest.SEARCHING and req.radius_m == 30000
    n = Notification.objects.get(user=client_user, notification_type="mission_choice")
    assert "Élargir" in n.title and n.data == {"kind": "flash_request", "id": req.pk}
    d = as_user(client_user).get(f"/handy/flash/requests/{req.pk}/").json()
    assert d["can_extend"] and d["search"]["phase"] == "extension"
    assert d["search"]["far"]["needs_consent"] and d["search"]["far"]["available_beyond"] == 1
    assert d["search"]["steps_m"][-1] == 30000                          # jamais au-delà sans accord
    with django_capture_on_commit_callbacks(execute=True):
        r = as_user(client_user).post(f"/handy/flash/requests/{req.pk}/extend/", {}, format="json", HTTP_IDEMPOTENCY_KEY="extend-0001")
    assert r.status_code == 200
    req.refresh_from_db()
    assert req.allow_far and req.radius_m == 50000 and [o.handyman_id for o in offers_of(req)] == [far.pk]
    assert "far_consent" in kinds(req)
    again = as_user(client_user).post(f"/handy/flash/requests/{req.pk}/extend/", {}, format="json", HTTP_IDEMPOTENCY_KEY="extend-0001")
    assert again.status_code == 200 and len(offers_of(req)) == 1


def test_without_an_answer_or_for_a_local_trade_the_search_ends_at_30_km(make_pro, make_request, make_user):
    cfg(far_consent_wait_seconds=60)
    make_pro("loin", km=40)
    req = make_request()
    services.expire_due(now=timezone.now() + timedelta(seconds=90))
    req.refresh_from_db()
    assert req.status == MissionRequest.UNFULFILLED and offers_of(req) == []
    cfg(far_trades="jardinage")                                         # métier non compatible : la question n'est même pas posée
    other = make_request(client=make_user("autre", phone="+2250700000777"))
    other.refresh_from_db()
    assert other.status == MissionRequest.UNFULFILLED and "consent_asked" not in kinds(other)
    with pytest.raises(FlashError) as e:
        services.allow_far(other.pk, other.client)
    assert e.value.code == "request_closed"


# ═══ Mode Propositions : réponse, proposition, contre-offre, sélection, confirmation ══════════════════════════════════

def test_counter_offer_then_confirmation_at_the_countered_price(make_pro, make_request, client_user, django_capture_on_commit_callbacks):
    cfg(wave_size=2, max_quotes=2)
    a, b = make_pro("a", km=0.05), make_pro("b", km=0.06)
    req = make_request(mode="quote")
    oa, ob = offers_of(req)
    with django_capture_on_commit_callbacks(execute=True):
        services.send_quote(oa.pk, a, 30000)
        services.send_quote(ob.pk, b, 28000)
    req.refresh_from_db()
    assert req.status == MissionRequest.QUOTING
    client = as_user(client_user)
    url = f"/handy/flash/requests/{req.pk}/quotes/{oa.pk}/counter/"
    assert client.post(url, {"amount": 30000}, format="json").json()["code"] == "counter_not_lower"
    with django_capture_on_commit_callbacks(execute=True):
        r = client.post(url, {"amount": 25000}, format="json", HTTP_IDEMPOTENCY_KEY="counter-0001")
    assert r.status_code == 200
    row = next(q for q in r.json()["quotes"] if q["offer"] == oa.pk)
    assert row["status"] == "countered" and row["counter_amount"] == 25000 and row["can_choose"] and not row["can_counter"]
    assert client.post(url, {"amount": 25000}, format="json", HTTP_IDEMPOTENCY_KEY="counter-0001").status_code == 200   # rejeu
    n = Notification.objects.get(user=a, notification_type="mission_choice")
    assert n.data == {"kind": "flash_offer", "id": oa.pk} and "25\u202f000 FCFA" in n.message
    pro_view = as_user(a).get(f"/handy/flash/offers/{oa.pk}/").json()
    assert pro_view["counter"]["amount"] == 25000 and pro_view["counter"]["seconds_left"] > 0
    # Le pro garde sa proposition : elle reste choisissable ; le client peut contre-proposer une seconde fois.
    with django_capture_on_commit_callbacks(execute=True):
        assert as_user(a).post(f"/handy/flash/offers/{oa.pk}/counter/decline/", {}, format="json").status_code == 200
    oa.refresh_from_db()
    assert oa.status == MissionOffer.QUOTED and oa.counters == 1
    assert Notification.objects.filter(user=client_user, title="Contre-offre non retenue").exists()
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(url, {"amount": 26000}, format="json").status_code == 200
        r = as_user(a).post(f"/handy/flash/offers/{oa.pk}/counter/accept/", {}, format="json", HTTP_IDEMPOTENCY_KEY="counter-ok-0001")
    assert r.status_code == 200 and r.json()["status"] == "accepted" and r.json()["agreed_label"] == "26\u202f000 FCFA"
    d = client.get(f"/handy/flash/requests/{req.pk}/").json()
    assert d["agreed_label"] == "26\u202f000 FCFA" and d["search"]["counts"]["proposals"] == 2   # prix convenu ; propositions reçues
    assert d["search"]["counts"]["open_proposals"] == 0 and d["search"]["phase"] == "confirmed"
    req.refresh_from_db()
    assert req.status == MissionRequest.ASSIGNED and req.booking.total_price == 26000 and req.assigned_to == a
    assert MissionOffer.objects.get(pk=ob.pk).status == MissionOffer.WITHDRAWN
    k = kinds(req)
    assert k.count("quoted") == 2 and k.count("counter") == 2 and "counter_no" in k and "counter_ok" in k and k[-1] == "assigned"
    assert "quote_chosen" not in k          # la contre-offre acceptée confirme : le client n'a sélectionné aucune proposition
    assert as_user(a).post(f"/handy/flash/offers/{oa.pk}/counter/accept/", {}, format="json").status_code == 200   # rejeu
    assert Booking.objects.filter(client=client_user).count() == 1


def test_counter_limit_selection_and_confirmation(make_pro, make_request, client_user):
    cfg(wave_size=1, max_quotes=1, max_counter_offers=1)
    a = make_pro("a", km=0.05)
    req = make_request(mode="quote")
    o = offers_of(req)[0]
    services.send_quote(o.pk, a, 20000)
    services.launch_wave(req.pk)
    services.counter_offer(req.pk, client_user, o.pk, 18000)
    services.answer_counter(o.pk, a, False)
    with pytest.raises(FlashError) as e:
        services.counter_offer(req.pk, client_user, o.pk, 17000)
    assert e.value.code == "counter_limit"
    services.choose_quote(req.pk, client_user, o.pk)                      # sélection explicite, puis confirmation
    req.refresh_from_db()
    assert req.status == MissionRequest.ASSIGNED and req.booking.total_price == 20000
    assert kinds(req)[-2:] == ["quote_chosen", "assigned"]


def test_counter_expiry_keeps_the_proposal_and_lapsed_proposals_close_the_choice(make_pro, make_request, client_user):
    cfg(wave_size=1, max_quotes=1, counter_timeout_seconds=60, proposal_ttl_minutes=10)
    a = make_pro("a", km=0.05)
    req = make_request(mode="quote")
    o = offers_of(req)[0]
    now = timezone.now()
    services.send_quote(o.pk, a, 20000, now=now)
    services.launch_wave(req.pk)
    services.counter_offer(req.pk, client_user, o.pk, 18000, now=now)
    services.expire_due(now=now + timedelta(minutes=2))
    o.refresh_from_db()
    assert o.status == MissionOffer.QUOTED and o.counter_amount == 18000      # la proposition initiale reste valable
    with pytest.raises(FlashError) as e:
        services.answer_counter(o.pk, a, True, now=now + timedelta(minutes=2))
    assert e.value.code == "counter_closed"
    services.expire_due(now=now + timedelta(minutes=11))
    o.refresh_from_db()
    req.refresh_from_db()
    assert o.status == MissionOffer.LAPSED and req.status == MissionRequest.UNFULFILLED
    with pytest.raises(FlashError):
        services.choose_quote(req.pk, client_user, o.pk)


@pytest.mark.django_db(transaction=True)
def test_counter_acceptance_and_another_choice_racing_assign_exactly_once(make_pro, make_request, client_user):
    cfg(wave_size=2, max_quotes=2)
    a, b = make_pro("a", km=0.05), make_pro("b", km=0.06)
    req = make_request(mode="quote")
    oa, ob = offers_of(req)
    services.send_quote(oa.pk, a, 30000)
    services.send_quote(ob.pk, b, 28000)
    services.counter_offer(req.pk, client_user, oa.pk, 25000)
    barrier, results = threading.Barrier(2), []

    def run(fn):
        try:
            barrier.wait()
            fn()
            results.append("ok")
        except FlashError as e:
            results.append(e.code)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(lambda: services.answer_counter(oa.pk, a, True),)),
               threading.Thread(target=run, args=(lambda: services.choose_quote(req.pk, client_user, ob.pk),))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1, results
    assert MissionOffer.objects.filter(request=req, status="accepted").count() == 1
    assert Booking.objects.filter(client=client_user).count() == 1


# ═══ Cycle de vie ════════════════════════════════════════════════════════════════════════════════════════════════════

def test_selected_pro_withdraws_and_the_same_request_resumes_without_duplicate(make_pro, make_request, client_user,
                                                                               django_capture_on_commit_callbacks):
    cfg(wave_size=1)
    a, b = make_pro("a", km=0.05), make_pro("b", km=3)
    req = make_request()
    oa = offers_of(req)[0]
    services.accept(oa.pk, a)
    req.refresh_from_db()
    booking = req.booking
    with django_capture_on_commit_callbacks(execute=True):
        booking.transition_to("cancelled", actor=a)
    req.refresh_from_db()
    assert req.status == MissionRequest.SEARCHING and req.booking is None and req.assigned_to is None
    assert MissionOffer.objects.get(pk=oa.pk).status == MissionOffer.RESIGNED
    assert MissionRequest.objects.count() == 1
    assert [o.handyman_id for o in offers_of(req)] == [a.pk, b.pk]          # b sollicité, a jamais resollicité
    assert Notification.objects.filter(user=client_user, title="Recherche reprise").count() == 1
    d = as_user(client_user).get(f"/handy/flash/requests/{req.pk}/").json()
    assert d["reopened"]["pro"] == "A" and d["status"] == "searching"       # visible sur l'écran de suivi
    booking.save()                                                         # nouvel enregistrement de la réservation annulée : sans effet
    assert len(offers_of(req)) == 2 and kinds(req).count("reopened") == 1
    services.accept(offers_of(req)[1].pk, b)
    req.refresh_from_db()
    assert req.status == MissionRequest.ASSIGNED and req.booking_id != booking.pk and req.assigned_to == b
    from trust.metrics import commitment
    from trust.models import TrustConfig

    assert commitment(a.handyman_profile, TrustConfig.get_solo())["taken"] == 1   # l'engagement pris reste compté
    assert as_user(client_user).get(f"/handy/flash/requests/{req.pk}/").json()["reopened"] is None          # de nouveau attribuée
    # b se désiste à son tour et plus personne n'est disponible : la demande se clôt, et l'écran dit encore pourquoi.
    with django_capture_on_commit_callbacks(execute=True):
        req.booking.transition_to("cancelled", actor=b)
    d = as_user(client_user).get(f"/handy/flash/requests/{req.pk}/").json()
    assert d["status"] == "unfulfilled" and d["reopened"]["pro"] == "B"


def test_client_cancel_stops_dispatch_offers_and_timers(make_pro, make_request, client_user, django_capture_on_commit_callbacks):
    cfg(wave_size=1)
    a, b = make_pro("a", km=0.05), make_pro("b", km=3)
    req = make_request()
    with django_capture_on_commit_callbacks(execute=True):
        r = as_user(client_user).post(f"/handy/flash/requests/{req.pk}/cancel/", {}, format="json")
    assert r.status_code == 200 and r.json()["search"]["phase"] == "cancelled"
    req.refresh_from_db()
    assert req.status == MissionRequest.CANCELLED and req.next_step_at is None
    services.expire_due(now=timezone.now() + timedelta(minutes=10))
    assert [o.status for o in offers_of(req)] == [MissionOffer.WITHDRAWN]  # b n'est jamais sollicité
    with pytest.raises(FlashError) as e:
        services.accept(offers_of(req)[0].pk, a)
    assert e.value.code == "request_closed"


# ═══ Temps réel, reprise, confidentialité ════════════════════════════════════════════════════════════════════════════

def test_live_updates_carry_state_and_counters_but_never_an_exact_pro_position(make_pro, make_request, client_user, monkeypatch,
                                                                       django_capture_on_commit_callbacks):
    sent = []
    monkeypatch.setattr("handy.inbox.push", lambda users, event: sent.append((sorted(set(users)), event)))
    cfg(wave_size=1, max_quotes=3)
    a, b = make_pro("a", km=0.05), make_pro("b", km=3)
    with django_capture_on_commit_callbacks(execute=True):
        req = make_request(mode="quote")
    with django_capture_on_commit_callbacks(execute=True):
        services.decline(offers_of(req)[0].pk, a)
    with django_capture_on_commit_callbacks(execute=True):
        services.send_quote(offers_of(req)[1].pk, b, 21000)
    live = [e for users, e in sent if e["type"] == "flash_request"]
    assert live and all(users == [client_user.pk] for users, e in sent if e["type"] == "flash_request")
    seqs = [e["search"]["seq"] for e in live]
    assert seqs == sorted(seqs)
    assert any(e["search"]["radius_m"] == 5000 and e["search"]["counts"]["contacted"] == 2 for e in live)   # refus : palier suivant
    last = live[-1]["search"]
    # Plus personne jusqu'à 30 km (et personne au-delà) : le client choisit parmi les propositions reçues.
    assert last["radius_m"] == 30000 and last["phase"] == "selection" and live[-1]["status"] == "quoting"
    assert {k: last["counts"][k] for k in ("contacted", "responses", "proposals", "declined")} == \
        {"contacted": 2, "responses": 2, "proposals": 1, "declined": 1}
    rest = as_user(client_user).get(f"/handy/flash/requests/{req.pk}/").json()     # reprise : même état par l'API
    assert rest["search"]["seq"] >= last["seq"] and rest["search"]["counts"]["proposals"] == 1
    assert rest["center"] == {"lat": pytest.approx(5.36), "lng": pytest.approx(-3.99)}
    assert rest["quotes"][0]["distance_km"] == 3.0                             # arrondie à 100 m
    blob = json.dumps([sent, rest], default=str)
    for pro in (a, b):
        loc = pro.handyman_profile.location
        assert f"{loc.y:.5f}" not in blob and f"{loc.y:.4f}" not in blob


def test_the_map_shows_contacted_pros_wave_by_wave_approximately_and_without_identity(make_pro, make_request, client_user, plomberie,
                                                                                      django_capture_on_commit_callbacks):
    from flash import realtime

    cfg(wave_size=1)
    a, b = make_pro("awa", km=0.05), make_pro("bintou", km=3)
    type(a).objects.filter(pk=a.pk).update(gender="F")                 # déclaré par la professionnelle ; `b` n'a rien indiqué
    req = make_request()
    first = offers_of(req)[0]
    pros = realtime.search_payload(req)["pros"]
    assert [(p["id"], p["state"], p["gender"]) for p in pros] == [(first.pk, "contacted", "F")]     # seule la 1re vague est visible
    assert set(pros[0]) == {"id", "lat", "lng", "gender", "state"}                                  # ni nom, ni photo, ni compte
    loc = a.handyman_profile.location
    assert abs(pros[0]["lat"] - loc.y) < 0.0012 and abs(pros[0]["lng"] - loc.x) < 0.0012             # à ≈ 100 m près…
    assert (pros[0]["lat"], pros[0]["lng"]) != (loc.y, loc.x)                                       # … jamais la position exacte
    assert realtime.search_payload(req)["pros"] == pros                                             # stable d'un message à l'autre

    with django_capture_on_commit_callbacks(execute=True):
        services.decline(first.pk, a)                                  # refus : palier suivant, le 2e professionnel apparaît
    second = offers_of(req)[1]
    rest = as_user(client_user).get(f"/handy/flash/requests/{req.pk}/").json()["search"]["pros"]
    assert [(p["id"], p["state"], p["gender"]) for p in rest] == [(first.pk, "declined", "F"), (second.pk, "contacted", None)]

    services.accept(second.pk, b)                                      # mission attribuée : seul le professionnel retenu reste
    req.refresh_from_db()
    assert [(p["id"], p["state"]) for p in realtime.live_payload(req)["search"]["pros"]] == [(second.pk, "selected")]

    other = make_request(client=None)                                   # demande annulée : plus aucun repère
    services.cancel_request(other.pk, client_user)
    other.refresh_from_db()
    assert realtime.search_payload(other)["pros"] == []
    commune = services.create_request(client_user, category=plomberie, address="Rue 12", commune="Cocody", mode="firm", amount=15000)
    assert realtime.search_payload(commune)["pros"] == []              # demande par commune (sans lieu précis) : pas de carte


def test_gender_is_optional_and_declared_by_the_member(make_user):
    user = make_user("genre", first_name="Awa", phone="+2250700000177")
    api = as_user(user)
    assert api.get(f"/handy/users/{user.pk}/").json()["gender"] == ""
    assert api.patch(f"/handy/users/{user.pk}/", {"gender": "F"}, format="json").json()["gender"] == "F"
    assert api.patch(f"/handy/users/{user.pk}/", {"gender": "X"}, format="json").status_code == 400
    assert api.patch(f"/handy/users/{user.pk}/", {"gender": ""}, format="json").json()["gender"] == ""


def test_existing_requests_without_position_keep_the_commune_search(make_pro, client_user, plomberie):
    from handy.models import HandymanProfile

    pro = make_pro("commune", km=12)
    HandymanProfile.objects.filter(user=pro).update(commune="Cocody")
    req = services.create_request(client_user, category=plomberie, address="Rue 1", commune="Cocody", amount=15000)
    req.refresh_from_db()
    assert req.radius_m == 0 and [o.handyman_id for o in offers_of(req)] == [pro.pk]
    d = as_user(client_user).get(f"/handy/flash/requests/{req.pk}/").json()
    assert d["search"]["progressive"] is False and d["search"]["radius_label"] == "Votre commune" and d["center"] is None


def test_each_radius_step_is_served_by_the_spatial_index(make_pro, client_user, plomberie):
    """Plan PostgreSQL du préfiltre de zone d'un palier : servi par l'index GiST des positions (le parcours séquentiel est désactivé
    pour la mesure, sinon PostgreSQL le préfère sur une base de test minuscule) — jamais un calcul de distance sur chaque ligne."""
    from django.contrib.gis.geos import Point

    from flash.conftest import COCODY
    from handy import proximity
    from handy.models import HandymanProfile

    make_pro("voisin", km=0.05)
    point = Point(COCODY[1], COCODY[0], srid=4326)
    for km in DispatchConfig.get_solo().steps_km():
        qs = HandymanProfile.objects.filter(proximity.near("location", point, km)).values("pk")
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_seqscan = off")
            plan = qs.explain()
        assert "Index" in plan and "location" in plan, plan
