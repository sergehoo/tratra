"""Tratra Flash — fiabilité et concurrence (phase 3) : numéro de synchronisation, acceptations simultanées (2, 10, 50), propositions et
contre-offres concurrentes, expiration pendant l'acceptation, désistement et reprise, tâches rejouées ou perdues, temps réel coupé.
Les tests « simultanés » lancent de vrais fils sur de vraies transactions PostgreSQL. FCM jamais réel (conftest), aucun SMS."""
import threading
from collections import Counter
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from flash import realtime, services, tasks
from flash.conftest import COCODY
from flash.models import DispatchConfig, DispatchEvent, MissionOffer, MissionRequest
from flash.services import FlashError
from handy.models import Booking, Invoice, Notification, Payment

pytestmark = pytest.mark.django_db
real_db = pytest.mark.django_db(transaction=True)


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


def visible(req):
    return DispatchEvent.objects.filter(request=req).exclude(kind__in=realtime.QUIET).count()


def race(*calls):
    """Chaque appel dans son fil, tous libérés au même instant. Par appel : "ok", le code métier (`FlashError`), ou "!Erreur…"
    (interblocage, erreur d'intégrité non traitée : un défaut) ; `None` si le fil ne rend pas la main."""
    barrier, out = threading.Barrier(len(calls)), [None] * len(calls)

    def run(i, fn):
        try:
            barrier.wait(timeout=60)
            fn()
            out[i] = "ok"
        except FlashError as e:
            out[i] = e.code
        except Exception as e:  # noqa: BLE001 — tout ce qui n'est pas une réponse métier est un défaut à constater
            out[i] = f"!{type(e).__name__}: {e}"[:160]
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(calls)]
    [t.start() for t in threads]
    [t.join(120) for t in threads]
    return out


def crashes(results):
    return [r for r in results if r is None or r.startswith("!")]


def raw_request(client, category, *, mode="firm", amount=15000):
    """Demande posée directement (sans vague) : pour simuler deux alertes simultanées chez un même professionnel."""
    return MissionRequest.objects.create(client=client, category=category, address="Rue B", commune="Cocody", mode=mode,
                                         location=f"SRID=4326;POINT({COCODY[1]} {COCODY[0]})", scheduled_for=timezone.now(),
                                         is_immediate=True, amount=amount if mode == "firm" else None, wave=1)


def raw_offer(req, pro, **fields):
    fields.setdefault("expires_at", timezone.now() + timedelta(minutes=5))
    return MissionOffer.objects.create(request=req, handyman=pro, wave=1, rank=1, score=50, **fields)


def quoted(req, pro, amount, **fields):
    now = timezone.now()
    fields.setdefault("proposal_expires_at", now + timedelta(minutes=30))
    fields.setdefault("status", MissionOffer.QUOTED)
    return raw_offer(req, pro, quote_amount=amount, responded_at=now, response_seconds=1, **fields)


# ═══ 1. Synchronisation temps réel ═══════════════════════════════════════════════════════════════════════════════════

def test_seq_counts_visible_events_and_each_transaction_sends_one_message(make_pro, make_request, client_user, monkeypatch,
                                                                         django_capture_on_commit_callbacks):
    sent = []
    monkeypatch.setattr("handy.inbox.push", lambda users, event: sent.append(event))
    cfg(wave_size=2)
    a, b = make_pro("a", km=0.05), make_pro("b", km=0.06)
    with django_capture_on_commit_callbacks(execute=True):
        req = make_request()
    oa, ob = offers_of(req)
    before = len(sent)
    with django_capture_on_commit_callbacks(execute=True):
        services.mark_seen(oa.pk, a)                       # évènement discret : ni numéro, ni message
    assert len(sent) == before and MissionRequest.objects.get(pk=req.pk).seq == visible(req)
    with django_capture_on_commit_callbacks(execute=True):
        services.decline(ob.pk, b)
    before = len([e for e in sent if e["type"] == "flash_request"])
    with django_capture_on_commit_callbacks(execute=True):
        services.accept(oa.pk, a)                          # deux évènements (accepté, attribué) : UN message
    req.refresh_from_db()
    live = [e for e in sent if e["type"] == "flash_request"]
    seqs = [e["search"]["seq"] for e in live]
    assert len(live) == before + 1 and live[-1]["status"] == "assigned"
    assert seqs == sorted(set(seqs)) and seqs[-1] == req.seq == visible(req)        # strictement croissant, sans doublon
    rest = as_user(client_user).get(f"/handy/flash/requests/{req.pk}/").json()        # reprise : l'état complet, au même numéro
    assert rest["search"]["seq"] == req.seq and rest["status"] == "assigned" and rest["search"]["phase"] == "confirmed"
    realtime.request_changed(req.pk)                                                 # rediffusion du même état : rien ne part
    assert len([e for e in sent if e["type"] == "flash_request"]) == len(live)


