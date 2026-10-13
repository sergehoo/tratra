"""Messagerie interne : conversations privées uniques, messages persistants, états, non-lus, médias validés, blocage, signalement,
isolation, rattrapage après coupure, temps réel (WebSocket) et notifications."""
import json
from urllib.parse import quote

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import re_path
from rest_framework.test import APIClient

from handy import contacts, inbox
from handy.models import Booking, Conversation, Message, Notification, Report
from handy.test_booking_regression import _booking, _client
from handy.test_eligibility import artisan, service
from handy.testing import make_jpeg, make_mp4
from tratra import routing

pytestmark = pytest.mark.django_db


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


def link(a, b):
    """Met deux membres en relation (réservation acceptée), comme en production."""
    pro, cli = (a, b) if hasattr(a, "handyman_profile") and a.user_type == "handyman" else (b, a)
    return _booking(cli, pro, service(pro), status="confirmed")


def open_direct(a, b):
    r = api(a).post("/handy/me/conversations/", {"user": b.id}, format="json")
    assert r.status_code in (200, 201), r.content
    return r.json()["id"]


def send(user, conv, content="Bonjour", **extra):
    return api(user).post(f"/handy/me/conversations/{conv}/send/", {"content": content, **extra}, format="json")


# ----------------------------------------------------------------------------------------- conversations privées uniques

def test_private_conversation_is_unique_and_symmetrical():
    pro, cli = artisan("m_pro"), _client("m_cli")
    link(pro, cli)
    first = api(cli).post("/handy/me/conversations/", {"user": pro.id}, format="json")
    assert first.status_code == 201 and first.json()["created"] is True
    again = api(pro).post("/handy/me/conversations/", {"user": cli.id}, format="json")      # sens inverse : le MÊME fil
    assert again.status_code == 200 and again.json() == {"id": first.json()["id"], "created": False}
    assert Conversation.objects.filter(kind="direct").count() == 1


def test_cannot_open_conversation_with_self_staff_unknown_or_unreachable_stranger():
    cli, other = _client("m_a"), _client("m_b")
    staff = _client("m_staff")
    staff.is_staff = True
    staff.save()
    assert api(cli).post("/handy/me/conversations/", {"user": cli.id}, format="json").status_code == 404
    assert api(cli).post("/handy/me/conversations/", {"user": staff.id}, format="json").status_code == 404
    assert api(cli).post("/handy/me/conversations/", {"user": 999999}, format="json").status_code == 404
    r = api(cli).post("/handy/me/conversations/", {"user": other.id}, format="json")       # inconnu, non prestataire publié
    assert r.status_code == 403 and r.json()["code"] == "not_reachable"


def test_published_provider_can_be_contacted_before_any_booking():
    pro, cli = artisan("m_pub"), _client("m_cli2")
    assert api(cli).post("/handy/me/conversations/", {"user": pro.id}, format="json").status_code == 201


def test_empty_direct_conversation_is_not_listed_until_a_message_exists():
    pro, cli = artisan("m_e_pro"), _client("m_e_cli")
    conv = open_direct(cli, pro)
    assert api(pro).get("/handy/me/conversations/").json()["results"] == []             # pas de fil vide imposé au destinataire
    send(cli, conv, "Salut")
    assert [c["id"] for c in api(pro).get("/handy/me/conversations/").json()["results"]] == [conv]


# ------------------------------------------------------------------------------------------ messages, états, non-lus

def test_message_is_persisted_idempotent_and_counts_as_unread_for_the_recipient_only():
    pro, cli = artisan("m_i_pro"), _client("m_i_cli")
    link(pro, cli)
    conv = open_direct(cli, pro)
    cid = "6f1d1f9c-1d3e-4e53-9f64-4a7d1f0c9a11"
    r1 = send(cli, conv, "Bonjour, êtes-vous disponible ?", client_id=cid)
    r2 = send(cli, conv, "Bonjour, êtes-vous disponible ?", client_id=cid)                 # renvoi après coupure réseau
    assert r1.status_code == 201 and r2.status_code == 200 and r1.json()["message"]["id"] == r2.json()["message"]["id"]
    assert Message.objects.filter(conversation_id=conv).count() == 1
    m = r1.json()["message"]
    assert m["mine"] is True and m["state"] == "sent" and m["kind"] == "text" and m["created_at"]
    listing = api(pro).get("/handy/me/conversations/").json()
    assert listing["unread_total"] == 1 and listing["results"][0]["unread"] == 1
    assert listing["results"][0]["last_message"] == "Bonjour, êtes-vous disponible ?" and listing["results"][0]["counterpart"]
    assert api(cli).get("/handy/me/conversations/").json()["results"][0]["unread"] == 0     # ses propres messages ne comptent pas
    assert api(pro).get("/handy/me/messages/unread/").json() == {"total": 1, "conversations": {str(conv): 1}}


