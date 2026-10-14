"""Statuts éphémères : publication validée, expiration, visibilité (contacts, audience élargie, exclusions, blocages), vues, lecteurs
(auteur seul), réponses, signalement, purge, idempotence et invalidation du cache."""
import os
from datetime import timedelta
from unittest import mock

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from handy.models import Conversation, Message
from handy.test_booking_regression import _client
from handy.test_eligibility import artisan
from handy.test_messaging import link
from handy.testing import make_jpeg, make_mp4
from statuses import services, tasks
from statuses.models import Status, StatusReport, StatusView

pytestmark = pytest.mark.django_db


def api(user=None):
    c = APIClient()
    if user:
        c.force_authenticate(user)
    return c


def post(user, text="", file=None, **extra):
    data = {"text": text, **extra}
    if file is not None:
        data["file"] = file
    return api(user).post("/handy/statuses/", data, format="multipart")


def up(name, data, mime="application/octet-stream"):
    return SimpleUploadedFile(name, data, content_type=mime)


def pair(prefix):
    """Un artisan et un client en relation (réservation acceptée) : contacts Tratra."""
    pro, cli = artisan(f"{prefix}_pro"), _client(f"{prefix}_cli")
    link(pro, cli)
    return pro, cli


def feed(user):
    return api(user).get("/handy/statuses/feed/").json()


# ------------------------------------------------------------------------------------------------------- publication

def test_publish_text_photo_video_and_text_with_media():
    a = _client("st_a")
    t = post(a, "Bonjour Tratra")
    assert t.status_code == 201 and t.json()["status"]["type"] == "text" and t.json()["status"]["background"] == "green"
    p = post(a, "", up("p.jpg", make_jpeg((3200, 2400), exif=True)))
    assert p.status_code == 201 and p.json()["status"]["type"] == "photo"
    meta = p.json()["status"]["media"]
    assert max(meta["width"], meta["height"]) <= 1600 and meta["mime"] == "image/jpeg"
    raw = Status.objects.get(pk=p.json()["status"]["id"]).media.read()
    assert b"TestCam" not in raw                                        # métadonnées retirées
    v = post(a, "", up("v.mp4", make_mp4(12, 720, 1280)))
    assert v.status_code == 201 and v.json()["status"]["type"] == "video" and v.json()["status"]["media"]["duration"] == 12.0
    tm = post(a, "Chantier terminé", up("c.jpg", make_jpeg()))
    assert tm.json()["status"]["type"] == "text_media" and tm.json()["status"]["text"] == "Chantier terminé"
    mine = api(a).get("/handy/statuses/").json()
    assert mine["count"] == 4 and [s["views"] for s in mine["statuses"]] == [{"unique": 0, "total": 0}] * 4


def test_default_limits_are_24h_700_chars_30_seconds():
    a = _client("st_l")
    s = post(a, "x" * 700)
    assert s.status_code == 201
    st = Status.objects.get()
    assert timedelta(hours=23, minutes=59) < st.expires_at - st.created_at <= timedelta(hours=24, minutes=1)
    assert post(a, "x" * 701).json()["code"] == "text_too_long"
    assert post(a, "").json()["code"] == "empty"
    assert post(a, "", up("long.mp4", make_mp4(31))).json()["code"] == "video_too_long"
    assert post(a, "", up("ok.mp4", make_mp4(30))).status_code == 201
    lim = api(a).get("/handy/statuses/feed/").json()["limits"]
    assert lim["text_max"] == 700 and lim["video_max_seconds"] == 30 and lim["ttl_hours"] == 24


def test_limits_are_configurable(settings):
    settings.STATUS_TEXT_MAX, settings.STATUS_TTL_HOURS, settings.STATUS_VIDEO_MAX_SECONDS = 20, 6, 5
    a = _client("st_cfg")
    assert post(a, "x" * 21).status_code == 400
    assert post(a, "", up("v.mp4", make_mp4(6))).status_code == 400
    post(a, "court")
    st = Status.objects.get()
    assert st.expires_at - st.created_at < timedelta(hours=6, minutes=1)