@real_db
def test_simultaneous_events_get_ordered_numbers_and_no_message_is_older_than_its_number(make_pro, make_request, monkeypatch):
    sent = []
    monkeypatch.setattr("handy.inbox.push", lambda users, event: sent.append(event))
    n = 8
    cfg(wave_size=n, max_pending_offers=n)
    pros = [make_pro(f"p{i}", km=0.05) for i in range(n)]
    req = make_request()
    base = MissionRequest.objects.get(pk=req.pk).seq
    offers = {o.handyman_id: o.pk for o in offers_of(req)}
    assert len(offers) == n and base == visible(req)
    results = race(*[lambda p=p: services.decline(offers[p.pk], p) for p in pros])
    assert results == ["ok"] * n
    req.refresh_from_db()
    assert req.seq == visible(req)                                     # une unité par évènement visible : ni trou, ni doublon
    live = [e["search"] for e in sent if e["type"] == "flash_request" and e["id"] == req.pk]
    assert max(s["seq"] for s in live) == req.seq                      # le dernier état est bien parti
    for s in live:                                                     # un message numéroté k contient AU MOINS les k premiers refus
        if base < s["seq"] <= base + n:
            assert s["counts"]["declined"] >= s["seq"] - base


def test_a_cancelled_or_finished_request_is_never_reactivated(make_pro, make_request, client_user, make_user):
    cfg(wave_size=1, max_active_requests_per_client=5)
    a, b = make_pro("a", km=0.05), make_pro("b", km=3)
    late = timezone.now() + timedelta(hours=3)

    def replay(req):
        """Tout ce qui peut encore arriver après coup : tâches en retard ou rejouées, passage périodique."""
        for _ in range(2):
            services.launch_wave(req.pk)
            tasks.step_due(req.pk)
            tasks.wave_timeout(req.pk, 1)
            tasks.tick()
            services.expire_due(now=late)
            services.expire_due(now=late, request_id=req.pk)

    # Annulée : aucune tâche, aucun geste tardif ne la rouvre.
    req = make_request(mode="quote")
    oa = offers_of(req)[0]
    services.send_quote(oa.pk, a, 20000)
    services.cancel_request(req.pk, client_user)
    frozen = MissionRequest.objects.get(pk=req.pk)
    replay(req)
    for call, code in ((lambda: services.choose_quote(req.pk, client_user, oa.pk), "request_closed"),
                       (lambda: services.counter_offer(req.pk, client_user, oa.pk, 15000), "request_closed"),
                       (lambda: services.allow_far(req.pk, client_user), "request_closed"),
                       (lambda: services.send_quote(oa.pk, a, 21000), "request_closed"),
                       (lambda: services.answer_counter(oa.pk, a, True), "counter_closed")):
        with pytest.raises(FlashError) as e:
            call()
        assert e.value.code == code
    req.refresh_from_db()
    assert (req.status, req.seq, req.version) == (MissionRequest.CANCELLED, frozen.seq, frozen.version)
    assert [o.status for o in offers_of(req)] == [MissionOffer.WITHDRAWN] and Booking.objects.count() == 0     # b jamais sollicité
    assert as_user(client_user).get(f"/handy/flash/requests/{req.pk}/").json()["search"]["phase"] == "cancelled"

    # Sans professionnel : close, et elle le reste.
    lonely = make_request(client=make_user("seul"), category=None)
    MissionOffer.objects.filter(request=lonely).update(expires_at=timezone.now() - timedelta(minutes=5))
    services.expire_due(request_id=lonely.pk)
    lonely.refresh_from_db()
    while lonely.status == MissionRequest.SEARCHING:                     # paliers suivants : plus personne (a et b déjà sollicités)
        MissionOffer.objects.filter(request=lonely, status="pending").update(expires_at=timezone.now() - timedelta(minutes=5))
        services.expire_due(request_id=lonely.pk)
        lonely.refresh_from_db()
    assert lonely.status == MissionRequest.UNFULFILLED
    frozen = (lonely.seq, lonely.version, len(offers_of(lonely)))
    replay(lonely)
    lonely.refresh_from_db()
    assert (lonely.status, lonely.seq, lonely.version, len(offers_of(lonely))) == (MissionRequest.UNFULFILLED, *frozen)

    # Attribuée : terminée pour la recherche ; ni annulation ici, ni nouvelle vague.
    done = make_request(client=make_user("servi"))
    first = offers_of(done)[0]
    services.accept(first.pk, first.handyman)
    frozen = MissionRequest.objects.get(pk=done.pk)
    replay(done)
    with pytest.raises(FlashError) as e:
        services.cancel_request(done.pk, done.client)
    assert e.value.code == "request_closed"
    done.refresh_from_db()
    assert (done.status, done.seq, done.booking_id) == (MissionRequest.ASSIGNED, frozen.seq, frozen.booking_id)
    assert Booking.objects.count() == 1