def test_delivered_then_read_states_reach_the_sender():
    pro, cli = artisan("m_s_pro"), _client("m_s_cli")
    link(pro, cli)
    conv = open_direct(cli, pro)
    mid = send(cli, conv, "Test").json()["message"]["id"]
    assert api(pro).post("/handy/me/messages/delivered/", {"ids": [mid]}, format="json").json() == {"delivered": 1}
    assert api(cli).post("/handy/me/messages/delivered/", {"ids": [mid]}, format="json").json() == {"delivered": 0}     # pas son propre message
    assert api(cli).get(f"/handy/me/conversations/{conv}/messages/").json()["results"][0]["state"] == "delivered"
    assert api(pro).post(f"/handy/me/conversations/{conv}/read/").json()["marked"] == 1
    got = api(cli).get(f"/handy/me/conversations/{conv}/messages/").json()["results"][0]
    assert got["state"] == "read" and got["is_read"] is True
    assert api(pro).get("/handy/me/messages/unread/").json()["total"] == 0


def test_reading_never_marks_the_readers_own_messages_or_other_conversations():
    pro, cli, other = artisan("m_r_pro"), _client("m_r_cli"), _client("m_r_oth")
    link(pro, cli)
    link(pro, other)
    c1, c2 = open_direct(cli, pro), open_direct(other, pro)
    send(cli, c1, "pour pro")
    send(pro, c1, "réponse")
    send(other, c2, "autre fil")
    api(pro).post(f"/handy/me/conversations/{c1}/read/")
    assert Message.objects.get(conversation_id=c2).is_read is False
    assert Message.objects.get(conversation_id=c1, sender=pro).is_read is False


def test_legacy_endpoints_keep_working():
    pro, cli = artisan("m_l_pro"), _client("m_l_cli")
    b = _booking(cli, pro, service(pro), status="confirmed")
    cid = api(cli).post("/handy/me/conversations/", {"booking": b.id}, format="json").json()["id"]
    assert api(cli).post("/handy/messages/", {"conversation": cid, "content": "Bonjour"}, format="json").status_code == 201
    assert api(pro).post(f"/handy/me/conversations/{cid}/messages/").json() == {"marked": 1}
    assert api(pro).put(f"/handy/messages/{Message.objects.get().id}/", {"content": "x"}, format="json").status_code == 405
    assert api(pro).delete(f"/handy/messages/{Message.objects.get().id}/").status_code == 405
    assert api(cli).post("/handy/conversations/", {"participants": [pro.id]}, format="json").status_code == 405


# ------------------------------------------------------------------------------------------------------------ isolation

def test_a_third_party_can_neither_read_send_mark_nor_report():
    pro, cli, spy = artisan("m_x_pro"), _client("m_x_cli"), _client("m_x_spy")
    link(pro, cli)
    conv = open_direct(cli, pro)
    mid = send(cli, conv, "privé").json()["message"]["id"]
    a = api(spy)
    assert a.get(f"/handy/me/conversations/{conv}/messages/").status_code == 404
    assert send(spy, conv, "intrus").status_code == 404
    assert a.post(f"/handy/me/conversations/{conv}/read/").status_code == 404
    assert a.post(f"/handy/me/conversations/{conv}/report/", {"reason": "test", "message": mid}, format="json").status_code == 404
    assert a.post("/handy/messages/", {"conversation": conv, "content": "x"}, format="json").status_code == 403
    assert a.post("/handy/me/messages/delivered/", {"ids": [mid]}, format="json").json() == {"delivered": 0}
    assert a.get("/handy/me/messages/sync/?after=0").json()["messages"] == []
    assert a.get("/handy/me/messages/search/?q=priv").json()["results"] == []
    assert a.get("/handy/me/conversations/").json()["results"] == []


# ---------------------------------------------------------------------------------------- pagination, recherche, sync