@pytest.mark.parametrize("name,data", [
    ("faux.jpg", b"pas une image" * 100), ("virus.png", b"MZ\x90\x00" + b"\0" * 500), ("page.html", b"<script>1</script>"),
    ("doc.pdf", b"%PDF-1.4\n" + b"0" * 100), ("coupe.jpg", make_jpeg()[:100]), ("sans_moov.mp4", b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\0" * 80),
])
def test_invalid_media_is_rejected_by_content_not_name(name, data):
    a = _client("st_bad")
    assert post(a, "", up(name, data, "image/jpeg")).status_code in (400, 413)
    assert Status.objects.count() == 0


def test_size_limit(settings):
    settings.STATUS_MAX_VIDEO_BYTES = 500
    a = _client("st_big")
    r = post(a, "", up("v.mp4", make_mp4(3)))
    assert r.status_code == 413 and r.json()["code"] == "too_large"


def test_publish_is_idempotent_on_client_id_and_no_orphan_media():
    a = _client("st_i")
    cid = "7c2f2e55-87d6-4b1e-8c1e-41a76f2c9a10"
    photo = make_jpeg()
    r1 = post(a, "", up("p.jpg", photo), client_id=cid)
    r2 = post(a, "", up("p.jpg", photo), client_id=cid)                  # renvoi après coupure réseau
    assert r1.status_code == 201 and r2.status_code == 200 and r1.json()["status"]["id"] == r2.json()["status"]["id"]
    assert Status.objects.count() == 1 and len(default_storage.listdir("statuses/%s" % timezone.now().strftime("%Y/%m"))[1]) == 1
    assert post(a, "x", client_id="pas-un-uuid").json()["code"] == "invalid_client_id"


def test_active_status_quota(settings):
    settings.STATUS_MAX_ACTIVE_PER_USER = 2
    a = _client("st_q")
    assert post(a, "1").status_code == 201 and post(a, "2").status_code == 201
    r = post(a, "3")
    assert r.status_code == 429 and r.json()["code"] == "quota"


def test_delete_is_author_only_and_removes_content_and_media(django_capture_on_commit_callbacks):
    pro, cli = pair("st_d")
    s = post(pro, "", up("p.jpg", make_jpeg()), audience="contacts").json()["status"]
    name = Status.objects.get(pk=s["id"]).media.name
    assert default_storage.exists(name)
    assert api(cli).delete(f"/handy/statuses/{s['id']}/").status_code == 404
    with django_capture_on_commit_callbacks(execute=True):          # en production, la suppression du fichier suit la validation de la transaction
        assert api(pro).delete(f"/handy/statuses/{s['id']}/").status_code == 204
    assert not default_storage.exists(name)
    st = Status.objects.get()
    assert st.deleted_at and st.text == "" and not st.media
    assert feed(cli)["contacts"] == [] and api(pro).get("/handy/statuses/").json()["count"] == 0
    assert api(pro).delete(f"/handy/statuses/{s['id']}/").status_code == 404


# --------------------------------------------------------------------------------------------------------- expiration

def test_status_disappears_after_24_hours_even_before_the_purge_runs():
    pro, cli = pair("st_x")
    post(pro, "éphémère")
    assert len(feed(cli)["contacts"]) == 1
    later = timezone.now() + timedelta(hours=24, minutes=1)
    with mock.patch.object(timezone, "now", return_value=later):
        services.bump()
        assert feed(cli)["contacts"] == [] and api(pro).get("/handy/statuses/").json()["count"] == 0
        assert api(cli).post(f"/handy/statuses/{Status.objects.get().pk}/view/").status_code == 404     # plus de vue sur un statut expiré


def test_purge_removes_expired_media_after_retention_then_old_rows_and_orphans(settings):
    a = _client("st_p")
    s = post(a, "", up("p.jpg", make_jpeg())).json()["status"]
    kept = post(a, "", up("k.jpg", make_jpeg())).json()["status"]
    st = Status.objects.get(pk=s["id"])
    name = st.media.name
    Status.objects.filter(pk=st.pk).update(expires_at=timezone.now() - timedelta(hours=2))      # expiré depuis 2 h : conservation 24 h
    assert services.purge()["media_purged"] == 0 and default_storage.exists(name)
    Status.objects.filter(pk=st.pk).update(expires_at=timezone.now() - timedelta(hours=25))
    out = services.purge()
    assert out["media_purged"] == 1 and not default_storage.exists(name)
    assert Status.objects.get(pk=kept["id"]).media and Status.objects.filter(pk=st.pk).exists()
    Status.objects.filter(pk=st.pk).update(expires_at=timezone.now() - timedelta(days=31))
    assert services.purge()["rows_deleted"] == 1 and not Status.objects.filter(pk=st.pk).exists()
    # fichier orphelin ancien supprimé, orphelin récent conservé, fichier référencé conservé
    month = timezone.now().strftime("%Y/%m")
    old, recent = f"statuses/{month}/orphelin_ancien.jpg", f"statuses/{month}/orphelin_recent.jpg"
    default_storage.save(old, ContentFile(b"x")), default_storage.save(recent, ContentFile(b"x"))
    past = (timezone.now() - timedelta(days=3)).timestamp()
    os.utime(default_storage.path(old), (past, past))
    out = services.purge()
    assert out["orphans_deleted"] == 1 and not default_storage.exists(old) and default_storage.exists(recent)
    assert default_storage.exists(Status.objects.get(pk=kept["id"]).media.name)


def test_purge_task_is_registered_retryable_and_scheduled(settings):
    assert tasks.purge.name == "statuses.tasks.purge" and tasks.purge.max_retries == 5
    assert settings.CELERY_BEAT_SCHEDULE["statuses-purge"]["task"] == "statuses.tasks.purge"
    assert tasks.purge.apply().get()["rows_deleted"] == 0


# ---------------------------------------------------------------------------------------------------------- visibilité

def test_contacts_see_statuses_in_their_feed_strangers_do_not():
    pro, cli = pair("st_v")
    stranger = _client("st_v_out")
    post(pro, "pour mes contacts")
    got = feed(cli)
    assert len(got["contacts"]) == 1 and got["contacts"][0]["author"]["id"] == pro.id and got["contacts"][0]["statuses"][0]["text"] == "pour mes contacts"
    assert feed(stranger)["contacts"] == [] and feed(stranger)["discover_count"] == 0
    assert api(stranger).get("/handy/statuses/discover/").json()["results"] == []
    assert api(stranger).post(f"/handy/statuses/{Status.objects.get().pk}/view/").status_code == 404
    assert api().get("/handy/statuses/feed/").status_code in (401, 403)


def test_extended_audience_appears_in_discover_for_non_contacts_not_in_the_home_bar():
    pro, cli = pair("st_e")
    stranger = _client("st_e_out")
    post(pro, "pour tous", audience="extended")
    assert len(feed(cli)["contacts"]) == 1                                  # contact : barre d'accueil
    f = feed(stranger)
    assert f["contacts"] == [] and f["discover_count"] == 1
    d = api(stranger).get("/handy/statuses/discover/").json()
    assert len(d["results"]) == 1 and d["results"][0]["author"]["id"] == pro.id and d["has_more"] is False
    assert api(cli).get("/handy/statuses/discover/").json()["results"] == []   # un contact ne le retrouve pas dans « Découvrir »


def test_default_audience_preference_and_per_status_override():
    pro, cli = pair("st_pref")
    stranger = _client("st_pref_out")
    assert api(pro).get("/handy/statuses/settings/").json()["audience"] == "contacts"
    assert api(pro).put("/handy/statuses/settings/", {"audience": "extended"}, format="json").json()["audience"] == "extended"
    post(pro, "hérite de l'audience élargie")
    post(pro, "mais celui-ci reste privé", audience="contacts")
    assert api(stranger).get("/handy/statuses/discover/").json()["results"][0]["statuses"][0]["text"] == "hérite de l'audience élargie"
    assert len(api(stranger).get("/handy/statuses/discover/").json()["results"][0]["statuses"]) == 1
    assert api(pro).put("/handy/statuses/settings/", {"audience": "tous"}, format="json").status_code == 400


def test_individual_exclusion_hides_statuses_without_telling_the_member_and_is_reversible():
    pro, cli = pair("st_ex")
    post(pro, "secret")
    assert api(pro).post("/handy/statuses/exclusions/", {"user": cli.id}, format="json").status_code == 201
    assert feed(cli)["contacts"] == []
    sid = Status.objects.get().pk
    assert api(cli).post(f"/handy/statuses/{sid}/view/").status_code == 404
    assert api(pro).get("/handy/statuses/settings/").json()["exclusions"][0]["user"] == cli.id
    assert api(pro).get("/handy/statuses/contacts/").json()["results"][0]["excluded"] is True
    assert api(pro).delete(f"/handy/statuses/exclusions/{cli.id}/").status_code == 204
    assert len(feed(cli)["contacts"]) == 1
    assert api(pro).post("/handy/statuses/exclusions/", {"user": pro.id}, format="json").status_code == 404


def test_blocking_hides_statuses_in_both_directions_even_for_extended_audience():
    pro, cli = pair("st_bl")
    post(pro, "de pro", audience="extended")
    post(cli, "de client", audience="extended")
    assert len(feed(cli)["contacts"]) == 1 and len(feed(pro)["contacts"]) == 1
    api(pro).post("/handy/me/blocks/", {"user": cli.id}, format="json")
    assert feed(cli)["contacts"] == [] and feed(pro)["contacts"] == []
    assert api(cli).get("/handy/statuses/discover/").json()["results"] == [] and api(pro).get("/handy/statuses/discover/").json()["results"] == []
    assert api(cli).post(f"/handy/statuses/{Status.objects.get(author=pro).pk}/view/").status_code == 404


def test_feed_orders_unread_before_seen_and_flags_seen_after_a_view():
    pro, cli = pair("st_o")
    pro2 = artisan("st_o_pro2")
    link(pro2, cli)
    post(pro, "p1")
    post(pro2, "p2")
    f = feed(cli)
    assert [g["unseen"] for g in f["contacts"]] == [1, 1] and f["contacts"][0]["author"]["id"] == pro2.id      # le plus récent d'abord
    api(cli).post(f"/handy/statuses/{Status.objects.get(author=pro2).pk}/view/")
    f = feed(cli)
    assert [g["author"]["id"] for g in f["contacts"]] == [pro.id, pro2.id] and f["contacts"][1]["seen"] is True    # non lus avant les consultés
    assert f["contacts"][1]["statuses"][0]["seen"] is True


# ------------------------------------------------------------------------------------------------------------- vues

def test_view_is_counted_once_per_member_and_never_by_loading_the_feed():
    pro, cli = pair("st_w")
    other = _client("st_w2")
    link(pro, other)
    post(pro, "à voir")
    sid = Status.objects.get().pk
    for _ in range(3):                                                      # préchargements du fil : aucune vue
        feed(cli), api(cli).get("/handy/statuses/discover/")
    assert StatusView.objects.count() == 0
    r1 = api(cli).post(f"/handy/statuses/{sid}/view/").json()
    r2 = api(cli).post(f"/handy/statuses/{sid}/view/").json()               # double affichage involontaire
    assert r1["counted"] is True and r2 == {"counted": False, "reason": "already_counted"}
    api(other).post(f"/handy/statuses/{sid}/view/")
    assert api(pro).post(f"/handy/statuses/{sid}/view/").json() == {"counted": False, "reason": "own"}      # l'auteur ne se compte pas
    mine = api(pro).get("/handy/statuses/").json()["statuses"][0]
    assert mine["views"] == {"unique": 2, "total": 2}


def test_repeat_views_counted_only_when_enabled_and_outside_the_debounce_window(settings):
    pro, cli = pair("st_r")
    post(pro, "répété")
    sid = Status.objects.get().pk
    settings.STATUS_REPEAT_VIEWS_ENABLED = True
    api(cli).post(f"/handy/statuses/{sid}/view/")
    assert api(cli).post(f"/handy/statuses/{sid}/view/").json()["counted"] is False                 # dans la fenêtre de 30 s
    StatusView.objects.update(last_viewed_at=timezone.now() - timedelta(minutes=5))
    assert api(cli).post(f"/handy/statuses/{sid}/view/").json()["counted"] is True
    assert api(pro).get("/handy/statuses/").json()["statuses"][0]["views"] == {"unique": 1, "total": 2}
    v = api(pro).get(f"/handy/statuses/{sid}/viewers/").json()
    assert v["counters"] == {"unique": 1, "total": 2} and v["results"][0]["count"] == 2
    settings.STATUS_REPEAT_VIEWS_ENABLED = False
    assert api(pro).get("/handy/statuses/").json()["statuses"][0]["views"] == {"unique": 1, "total": 1}


def test_only_the_author_sees_the_named_viewer_list_with_view_times():
    pro, cli = pair("st_n")
    nosy = _client("st_n2")
    link(pro, nosy)
    post(pro, "liste", audience="contacts")
    sid = Status.objects.get().pk
    api(cli).post(f"/handy/statuses/{sid}/view/")
    api(nosy).post(f"/handy/statuses/{sid}/view/")
    got = api(pro).get(f"/handy/statuses/{sid}/viewers/").json()
    assert got["counters"]["unique"] == 2 and {r["user"]["id"] for r in got["results"]} == {cli.id, nosy.id}
    assert all(r["viewed_at"] for r in got["results"]) and "email" not in str(got) and "phone" not in str(got)
    for viewer in (cli, nosy, _client("st_n3")):                              # lecteurs, tiers : jamais la liste
        assert api(viewer).get(f"/handy/statuses/{sid}/viewers/").status_code == 404
    assert "viewers" not in str(feed(cli)) and "views" not in str(feed(cli)["contacts"])         # aucun compteur dans le fil d'un lecteur


def test_viewer_list_is_paginated():
    pro = artisan("st_pg")
    post(pro, "beaucoup de lecteurs")
    sid = Status.objects.get().pk
    for i in range(5):
        c = _client(f"st_pg_c{i}")
        link(pro, c)
        api(c).post(f"/handy/statuses/{sid}/view/")
    p1 = api(pro).get(f"/handy/statuses/{sid}/viewers/?page_size=2").json()
    assert len(p1["results"]) == 2 and p1["has_more"] and p1["next_page"] == 2 and p1["counters"]["unique"] == 5
    assert len(api(pro).get(f"/handy/statuses/{sid}/viewers/?page_size=2&page=3").json()["results"]) == 1


# --------------------------------------------------------------------------------------- réponse, signalement, cache

def test_reply_creates_a_private_message_with_the_status_as_context_when_allowed():
    pro, cli = pair("st_re")
    post(pro, "Promo plomberie")
    sid = Status.objects.get().pk
    r = api(cli).post(f"/handy/statuses/{sid}/reply/", {"content": "Intéressé !"}, format="json")
    assert r.status_code == 201
    m = Message.objects.get()
    assert m.sender_id == cli.id and m.context == {"status": sid, "kind": "text", "text": "Promo plomberie"}
    assert r.json()["message"]["context"]["status"] == sid
    assert Conversation.objects.get(pk=r.json()["conversation"]).participants.count() == 2
    assert api(pro).post(f"/handy/statuses/{sid}/reply/", {"content": "moi"}, format="json").status_code == 404      # pas à soi-même
    api(pro).put("/handy/statuses/settings/", {"allow_replies": False}, format="json")
    post(pro, "sans réponses")
    sid2 = Status.objects.order_by("-id").first().pk
    r2 = api(cli).post(f"/handy/statuses/{sid2}/reply/", {"content": "ok ?"}, format="json")
    assert r2.status_code == 403 and r2.json()["code"] == "replies_disabled"


def test_reply_from_a_stranger_is_possible_only_for_an_extended_status_and_not_when_blocked():
    pro = artisan("st_rs_pro")
    stranger = _client("st_rs_out")
    post(pro, "ouvert", audience="extended")
    sid = Status.objects.get().pk
    assert api(stranger).post(f"/handy/statuses/{sid}/reply/", {"content": "Bonjour"}, format="json").status_code == 201
    api(pro).post("/handy/me/blocks/", {"user": stranger.id}, format="json")
    assert api(stranger).post(f"/handy/statuses/{sid}/reply/", {"content": "encore"}, format="json").status_code == 404


def test_report_a_visible_status_once():
    pro, cli = pair("st_rp")
    post(pro, "choquant")
    sid = Status.objects.get().pk
    assert api(cli).post(f"/handy/statuses/{sid}/report/", {"reason": ""}, format="json").status_code == 400
    assert api(cli).post(f"/handy/statuses/{sid}/report/", {"reason": "Contenu choquant"}, format="json").status_code == 201
    api(cli).post(f"/handy/statuses/{sid}/report/", {"reason": "Contenu choquant"}, format="json")
    assert StatusReport.objects.count() == 1
    assert api(_client("st_rp3")).post(f"/handy/statuses/{sid}/report/", {"reason": "abus"}, format="json").status_code == 404


def test_feed_cache_is_invalidated_on_publish_and_delete():
    pro, cli = pair("st_c")
    assert feed(cli)["contacts"] == []
    r = post(pro, "nouveau")
    assert len(feed(cli)["contacts"]) == 1                                   # publication : visible aussitôt malgré le cache
    api(pro).delete(f"/handy/statuses/{r.json()['status']['id']}/")
    assert feed(cli)["contacts"] == []                                       # suppression : disparu aussitôt


@pytest.mark.django_db(transaction=True)
def test_realtime_event_is_pushed_to_contacts_on_publish_and_to_the_author_on_first_view():
    from asgiref.sync import async_to_sync, sync_to_async
    from channels.routing import URLRouter
    from channels.testing import WebsocketCommunicator

    from handy import inbox
    from tratra import routing

    pro, cli = pair("st_ws")

    async def scenario():
        conns = {}
        for user in (pro, cli):
            ws = WebsocketCommunicator(URLRouter(routing.websocket_urlpatterns), f"/ws/inbox/?ticket={inbox.make_ticket(user.id)}")
            ok, _ = await ws.connect()
            assert ok and (await ws.receive_json_from())["type"] == "ready"
            conns[user.id] = ws
        r = await sync_to_async(post)(pro, "live")
        ev = await conns[cli.id].receive_json_from()
        assert ev == {"type": "status", "action": "new", "author": pro.id, "status": r.json()["status"]["id"]}
        await sync_to_async(lambda: api(cli).post(f"/handy/statuses/{r.json()['status']['id']}/view/"))()
        seen = [await conns[pro.id].receive_json_from() for _ in range(2)]                   # sa propre publication puis la première vue
        assert any(e["type"] == "status_view" and e["views"]["unique"] == 1 for e in seen)
        for ws in conns.values():
            await ws.disconnect()

    async_to_sync(scenario)()


# ---------------------------------------------------------------------------------------------------- modération (BO)

def test_staff_moderation_lists_reports_removes_the_status_with_reason_and_notifies_the_author(django_capture_on_commit_callbacks):
    from backoffice.test_people import BO, staff
    from handy.models import Notification
    from trust.models import AuditEvent

    pro, cli = pair("st_mod")
    post(pro, "contenu litigieux")
    sid = Status.objects.get().pk
    api(cli).post(f"/handy/statuses/{sid}/report/", {"reason": "Contenu choquant"}, format="json")
    mod, analyst = staff("st_mod_s", "support"), staff("st_mod_a", "analyst")
    assert api(analyst).get(f"{BO}/statuses/reports/").status_code == 403
    rows = api(mod).get(f"{BO}/statuses/reports/").json()["results"]
    assert len(rows) == 1 and rows[0]["text"] == "contenu litigieux" and rows[0]["resolved"] is False
    assert api(mod).post(f"{BO}/statuses/{sid}/remove/", {"reason": "x"}, format="json").status_code == 400
    with django_capture_on_commit_callbacks(execute=True):
        assert api(mod).post(f"{BO}/statuses/{sid}/remove/", {"reason": "Propos inappropriés"}, format="json").status_code == 200
    st = Status.objects.get()
    assert st.deleted_at and st.removed_by_staff and st.text == "" and feed(cli)["contacts"] == []
    assert Notification.objects.filter(user=pro, title="Statut retiré").exists()
    assert AuditEvent.objects.filter(action="backoffice.status.removed", actor=mod).exists()
    assert api(mod).get(f"{BO}/statuses/reports/?resolved=true").json()["results"][0]["resolved"] is True


# ----------------------------------------------------------------- permissions : cas croisés (contacts, découverte, exclusions, blocages)

def endpoints(sid):
    return [("post", f"/handy/statuses/{sid}/view/", {}), ("post", f"/handy/statuses/{sid}/reply/", {"content": "Bonjour"}),
            ("post", f"/handy/statuses/{sid}/report/", {"reason": "motif valable"}), ("get", f"/handy/statuses/{sid}/viewers/", None)]


def hit(user, method, url, body):
    c = api(user)
    return getattr(c, method)(url, body, format="json") if body is not None else getattr(c, method)(url)


def test_a_contacts_only_status_is_closed_to_non_contacts_on_every_endpoint():
    pro, cli = pair("pm_c")
    stranger = _client("pm_c_out")
    sid = post(pro, "réservé aux contacts", audience="contacts").json()["status"]["id"]
    for method, url, body in endpoints(sid):
        assert hit(stranger, method, url, body).status_code == 404, url
    assert Status.objects.get().views.count() == 0 and not Message.objects.exists() and not StatusReport.objects.exists()
    assert hit(cli, "post", f"/handy/statuses/{sid}/view/", {}).status_code == 200            # le contact, lui, y accède


def test_an_excluded_member_gets_nothing_even_for_an_extended_status_and_exclusion_is_reversible():
    pro, cli = pair("pm_x")
    sid = post(pro, "ouvert à tous sauf exclus", audience="extended").json()["status"]["id"]
    api(pro).post("/handy/statuses/exclusions/", {"user": cli.id}, format="json")
    stranger_excluded = _client("pm_x_out")
    api(pro).post("/handy/statuses/exclusions/", {"user": stranger_excluded.id}, format="json")
    for who in (cli, stranger_excluded):
        f = feed(who)
        assert f["contacts"] == [] and f["discover_count"] == 0
        assert api(who).get("/handy/statuses/discover/").json()["results"] == []
        for method, url, body in endpoints(sid):
            assert hit(who, method, url, body).status_code == 404, url
    api(pro).delete(f"/handy/statuses/exclusions/{stranger_excluded.id}/")
    assert api(stranger_excluded).get("/handy/statuses/discover/").json()["results"][0]["author"]["id"] == pro.id


def test_exclusion_is_one_way_and_does_not_hide_the_excluded_members_own_statuses_from_the_author():
    pro, cli = pair("pm_ow")
    post(pro, "de l'auteur")
    mine = post(cli, "du membre exclu").json()["status"]["id"]
    api(pro).post("/handy/statuses/exclusions/", {"user": cli.id}, format="json")
    assert feed(cli)["contacts"] == []
    assert [g["author"]["id"] for g in feed(pro)["contacts"]] == [cli.id]
    assert hit(pro, "post", f"/handy/statuses/{mine}/view/", {}).status_code == 200


def test_blocked_members_cannot_view_reply_report_or_list_viewers_and_unblocking_restores_access():
    pro, cli = pair("pm_b")
    sid = post(pro, "bloqué", audience="extended").json()["status"]["id"]
    api(cli).post("/handy/me/blocks/", {"user": pro.id}, format="json")          # le BLOQUEUR ne voit plus non plus
    for method, url, body in endpoints(sid):
        assert hit(cli, method, url, body).status_code == 404, url
    api(cli).delete(f"/handy/me/blocks/{pro.id}/")
    assert hit(cli, "post", f"/handy/statuses/{sid}/view/", {}).status_code == 200
    api(pro).post("/handy/me/blocks/", {"user": cli.id}, format="json")           # blocage dans l'autre sens
    for method, url, body in endpoints(sid)[:3]:
        assert hit(cli, method, url, body).status_code == 404, url


def test_staff_and_superusers_have_no_special_access_to_member_statuses():
    from django.contrib.auth import get_user_model

    User = get_user_model()
    pro, cli = pair("pm_s")
    sid = post(pro, "privé", audience="contacts").json()["status"]["id"]
    api(cli).post(f"/handy/statuses/{sid}/view/")
    legacy = User.objects.create_user("pm_s_legacy", "pm_l@x.test", "pass1234", is_staff=True)
    root = User.objects.create_superuser("pm_s_root", "pm_r@x.test", "pass1234")
    for staff_user in (legacy, root):
        assert feed(staff_user)["contacts"] == [] and api(staff_user).get("/handy/statuses/discover/").json()["results"] == []
        for method, url, body in endpoints(sid):
            assert hit(staff_user, method, url, body).status_code == 404, url
        assert api(staff_user).delete(f"/handy/statuses/{sid}/").status_code == 404      # ni suppression par les accès membres
    assert Status.objects.get(pk=sid).deleted_at is None


def test_statuses_of_inactive_accounts_and_unauthenticated_requests():
    pro, cli = pair("pm_i")
    sid = post(pro, "compte suspendu", audience="extended").json()["status"]["id"]
    assert len(feed(cli)["contacts"]) == 1
    pro.is_active = False
    pro.save()
    services.bump()
    assert feed(cli)["contacts"] == [] and hit(cli, "post", f"/handy/statuses/{sid}/view/", {}).status_code == 404
    anon = APIClient()
    for url in ("/handy/statuses/", "/handy/statuses/feed/", "/handy/statuses/discover/", f"/handy/statuses/{sid}/viewers/"):
        assert anon.get(url).status_code in (401, 403), url
    assert anon.post(f"/handy/statuses/{sid}/view/").status_code in (401, 403)


def test_viewers_are_never_listed_to_the_members_who_viewed_even_with_the_extended_audience():
    pro = artisan("pm_v_pro")
    a, b = _client("pm_v_a"), _client("pm_v_b")
    sid = post(pro, "lecteurs privés", audience="extended").json()["status"]["id"]
    for u in (a, b):
        api(u).post(f"/handy/statuses/{sid}/view/")
    assert api(pro).get(f"/handy/statuses/{sid}/viewers/").json()["counters"]["unique"] == 2
    for u in (a, b):
        assert api(u).get(f"/handy/statuses/{sid}/viewers/").status_code == 404