# ═══ 2. Acceptations simultanées ═════════════════════════════════════════════════════════════════════════════════════

@real_db
@pytest.mark.parametrize("n", [2, 10, 50])
def test_n_simultaneous_acceptances_assign_once_and_every_loser_is_told(n, make_pro, make_request):
    cfg(wave_size=n, max_pending_offers=n, max_contacts=n + 5)
    pros = [make_pro(f"r{i}", km=0.05) for i in range(n)]
    req = make_request()
    offers = {o.handyman_id: o.pk for o in offers_of(req)}
    assert len(offers) == n
    results = race(*[lambda p=p: services.accept(offers[p.pk], p) for p in pros])
    assert crashes(results) == [] and Counter(results) == {"ok": 1, "already_assigned": n - 1}
    winner = pros[results.index("ok")]
    req.refresh_from_db()
    assert req.status == MissionRequest.ASSIGNED and req.assigned_to_id == winner.pk
    assert Counter(o.status for o in offers_of(req)) == {"accepted": 1, "withdrawn": n - 1}
    booking = Booking.objects.get()                                    # un seul engagement
    assert (booking.handyman_id, booking.total_price, booking.status) == (winner.pk, 15000, "confirmed")
    assert req.booking_id == booking.pk and kinds(req).count("assigned") == 1 and req.seq == visible(req)
    assert Payment.objects.count() <= 1 and Invoice.objects.count() <= 1            # aucune double facturation
    loser = next(p for p in pros if p.pk != winner.pk)                 # état explicite du perdant, et rejeu refusé proprement
    seen = as_user(loser).get(f"/handy/flash/offers/{offers[loser.pk]}/").json()
    assert (seen["status"], seen["request_status"], seen["seconds_left"]) == ("withdrawn", "assigned", 0) and "address" not in seen
    again = as_user(loser).post(f"/handy/flash/offers/{offers[loser.pk]}/accept/", {}, format="json")
    assert again.status_code == 409 and again.json()["code"] == "already_assigned"
    assert as_user(winner).post(f"/handy/flash/offers/{offers[winner.pk]}/accept/", {}, format="json").status_code == 200   # rejeu
    assert Booking.objects.count() == 1


@real_db
def test_acceptances_refusals_expiry_and_cancellation_together_never_deadlock(make_pro, make_request, client_user):
    n = 12
    cfg(wave_size=n, max_pending_offers=n)
    pros = [make_pro(f"m{i}", km=0.05) for i in range(n)]
    req = make_request()
    offers = {o.handyman_id: o.pk for o in offers_of(req)}
    late = timezone.now() + timedelta(seconds=1)
    calls = [(lambda p=p: services.accept(offers[p.pk], p)) if i % 2 else (lambda p=p: services.decline(offers[p.pk], p, "busy"))
             for i, p in enumerate(pros)]
    calls += [lambda: services.expire_due(now=late), lambda: tasks.wave_timeout(req.pk, 1), lambda: services.launch_wave(req.pk),
              lambda: services.cancel_request(req.pk, client_user)]
    results = race(*calls)
    assert crashes(results) == []
    assert set(results) <= {"ok", "already_assigned", "request_closed", "offer_closed"}
    req.refresh_from_db()
    assert req.status in (MissionRequest.ASSIGNED, MissionRequest.CANCELLED) and req.seq == visible(req)
    accepted = MissionOffer.objects.filter(request=req, status="accepted").count()
    assert accepted == Booking.objects.count() == (1 if req.status == MissionRequest.ASSIGNED else 0)
    assert not MissionOffer.objects.filter(request=req, status="pending").exists()


@real_db
def test_expiry_during_acceptance_has_exactly_one_outcome(make_pro, make_request):
    n = 6
    cfg(wave_size=n, max_pending_offers=n)
    pros = [make_pro(f"e{i}", km=0.05) for i in range(n)]
    req = make_request()
    offers = offers_of(req)
    edge = max(o.expires_at for o in offers)
    by_pro = {o.handyman_id: o.pk for o in offers}
    # Les pros appuient dans la seconde qui suit l'échéance (tolérée) ; au même instant le compte à rebours et le passage périodique
    # considèrent la vague échue.
    calls = [lambda p=p: services.accept(by_pro[p.pk], p, now=edge + timedelta(seconds=1)) for p in pros]
    calls += [lambda: services.expire_due(now=edge + timedelta(seconds=20)),
              lambda: services.expire_due(now=edge + timedelta(seconds=20), request_id=req.pk)]
    results = race(*calls)
    assert crashes(results) == [] and set(results) <= {"ok", "already_assigned", "offer_expired"}
    req.refresh_from_db()
    statuses = Counter(o.status for o in offers_of(req) if o.wave == 1)
    if req.status == MissionRequest.ASSIGNED:                           # un pro a gagné : les autres sont retirés ou expirés, jamais deux
        assert statuses["accepted"] == 1 and Booking.objects.count() == 1 and results.count("ok") == 3   # + les deux passages
    else:                                                               # l'expiration a gagné : personne n'est engagé
        assert statuses == {"expired": n} and Booking.objects.count() == 0 and results.count("ok") == 2
    assert kinds(req).count("expired") == statuses["expired"]           # deux passages simultanés : chaque expiration consignée une fois
    # Trop tard, clairement : au-delà de la tolérance, l'acceptation est refusée avec un motif.
    late = MissionOffer.objects.filter(request=req, status="expired").first()
    if late is not None:
        with pytest.raises(FlashError) as e:
            services.accept(late.pk, late.handyman, now=edge + timedelta(seconds=30))
        assert e.value.code in ("offer_expired", "already_assigned")