def test_thread_pagination_search_and_conversation_search():
    pro, cli = artisan("m_p_pro"), _client("m_p_cli")
    link(pro, cli)
    conv = open_direct(cli, pro)
    for i in range(7):
        send(cli, conv, f"message numéro {i}")
    page1 = api(pro).get(f"/handy/me/conversations/{conv}/messages/?limit=3").json()
    assert [m["content"] for m in page1["results"]] == ["message numéro 4", "message numéro 5", "message numéro 6"]
    assert page1["has_more"] is True
    page2 = api(pro).get(f"/handy/me/conversations/{conv}/messages/?limit=3&before={page1['next_before']}").json()
    assert [m["content"] for m in page2["results"]] == ["message numéro 1", "message numéro 2", "message numéro 3"]
    page3 = api(pro).get(f"/handy/me/conversations/{conv}/messages/?limit=3&before={page2['next_before']}").json()
    assert [m["content"] for m in page3["results"]] == ["message numéro 0"] and page3["has_more"] is False
    found = api(pro).get(f"/handy/me/conversations/{conv}/messages/?q=numéro 3").json()["results"]
    assert [m["content"] for m in found] == ["message numéro 3"]
    assert len(api(pro).get("/handy/me/messages/search/?q=numéro").json()["results"]) == 7
    assert api(pro).get("/handy/me/conversations/?q=zzz").json()["results"] == []
    assert len(api(pro).get("/handy/me/conversations/?q=numéro").json()["results"]) == 1
    assert len(api(pro).get(f"/handy/me/conversations/?q={cli.first_name or cli.username}").json()["results"]) in (0, 1)


def test_conversation_list_is_paginated():
    pro = artisan("m_pg_pro")
    for i in range(5):
        cli = _client(f"m_pg_c{i}")
        link(pro, cli)
        send(cli, open_direct(cli, pro), f"hello {i}")
    p1 = api(pro).get("/handy/me/conversations/?page_size=2").json()
    assert len(p1["results"]) == 2 and p1["has_more"] and p1["next_page"] == 2
    p3 = api(pro).get("/handy/me/conversations/?page_size=2&page=3").json()
    assert len(p3["results"]) == 1 and not p3["has_more"]


def test_sync_returns_only_newer_messages_in_order_and_marks_them_delivered():
    pro, cli = artisan("m_y_pro"), _client("m_y_cli")
    link(pro, cli)
    conv = open_direct(cli, pro)
    ids = [send(cli, conv, f"m{i}").json()["message"]["id"] for i in range(4)]
    data = api(pro).get(f"/handy/me/messages/sync/?after={ids[1]}").json()
    assert [m["id"] for m in data["messages"]] == ids[2:] and data["last_id"] == ids[-1] and data["unread_total"] == 4
    assert data["conversations"][0]["id"] == conv
    assert Message.objects.filter(pk__in=ids[2:], delivered_at__isnull=False).count() == 2
    assert api(pro).get(f"/handy/me/messages/sync/?after={ids[-1]}").json()["messages"] == []


# --------------------------------------------------------------------------------------------------------------- médias

def upload(user, conv, name, data, content="", mime="application/octet-stream"):
    return api(user).post(f"/handy/me/conversations/{conv}/send/", {"content": content, "file": SimpleUploadedFile(name, data, content_type=mime)},
                          format="multipart")


def test_photo_is_validated_recompressed_and_stripped_of_metadata():
    pro, cli = artisan("m_ph_pro"), _client("m_ph_cli")
    link(pro, cli)
    conv = open_direct(cli, pro)
    r = upload(cli, conv, "photo.jpg", make_jpeg((3000, 2000), exif=True), "voici")
    assert r.status_code == 201, r.content
    m = r.json()["message"]
    assert m["kind"] == "image" and m["attachment"]["mime"] == "image/jpeg" and max(m["attachment"]["width"], m["attachment"]["height"]) <= 1600
    stored = Message.objects.get(pk=m["id"])
    raw = stored.attachment.read()
    assert b"TestCam" not in raw and b"Exif" not in raw[:64]       # métadonnées et position GPS supprimées
    assert "/handy/me" not in (m["attachment"]["url"] or "")


@pytest.mark.parametrize("name,data", [
    ("faux.jpg", b"ceci n'est pas une image du tout" * 50),
    ("virus.jpg", b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 600),
    ("page.html", b"<html><script>alert(1)</script></html>"),
    ("tronque.jpg", make_jpeg()[:120]),
    ("vide.png", b""),
])
def test_files_with_wrong_or_corrupt_content_are_rejected_whatever_their_name(name, data):
    pro, cli = artisan("m_bad_pro"), _client("m_bad_cli")
    link(pro, cli)
    conv = open_direct(cli, pro)
    r = upload(cli, conv, name, data, mime="image/jpeg")
    assert r.status_code in (400, 413) and Message.objects.count() == 0


