"""Modération des statuts signalés : droits, filtres, contenu consultable (et journalisé), retrait motivé, classement sans suite,
cas limites (déjà supprimé par l'auteur, déjà traité) et absence d'effet sur les autres statuts."""
import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from backoffice.test_people import BO, api, audited, staff
from handy.models import Notification
from handy.test_booking_regression import _client
from handy.test_messaging import link
from handy.testing import make_jpeg
from statuses.models import Status, StatusReport
from statuses.test_statuses import api as member_api, pair, post

pytestmark = pytest.mark.django_db
URL = f"{BO}/statuses"


@pytest.fixture(autouse=True)
def _tmp_media(settings, tmp_path):
    """Médias de test dans un dossier temporaire (jamais dans `media/` du dépôt)."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def report(reporter, status_id, reason="Contenu choquant"):
    return member_api(reporter).post(f"/handy/statuses/{status_id}/report/", {"reason": reason}, format="json")


def photo(user, text="Photo signalée"):
    return post(user, text, SimpleUploadedFile("p.jpg", make_jpeg(), "image/jpeg")).json()["status"]["id"]


def test_only_moderators_can_use_the_status_moderation_screens():
    pro, cli = pair("sm_perm")
    sid = post(pro, "x").json()["status"]["id"]
    report(cli, sid)
    rid = StatusReport.objects.get().pk
    for who in (None, cli, staff("sm_perm_analyst", "analyst"), staff("sm_perm_fin", "finance")):
        a = api(who) if who else APIClient()
        assert a.get(f"{URL}/reports/").status_code in (401, 403)
        assert a.get(f"{URL}/{sid}/").status_code in (401, 403)
        assert a.post(f"{URL}/{sid}/remove/", {"reason": "motif valable"}, format="json").status_code in (401, 403)
        assert a.post(f"{URL}/reports/{rid}/dismiss/", {"reason": "motif valable"}, format="json").status_code in (401, 403)
    assert api(staff("sm_perm_ok", "support")).get(f"{URL}/reports/").status_code == 200


def test_report_list_filters_search_and_never_exposes_contact_details():
    pro, cli = pair("sm_list")
    pro2 = pair("sm_list2")[0]
    s1, s2 = post(pro, "Promo trompeuse").json()["status"]["id"], post(pro2, "Autre contenu").json()["status"]["id"]
    report(cli, s1, "Publicité mensongère")
    mod = staff("sm_list_mod", "support")
    rows = api(mod).get(f"{URL}/reports/").json()["results"]
    assert len(rows) == 1 and rows[0]["text"] == "Promo trompeuse" and rows[0]["state"] == "active" and rows[0]["resolved"] is False
    assert "phone" not in str(rows) and "email" not in str(rows)
    assert api(mod).get(f"{URL}/reports/?q=mensongère").json()["count"] == 1
    assert api(mod).get(f"{URL}/reports/?q=introuvable").json()["count"] == 0
    assert api(mod).get(f"{URL}/reports/?q={s1}").json()["count"] == 1
    assert api(mod).get(f"{URL}/reports/?resolved=true").json()["count"] == 0
    assert api(mod).get(f"{URL}/reports/?resolved=all").json()["count"] == 1
    assert api(mod).get(f"{URL}/reports/?from=2999-01-01").json()["count"] == 0


def test_moderator_sees_the_reported_content_and_each_consultation_is_audited():
    pro, cli = pair("sm_view")
    sid = photo(pro)
    report(cli, sid)
    mod = staff("sm_view_mod", "support")
    d = api(mod).get(f"{URL}/{sid}/").json()
    assert d["text"] == "Photo signalée" and d["media"]["url"] and d["media"]["mime"] == "image/jpeg" and d["reports"][0]["reason"] == "Contenu choquant"
    assert d["author"]["id"] == pro.id and "phone" not in str(d)
    assert audited("status.viewed", actor=mod).count() == 1
    unreported = post(pro, "jamais signalé").json()["status"]["id"]
    assert api(mod).get(f"{URL}/{unreported}/").status_code == 404           # seuls les statuts SIGNALÉS sont consultables par la modération
    assert api(mod).get(f"{URL}/999999/").status_code == 404


def test_removal_requires_a_reason_deletes_content_media_notifies_author_and_closes_all_reports(django_capture_on_commit_callbacks):
    pro, cli = pair("sm_rm")
    cli2 = _client("sm_rm_cli2")
    link(pro, cli2)
    sid = photo(pro)
    other = post(pro, "autre statut du même auteur").json()["status"]["id"]
    report(cli, sid)
    report(cli2, sid, "Atteinte à la vie privée")
    name = Status.objects.get(pk=sid).media.name
    mod = staff("sm_rm_mod", "support")
    short = api(mod).post(f"{URL}/{sid}/remove/", {"reason": "ok"}, format="json")
    assert short.status_code == 400 and short.json()["fields"]["reason"]
    assert Status.objects.get(pk=sid).deleted_at is None
    with django_capture_on_commit_callbacks(execute=True):
        assert api(mod).post(f"{URL}/{sid}/remove/", {"reason": "Contenu contraire aux règles"}, format="json").status_code == 200
    st = Status.objects.get(pk=sid)
    assert st.deleted_at and st.removed_by_staff and st.text == "" and not st.media and not default_storage.exists(name)
    assert Status.objects.get(pk=other).deleted_at is None                  # les autres statuts de l'auteur ne sont pas touchés
    assert StatusReport.objects.filter(status_id=sid, is_resolved=True).count() == 2
    assert Notification.objects.filter(user=pro, title="Statut retiré").count() == 1
    ev = audited("status.removed", actor=mod).get()
    assert ev.data["reason"] == "Contenu contraire aux règles" and "p.jpg" not in str(ev.data)
    again = api(mod).post(f"{URL}/{sid}/remove/", {"reason": "Contenu contraire aux règles"}, format="json")
    assert again.status_code == 409 and again.json()["code"] == "already"
    row = api(mod).get(f"{URL}/reports/?resolved=true").json()["results"][0]
    assert row["state"] == "removed_by_staff" and row["text"] == "" and row["has_media"] is False


def test_dismissing_a_report_keeps_the_status_and_is_recorded_with_the_decision():
    pro, cli = pair("sm_dis")
    sid = post(pro, "Statut conforme").json()["status"]["id"]
    report(cli, sid)
    rid = StatusReport.objects.get().pk
    mod = staff("sm_dis_mod", "support")
    assert api(mod).post(f"{URL}/reports/{rid}/dismiss/", {}, format="json").status_code == 400
    assert api(mod).post(f"{URL}/reports/{rid}/dismiss/", {"reason": "Aucune infraction constatée"}, format="json").status_code == 200
    assert Status.objects.get(pk=sid).deleted_at is None and member_api(cli).get("/handy/statuses/feed/").json()["contacts"]
    assert audited("status.report_dismissed", actor=mod).get().data["reason"] == "Aucune infraction constatée"
    assert api(mod).post(f"{URL}/reports/{rid}/dismiss/", {"reason": "Aucune infraction constatée"}, format="json").status_code == 409
    assert api(mod).post(f"{URL}/reports/9999/dismiss/", {"reason": "Aucune infraction constatée"}, format="json").status_code == 404


def test_reported_status_deleted_by_its_author_keeps_only_the_report_and_cannot_be_removed_twice():
    pro, cli = pair("sm_del")
    sid = post(pro, "Je vais le supprimer").json()["status"]["id"]
    report(cli, sid)
    member_api(pro).delete(f"/handy/statuses/{sid}/")
    mod = staff("sm_del_mod", "support")
    d = api(mod).get(f"{URL}/{sid}/").json()
    assert d["state"] == "deleted_by_author" and d["text"] == "" and d["media"] is None
    r = api(mod).post(f"{URL}/{sid}/remove/", {"reason": "Déjà supprimé par l'auteur"}, format="json")
    assert r.status_code == 409
    assert StatusReport.objects.get().is_resolved is True                    # le signalement ne reste pas ouvert indéfiniment