@real_db
def test_a_pro_chosen_by_one_client_while_accepting_another_mission_is_engaged_once(make_pro, make_user, plomberie):
    pairs = []
    for i in range(12):
        pro = make_pro(f"duo{i}", km=0.05)
        chooser = make_user(f"choix{i}")
        asked = raw_request(chooser, plomberie, mode="quote")
        proposal = quoted(asked, pro, 20000)
        firm = raw_request(make_user(f"ferme{i}"), plomberie)
        pending = raw_offer(firm, pro)
        pairs.append((pro, chooser, asked, proposal, firm, pending))
    calls = []
    for pro, chooser, asked, proposal, firm, pending in pairs:
        calls.append(lambda c=chooser, r=asked, o=proposal: services.choose_quote(r.pk, c, o.pk))
        calls.append(lambda p=pro, o=pending: services.accept(o.pk, p))
    results = race(*calls)
    assert crashes(results) == []
    for i, (pro, *_rest) in enumerate(pairs):
        assert sorted(results[2 * i: 2 * i + 2]) == ["ok", "schedule_conflict"]
        assert Booking.objects.filter(handyman=pro, status="confirmed").count() == 1
    assert Booking.objects.count() == len(pairs)


@real_db
def test_requests_created_at_the_same_instant_never_alert_the_same_pro_twice(make_pro, make_user, plomberie):
    cfg(wave_size=3)
    pros = [make_pro(f"z{i}", km=0.05) for i in range(12)]
    clients = [make_user(f"simul{i}") for i in range(8)]
    results = race(*[lambda c=c: services.create_request(c, category=plomberie, address="Rue des Jardins", commune="Cocody", mode="firm",
                                                         amount=15000, lat=COCODY[0], lng=COCODY[1]) for c in clients])
    assert results == ["ok"] * len(clients) and MissionRequest.objects.count() == len(clients)
    alerts = Counter(MissionOffer.objects.filter(status="pending").values_list("handyman_id", flat=True))
    assert alerts and max(alerts.values()) == 1                         # jamais deux alertes en attente chez le même professionnel
    assert set(alerts) <= {p.pk for p in pros}


# ═══ 3. Propositions et contre-offres ════════════════════════════════════════════════════════════════════════════════

@real_db
def test_simultaneous_proposals_are_all_kept_and_exactly_one_is_finally_selected(make_pro, make_request, client_user):
    n = 8
    cfg(wave_size=n, max_pending_offers=n, max_quotes=n)
    pros = [make_pro(f"q{i}", km=0.05) for i in range(n)]
    req = make_request(mode="quote")
    offers = {o.handyman_id: o.pk for o in offers_of(req)}
    results = race(*[lambda i=i, p=p: services.send_quote(offers[p.pk], p, 20000 + 1000 * i) for i, p in enumerate(pros)])
    assert results == ["ok"] * n
    req.refresh_from_db()
    assert req.status == MissionRequest.QUOTING and Counter(o.status for o in offers_of(req)) == {"quoted": n}   # plusieurs offres admises
    assert as_user(client_user).get(f"/handy/flash/requests/{req.pk}/").json()["search"]["counts"]["proposals"] == n
    # Le client contre-propose à trois pros ; ils acceptent au moment même où il choisit trois autres propositions (deux appareils).
    for i in range(3):
        services.counter_offer(req.pk, client_user, offers[pros[i].pk], 15000 + 1000 * i)
    calls = [lambda p=p: services.answer_counter(offers[p.pk], p, True) for p in pros[:3]]
    calls += [lambda p=p: services.choose_quote(req.pk, client_user, offers[p.pk]) for p in pros[3:6]]
    results = race(*calls)
    assert crashes(results) == [] and results.count("ok") == 1
    assert set(results) <= {"ok", "already_assigned", "request_closed", "quote_unavailable", "counter_closed"}
    won = results.index("ok")
    req.refresh_from_db()
    booking = Booking.objects.get()
    assert req.status == MissionRequest.ASSIGNED and req.assigned_to_id == pros[won].pk == booking.handyman_id
    # Prix final : la dernière proposition acceptée — la contre-offre si le pro l'a acceptée, sinon la proposition choisie.
    assert booking.total_price == (15000 + 1000 * won if won < 3 else 20000 + 1000 * won)
    assert Counter(o.status for o in offers_of(req)) == {"accepted": 1, "withdrawn": n - 1}
    assert kinds(req).count("assigned") == 1 and Payment.objects.count() <= 1 and Invoice.objects.count() <= 1
    # Acceptations tardives : refusées avec un motif, sans effet.
    loser = pros[(won + 1) % 3]
    with pytest.raises(FlashError) as e:
        services.answer_counter(offers[loser.pk], loser, True)
    assert e.value.code == "counter_closed"
    with pytest.raises(FlashError) as e:
        services.choose_quote(req.pk, client_user, offers[pros[7].pk])
    assert e.value.code == "request_closed"
    assert Booking.objects.count() == 1