def test_video_pdf_and_limits(settings):
    pro, cli = artisan("m_v_pro"), _client("m_v_cli")
    link(pro, cli)
    conv = open_direct(cli, pro)
    ok = upload(cli, conv, "clip.mp4", make_mp4(12.0, 720, 1280))
    assert ok.status_code == 201 and ok.json()["message"]["kind"] == "video" and ok.json()["message"]["attachment"]["duration"] == 12.0
    long = upload(cli, conv, "long.mp4", make_mp4(300.0))
    assert long.status_code == 400 and long.json()["code"] == "video_too_long"
    pdf = upload(cli, conv, "devis.pdf", b"%PDF-1.4\n" + b"0" * 500)
    assert pdf.status_code == 201 and pdf.json()["message"]["kind"] == "file"
    settings.MESSAGE_MAX_VIDEO_BYTES = 1000
    big = upload(cli, conv, "gros.mp4", make_mp4(3.0))
    assert big.status_code == 413 and big.json()["code"] == "too_large"
    assert upload(cli, conv, "x.mp4", b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 100).status_code == 400   # sans index moov


def test_message_validation_rules():
    pro, cli = artisan("m_val_pro"), _client("m_val_cli")
    link(pro, cli)
    conv = open_direct(cli, pro)
    assert send(cli, conv, "   ").status_code == 400
    assert send(cli, conv, "x" * 4001).json()["code"] == "too_long"
    assert send(cli, conv, "ok", client_id="pas-un-uuid").json()["code"] == "invalid_client_id"


# -------------------------------------------------------------------------------------------- blocage et signalement

def test_blocking_stops_messages_both_ways_hides_contact_and_is_reversible():
    pro, cli = artisan("m_b_pro"), _client("m_b_cli")
    link(pro, cli)
    conv = open_direct(cli, pro)
    send(cli, conv, "avant")
    assert pro.id in contacts.contact_ids(cli.id)
    assert api(pro).post("/handy/me/blocks/", {"user": cli.id}, format="json").status_code == 201
    assert send(cli, conv, "après").status_code == 403                              # le membre bloqué ne peut plus écrire
    assert send(pro, conv, "moi aussi").status_code == 403                          # ni le bloqueur (il doit débloquer)
    assert api(cli).post("/handy/me/conversations/", {"user": pro.id}, format="json").status_code in (200, 403)
    assert pro.id not in contacts.contact_ids(cli.id) and cli.id not in contacts.contact_ids(pro.id)
    row = api(pro).get("/handy/me/conversations/").json()["results"][0]
    assert row["blocked"] is True and row["can_send"] is False
    assert api(pro).get("/handy/me/blocks/").json()["results"][0]["user"] == cli.id
    assert api(pro).delete(f"/handy/me/blocks/{cli.id}/").status_code == 204
    assert send(cli, conv, "de retour").status_code == 201
    assert Notification.objects.filter(user=pro, notification_type="message_received").count() == 2       # « avant » + « de retour », pas « après »


def test_report_creates_a_moderation_report_for_a_message_of_the_other_member():
    pro, cli = artisan("m_rp_pro"), _client("m_rp_cli")
    link(pro, cli)
    conv = open_direct(cli, pro)
    mid = send(cli, conv, "insulte").json()["message"]["id"]
    mine = send(pro, conv, "réponse").json()["message"]["id"]
    assert api(pro).post(f"/handy/me/conversations/{conv}/report/", {"reason": ""}, format="json").status_code == 400
    r = api(pro).post(f"/handy/me/conversations/{conv}/report/", {"reason": "Propos injurieux", "block": True}, format="json")
    assert r.status_code == 201
    rep = Report.objects.get()
    assert rep.reporter_id == pro.id and rep.message_id == mid and rep.report_type == "message"
    assert api(pro).post(f"/handy/me/conversations/{conv}/report/", {"reason": "x y z", "message": mine}, format="json").status_code == 404   # pas son propre message
    assert api(pro).get("/handy/me/blocks/").json()["results"][0]["user"] == cli.id


# --------------------------------------------------------------------------------------------------- notifications

def test_message_creates_a_persistent_notification_with_preview_and_deeplink_only_for_the_recipient():
    pro, cli = artisan("m_n_pro"), _client("m_n_cli")
    link(pro, cli)
    conv = open_direct(cli, pro)
    send(cli, conv, "Pouvez-vous passer demain ?")
    n = Notification.objects.get(user=pro, notification_type="message_received")
    assert n.message == "Pouvez-vous passer demain ?" and n.data == {"kind": "conversation", "id": conv} and n.category == "message"
    assert not Notification.objects.filter(user=cli, notification_type="message_received").exists()
    upload(cli, conv, "a.jpg", make_jpeg())
    assert Notification.objects.filter(user=pro, message__startswith="📷").exists()


# --------------------------------------------------------------------------------------------------------- temps réel

def _app():
    return URLRouter(routing.websocket_urlpatterns)


async def _connect(path):
    comm = WebsocketCommunicator(_app(), path)
    connected, code = await comm.connect()
    return comm, connected, code


@pytest.mark.django_db(transaction=True)
def test_websocket_inbox_requires_a_valid_ticket_and_streams_messages_and_receipts_in_real_time():
    pro, cli, out = artisan("m_ws_pro"), _client("m_ws_cli"), _client("m_ws_out")
    link(pro, cli)
    conv = open_direct(cli, pro)

    async def scenario():
        for path in ("/ws/inbox/", "/ws/inbox/?ticket=nimportequoi"):
            _, ok, _ = await _connect(path)
            assert ok is False
        pro_ws, ok1, _ = await _connect(f"/ws/inbox/?ticket={quote(inbox.make_ticket(pro.id), safe='')}")
        cli_ws, ok2, _ = await _connect(f"/ws/inbox/?ticket={quote(inbox.make_ticket(cli.id), safe='')}")
        out_ws, ok3, _ = await _connect(f"/ws/inbox/?ticket={quote(inbox.make_ticket(out.id), safe='')}")
        assert ok1 and ok2 and ok3
        assert (await pro_ws.receive_json_from())["type"] == "ready"
        await cli_ws.receive_json_from()
        await out_ws.receive_json_from()
        # envoi par l'API : le destinataire ET l'expéditeur (autre appareil) reçoivent le message, un tiers rien
        r = await sync_to_async(send)(cli, conv, "temps réel")
        assert r.status_code == 201
        got = await pro_ws.receive_json_from()
        assert got["type"] == "message" and got["message"]["content"] == "temps réel" and got["message"]["mine"] is False
        assert got["conversation"]["unread"] == 1 and got["unread_total"] == 1
        echo = await cli_ws.receive_json_from()
        assert echo["message"]["mine"] is True
        assert await out_ws.receive_nothing(timeout=0.3)
        # accusé de réception par WebSocket puis lecture : l'expéditeur voit « distribué » puis « lu »
        await pro_ws.send_json_to({"type": "ack", "ids": [got["message"]["id"]]})
        delivered = await cli_ws.receive_json_from()
        assert delivered["type"] == "delivered" and delivered["ids"] == [got["message"]["id"]]
        await sync_to_async(lambda: api(pro).post(f"/handy/me/conversations/{conv}/read/"))()
        read = await cli_ws.receive_json_from()
        assert read["type"] == "read" and read["conversation"] == conv
        await pro_ws.send_json_to({"type": "ping"})
        seen = [await pro_ws.receive_json_from() for _ in range(2)]          # lu (pour le lecteur) + pong
        assert {m["type"] for m in seen} == {"read", "pong"}
        for c in (pro_ws, cli_ws, out_ws):
            await c.disconnect()

    async_to_sync(scenario)()


@pytest.mark.django_db(transaction=True)
def test_chat_socket_of_a_conversation_is_refused_to_non_participants():
    pro, cli, out = artisan("m_cw_pro"), _client("m_cw_cli"), _client("m_cw_out")
    link(pro, cli)
    conv = open_direct(cli, pro)

    async def scenario():
        _, ok_out, code = await _connect(f"/ws/chat/{conv}/?ticket={quote(inbox.make_ticket(out.id), safe='')}")
        assert ok_out is False
        ws, ok, _ = await _connect(f"/ws/chat/{conv}/?ticket={quote(inbox.make_ticket(pro.id), safe='')}")
        assert ok
        await ws.disconnect()

    async_to_sync(scenario)()


def test_realtime_ticket_requires_authentication_and_is_short_lived():
    cli = _client("m_t_cli")
    assert api().post("/handy/me/realtime/ticket/").status_code in (401, 403)
    t = api(cli).post("/handy/me/realtime/ticket/").json()
    assert t["expires_in"] == 60 and inbox.read_ticket(t["ticket"]) == cli.id
    assert inbox.read_ticket(t["ticket"] + "x") is None