def test_final_price_is_the_last_accepted_proposal_and_late_answers_are_refused(make_pro, make_request, client_user):
    cfg(wave_size=2, max_quotes=2)
    a, b = make_pro("a", km=0.05), make_pro("b", km=0.06)
    req = make_request(mode="quote")
    oa, ob = offers_of(req)
    services.send_quote(oa.pk, a, 30000)
    services.send_quote(ob.pk, b, 28000)
    services.counter_offer(req.pk, client_user, oa.pk, 22000)
    oa.refresh_from_db()
    gone = oa.counter_expires_at + timedelta(seconds=30)
    with pytest.raises(FlashError) as e:                                 # réponse du pro après l'échéance de la contre-offre
        services.answer_counter(oa.pk, a, True, now=gone)
    assert e.value.code == "counter_expired"
    assert services.expire_due(now=gone, request_id=req.pk)["counters_expired"] == 1
    assert services.expire_due(now=gone)["counters_expired"] == 0        # rejeu : rien de plus
    oa.refresh_from_db()
    assert oa.status == MissionOffer.QUOTED and kinds(req).count("counter_no") == 1
    with pytest.raises(FlashError) as e:                                 # la contre-offre expirée n'engage plus personne
        services.answer_counter(oa.pk, a, True, now=gone)
    assert e.value.code == "counter_closed"
    ob.refresh_from_db()
    with pytest.raises(FlashError) as e:                                 # proposition échue : choix refusé
        services.choose_quote(req.pk, client_user, ob.pk, now=ob.proposal_expires_at + timedelta(minutes=1))
    assert e.value.code == "proposal_lapsed"
    services.choose_quote(req.pk, client_user, oa.pk, now=gone)          # proposition initiale, toujours valable
    req.refresh_from_db()
    assert req.status == MissionRequest.ASSIGNED and req.booking.total_price == 30000       # jamais le montant de la contre-offre expirée
    assert MissionOffer.objects.get(pk=ob.pk).status == MissionOffer.WITHDRAWN               # retrait dans la même transaction
    with pytest.raises(FlashError) as e:
        services.send_quote(ob.pk, b, 20000)
    assert e.value.code == "request_closed"


@real_db
def test_counter_or_proposal_expiring_while_it_is_accepted_has_one_outcome(make_pro, make_user, plomberie):
    cases = []
    for i in range(4):
        pro, client = make_pro(f"x{i}", km=0.05), make_user(f"cx{i}")
        req = raw_request(client, plomberie, mode="quote")
        now = timezone.now()
        if i % 2:      # contre-offre : le pro l'accepte dans la seconde tolérée, le passage la considère échue
            offer = quoted(req, pro, 30000, status=MissionOffer.COUNTERED, counter_amount=25000, counter_at=now, counters=1,
                           counter_expires_at=now + timedelta(seconds=60))
            act = lambda o=offer, p=pro: services.answer_counter(o.pk, p, True, now=o.counter_expires_at + timedelta(seconds=1))  # noqa: E731
            sweep = offer.counter_expires_at + timedelta(seconds=20)
        else:          # proposition : le client la choisit dans la seconde tolérée, le passage la considère échue
            offer = quoted(req, pro, 30000, proposal_expires_at=now + timedelta(seconds=60))
            act = lambda o=offer, r=req, c=client: services.choose_quote(r.pk, c, o.pk, now=o.proposal_expires_at + timedelta(seconds=1))  # noqa: E731
            sweep = offer.proposal_expires_at + timedelta(seconds=20)
        cases.append((req, offer, act, sweep))
    calls = []
    for req, offer, act, sweep in cases:
        calls += [act, lambda s=sweep, r=req: services.expire_due(now=s, request_id=r.pk)]
    results = race(*calls)
    assert crashes(results) == []
    for i, (req, offer, act, sweep) in enumerate(cases):
        req.refresh_from_db()
        offer.refresh_from_db()
        acted = results[2 * i]
        if acted == "ok":
            assert req.status == MissionRequest.ASSIGNED and offer.status == MissionOffer.ACCEPTED
            assert req.booking.total_price == (25000 if i % 2 else 30000)
        elif i % 2:    # contre-offre expirée la première : la proposition initiale reste, personne n'est engagé
            assert acted == "counter_closed" and offer.status == MissionOffer.QUOTED and req.booking_id is None
        else:          # proposition échue la première : retirée du choix, demande close
            assert acted in ("quote_unavailable", "request_closed") and offer.status == MissionOffer.LAPSED and req.booking_id is None
    assert Booking.objects.count() == sum(1 for i in range(len(cases)) if results[2 * i] == "ok")


# ═══ 4. Désistement et reprise ═══════════════════════════════════════════════════════════════════════════════════════

def test_withdrawal_restores_only_valid_proposals_and_never_the_withdrawn_pro(make_pro, make_request, client_user,
                                                                             django_capture_on_commit_callbacks):
    cfg(wave_size=3, max_quotes=3)
    a, b, c = make_pro("a", km=0.05), make_pro("b", km=0.06), make_pro("c", km=0.07)
    req = make_request(mode="quote")
    oa, ob, oc = offers_of(req)
    for offer, pro, amount in ((oa, a, 30000), (ob, b, 28000), (oc, c, 26000)):
        services.send_quote(offer.pk, pro, amount)
    MissionOffer.objects.filter(pk=oc.pk).update(proposal_expires_at=timezone.now() + timedelta(seconds=2))
    services.choose_quote(req.pk, client_user, oa.pk)
    req.refresh_from_db()
    booking, seq = req.booking, req.seq
    MissionOffer.objects.filter(pk=oc.pk).update(proposal_expires_at=timezone.now() - timedelta(seconds=1))   # échue entre-temps
    with django_capture_on_commit_callbacks(execute=True):
        booking.transition_to("cancelled", actor=a)
    req.refresh_from_db()
    assert req.status in (MissionRequest.SEARCHING, MissionRequest.QUOTING) and req.booking_id is None and req.seq > seq
    assert {o.handyman_id: o.status for o in offers_of(req)} == {a.pk: "resigned", b.pk: "quoted", c.pk: "withdrawn"}
    assert MissionRequest.objects.count() == 1 and len(offers_of(req)) == 3          # ni nouvelle demande, ni nouvelle proposition
    note = Notification.objects.get(user=client_user, title="Recherche reprise")       # le client est prévenu, explicitement
    assert "désisté" in note.message and note.data == {"kind": "flash_request", "id": req.pk}
    # Relance rejouée (signal répété, tâche rejouée) : sans aucun effet.
    with django_capture_on_commit_callbacks(execute=True):
        assert services.reopen_after_withdrawal(booking, a.pk) is None
        booking.save()
    assert kinds(req).count("reopened") == 1 and Notification.objects.filter(user=client_user, title="Recherche reprise").count() == 1
    for late in (lambda: services.choose_quote(req.pk, client_user, oa.pk), lambda: services.choose_quote(req.pk, client_user, oc.pk)):
        with pytest.raises(FlashError) as e:                             # ni le pro désisté, ni la proposition échue
            late()
        assert e.value.code == "quote_unavailable"
    services.choose_quote(req.pk, client_user, ob.pk)
    req.refresh_from_db()
    assert req.assigned_to_id == b.pk and req.booking.total_price == 28000 and req.booking_id != booking.pk
    assert Booking.objects.filter(status="confirmed").count() == 1


@real_db
def test_a_withdrawal_replayed_in_parallel_reopens_the_request_once(make_pro, make_request, client_user):
    cfg(wave_size=1)
    a, b = make_pro("a", km=0.05), make_pro("b", km=3)
    req = make_request()
    services.accept(offers_of(req)[0].pk, a)
    booking = MissionRequest.objects.get(pk=req.pk).booking
    booking.transition_to("cancelled", actor=a)
    results = race(*[lambda: services.reopen_after_withdrawal(booking, a.pk) for _ in range(4)],
                   *[lambda: services.launch_wave(req.pk) for _ in range(3)], lambda: tasks.tick())
    assert results == ["ok"] * 8
    req.refresh_from_db()
    assert req.status == MissionRequest.SEARCHING and kinds(req).count("reopened") == 1
    assert [(o.handyman_id, o.status) for o in offers_of(req)] == [(a.pk, "resigned"), (b.pk, "pending")]
    assert Notification.objects.filter(user=client_user, title="Recherche reprise").count() == 1


def test_resuming_respects_a_client_cancellation_and_the_geographic_consent(make_pro, make_request, client_user, make_user,
                                                                           django_capture_on_commit_callbacks):
    cfg(wave_size=1, max_active_requests_per_client=5)
    near, far = make_pro("pres", km=0.05), make_pro("loin", km=40)
    with django_capture_on_commit_callbacks(execute=True):
        req = make_request()
    services.accept(offers_of(req)[0].pk, near)
    req.refresh_from_db()
    assert not req.allow_far
    with django_capture_on_commit_callbacks(execute=True):
        req.booking.transition_to("cancelled", actor=near)
    req.refresh_from_db()
    # Reprise : le pro à 40 km n'est PAS sollicité sans l'accord du client, qui est reposé.
    assert req.status == MissionRequest.SEARCHING and [o.handyman_id for o in offers_of(req)] == [near.pk]
    assert not req.allow_far and req.consent_asked_at is not None and req.radius_m == 30000
    d = as_user(client_user).get(f"/handy/flash/requests/{req.pk}/").json()
    assert d["search"]["phase"] == "extension" and d["reopened"]["pro"] == "Pres"
    with django_capture_on_commit_callbacks(execute=True):
        services.allow_far(req.pk, client_user)
    assert [o.handyman_id for o in offers_of(req)] == [near.pk, far.pk]
    # Demande annulée par le client pendant la reprise : un désistement rejoué ne la rouvre pas.
    services.cancel_request(req.pk, client_user)
    assert services.reopen_after_withdrawal(Booking.objects.get(handyman=near), near.pk) is None
    assert MissionRequest.objects.get(pk=req.pk).status == MissionRequest.CANCELLED
    # Le CLIENT annule la réservation : ce n'est pas un désistement, rien n'est relancé.
    other = make_request(client=make_user("annule"))
    offer = offers_of(other)[0]
    services.accept(offer.pk, offer.handyman)
    other.refresh_from_db()
    with django_capture_on_commit_callbacks(execute=True):
        other.booking.transition_to("cancelled", actor=other.client)
    other.refresh_from_db()
    assert other.status == MissionRequest.ASSIGNED and "reopened" not in kinds(other) and len(offers_of(other)) == 1


# ═══ 5. Résilience ═══════════════════════════════════════════════════════════════════════════════════════════════════

@real_db
def test_repeated_and_simultaneous_tasks_send_each_wave_once(make_pro, make_request):
    cfg(wave_size=1)
    pros = [make_pro(f"t{i}", km=0.05 + i / 100) for i in range(3)]
    req = make_request()
    first = offers_of(req)[0]
    MissionOffer.objects.filter(pk=first.pk).update(expires_at=timezone.now() - timedelta(seconds=30))
    # Tâche livrée deux fois, compte à rebours et passage périodique au même instant, palier rejoué.
    results = race(*[lambda: tasks.wave_timeout(req.pk, 1) for _ in range(4)], *[lambda: tasks.tick() for _ in range(2)],
                   *[lambda: tasks.step_due(req.pk) for _ in range(2)], *[lambda: services.launch_wave(req.pk) for _ in range(2)])
    assert results == ["ok"] * 10
    req.refresh_from_db()
    assert [(o.wave, o.status) for o in offers_of(req)] == [(1, "expired"), (2, "pending")] and req.wave == 2
    assert kinds(req).count("expired") == 1 and kinds(req).count("wave") == 2 and req.seq == visible(req)
    assert len({o.handyman_id for o in offers_of(req)}) == 2 and {o.handyman_id for o in offers_of(req)} <= {p.pk for p in pros}


def test_lost_tasks_and_a_dead_realtime_channel_never_block_a_search(make_pro, make_request, client_user, monkeypatch,
                                                                    django_capture_on_commit_callbacks):
    def down(*args, **kwargs):
        raise ConnectionError("broker ou Redis indisponible")

    # Celery et le canal temps réel sont coupés (redémarrage) : chaque action aboutit quand même.
    monkeypatch.setattr("flash.tasks.wave_timeout.apply_async", down)
    monkeypatch.setattr("flash.tasks.step_due.apply_async", down)
    monkeypatch.setattr("flash.tasks.close_offers.apply_async", down)
    monkeypatch.setattr("handy.inbox.push", down)
    cfg(wave_size=1)
    a, b = make_pro("a", km=0.05), make_pro("b", km=0.06)
    with django_capture_on_commit_callbacks(execute=True):
        req = make_request()
    assert [o.handyman_id for o in offers_of(req)] == [a.pk]
    # Aucun compte à rebours n'a été posé : le passage périodique rattrape, à lui seul, l'échéance puis la vague suivante.
    MissionOffer.objects.filter(request=req).update(expires_at=timezone.now() - timedelta(seconds=30))
    with django_capture_on_commit_callbacks(execute=True):
        assert tasks.tick()["expired"] == 1
    assert [(o.handyman_id, o.status) for o in offers_of(req)] == [(a.pk, "expired"), (b.pk, "pending")]
    with django_capture_on_commit_callbacks(execute=True):
        services.accept(offers_of(req)[1].pk, b)
    req.refresh_from_db()
    assert req.status == MissionRequest.ASSIGNED and Booking.objects.count() == 1
    # À la reconnexion, l'API donne l'état complet et son numéro : rien n'a été perdu avec les messages non partis.
    d = as_user(client_user).get(f"/handy/flash/requests/{req.pk}/").json()
    assert d["status"] == "assigned" and d["search"]["seq"] == req.seq == visible(req) and d["search"]["counts"]["no_answer"] == 1


def test_deadlines_are_sent_with_the_server_clock_and_their_start(make_pro, make_request, client_user):
    """Barres de délai de l'application : heure du serveur, début et fin de chaque délai — jamais l'horloge du téléphone."""
    from django.utils.dateparse import parse_datetime as dt

    config = cfg(wave_size=1)
    a = make_pro("a", km=0.05)
    req = make_request(mode="quote")
    (oa,) = offers_of(req)
    seen = as_user(a).get(f"/handy/flash/offers/{oa.pk}/").json()
    start, end, now = dt(seen["sent_at"]), dt(seen["expires_at"]), dt(seen["server_now"])
    assert start <= now < end and 0 <= (end - now).total_seconds() - seen["seconds_left"] < 1
    listed = as_user(a).get("/handy/flash/offers/").json()["results"][0]
    assert listed["id"] == oa.pk and dt(listed["server_now"]) >= now and listed["expires_at"] == seen["expires_at"]
    services.send_quote(oa.pk, a, 30000)
    services.counter_offer(req.pk, client_user, oa.pk, 22000)
    counter = as_user(a).get(f"/handy/flash/offers/{oa.pk}/").json()["counter"]
    assert (dt(counter["expires_at"]) - dt(counter["at"])).total_seconds() == config.counter_timeout_seconds
    d = as_user(client_user).get(f"/handy/flash/requests/{req.pk}/").json()
    (q,) = d["quotes"]
    assert dt(d["server_now"]) < dt(q["expires_at"]) and dt(q["at"]) < dt(q["expires_at"])
    assert (dt(q["counter_expires_at"]) - dt(q["counter_at"])).total_seconds() == config.counter_timeout_seconds


def test_a_closed_proposal_is_announced_live_to_its_pro_even_without_push(make_pro, make_request, monkeypatch):
    """Push tardif ou perdu : la fermeture part aussi par le WebSocket, sinon l'écran « Accepter » du perdant reste ouvert."""
    cfg(wave_size=2)
    a, b = make_pro("a", km=0.05), make_pro("b", km=0.06)
    req = make_request()
    oa, ob = offers_of(req)
    sent = []
    monkeypatch.setattr("handy.inbox.push", lambda users, event: sent.append((list(users), event)))
    monkeypatch.setattr("handy.push.send_data_to_user", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("push en panne")))
    services.accept(oa.pk, a)
    try:
        tasks.close_offers([ob.pk])
    except RuntimeError:
        pass                                                           # le push en panne n'empêche pas l'annonce en direct
    live = [(users, e["id"], e["status"]) for users, e in sent if e.get("type") == "flash_offer"]
    assert ([b.pk], ob.pk, "withdrawn") in live
    monkeypatch.setattr("handy.inbox.push", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("redis coupé")))
    monkeypatch.setattr("handy.push.send_data_to_user", lambda *a, **k: None)
    tasks.close_offers([ob.pk])                                        # canal temps réel coupé : la tâche aboutit quand même


def test_a_late_notification_tap_gets_an_explicit_answer_and_changes_nothing(make_pro, make_request, client_user, make_user):
    cfg(wave_size=2, max_active_requests_per_client=5)
    a, b = make_pro("a", km=0.05), make_pro("b", km=0.06)

    def tap(pro, offer, action="accept", **body):
        r = as_user(pro).post(f"/handy/flash/offers/{offer.pk}/{action}/", body, format="json")
        return r.status_code, r.json().get("code")

    # Notification ouverte après l'échéance.
    req = make_request()
    oa, ob = offers_of(req)
    MissionOffer.objects.filter(pk=oa.pk).update(expires_at=timezone.now() - timedelta(seconds=10))
    assert tap(a, oa) == (409, "offer_expired")
    # … après l'attribution à un autre.
    services.accept(ob.pk, b)
    assert tap(a, oa) == (409, "already_assigned") and tap(a, oa, "decline") == (409, "offer_closed")
    # … après l'annulation par le client.
    other = make_request(client=make_user("tardif"))
    late = offers_of(other)[0]
    services.cancel_request(other.pk, other.client)
    assert tap(late.handyman, late) == (409, "request_closed")
    seen = as_user(late.handyman).get(f"/handy/flash/offers/{late.pk}/").json()
    assert (seen["status"], seen["request_status"], seen["seconds_left"]) == ("withdrawn", "cancelled", 0)
    assert Booking.objects.count() == 1 and MissionRequest.objects.get(pk=other.pk).status == MissionRequest.CANCELLED
