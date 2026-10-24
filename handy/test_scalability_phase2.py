"""Scalabilité, phase 2 : rétention des notifications (purge par lots, protections), « près de moi » (tri plus-proche-voisin identique
au tri par distance, total plafonné), push réservé atomiquement (jamais deux envois), plafonds SMS anti-fraude inchangés."""
from datetime import timedelta
from unittest import mock

import pytest
from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.utils import timezone

from handy import notifications
from handy.models import Notification, User

pytestmark = pytest.mark.django_db
ABIDJAN = (5.36, -3.99)


def _note(user, *, days, read=True, category="booking", push_status="sent", **extra):
    n = Notification.objects.create(user=user, notification_type="booking_confirmed", category=category, message="x", is_read=read,
                                    push_status=push_status, **extra)
    Notification.objects.filter(pk=n.pk).update(created_at=timezone.now() - timedelta(days=days))
    return n.pk


# ── Rétention des notifications ────────────────────────────────────────────────────────────────────────────────────────

def test_retention_is_disabled_by_default_and_never_deletes_anything(settings):
    user = User.objects.create_user(username="ret0", password="pass1234")
    _note(user, days=900)
    assert settings.NOTIFICATION_RETENTION_DAYS == 0
    assert notifications.purge() == {"enabled": False, "deleted": 0}
    assert Notification.objects.filter(user=user).count() == 1


def test_purge_by_batches_keeps_recent_unread_protected_and_unsent(settings):
    settings.NOTIFICATION_RETENTION_DAYS, settings.NOTIFICATION_PURGE_BATCH = 180, 2
    user = User.objects.create_user(username="ret1", password="pass1234")
    old = [_note(user, days=200 + i) for i in range(5)]
    kept = {
        "récente": _note(user, days=10),
        "non lue": _note(user, days=400, read=False),
        "paiement": _note(user, days=400, category="payment"),
        "compte": _note(user, days=400, category="account"),
        "engagement": _note(user, days=400, category="engagement"),
        "push en file": _note(user, days=400, push_status="queued"),
        "push en cours": _note(user, days=400, push_status="sending"),
    }
    preview = notifications.purge(dry_run=True)
    assert preview["would_delete"] == 5 and Notification.objects.filter(pk__in=old).count() == 5
    result = notifications.purge()
    assert result == {"enabled": True, "deleted": 5, "batches": 3, "complete": True}
    assert not Notification.objects.filter(pk__in=old).exists()
    assert set(Notification.objects.values_list("pk", flat=True)) == set(kept.values())


def test_unread_notifications_need_their_own_retention_and_a_run_is_bounded(settings):
    settings.NOTIFICATION_RETENTION_DAYS, settings.NOTIFICATION_UNREAD_RETENTION_DAYS = 90, 365
    settings.NOTIFICATION_PURGE_BATCH, settings.NOTIFICATION_PURGE_MAX_BATCHES = 1, 1
    user = User.objects.create_user(username="ret2", password="pass1234")
    young_unread, old_unread = _note(user, days=200, read=False), _note(user, days=400, read=False)
    old_read = _note(user, days=100)
    first = notifications.purge()
    assert first["deleted"] == 1 and first["complete"] is False          # une seule passe bornée : la suite au prochain passage
    notifications.purge()
    assert list(Notification.objects.values_list("pk", flat=True)) == [young_unread]
    assert not Notification.objects.filter(pk__in=[old_unread, old_read]).exists()


def test_the_purge_command_previews_without_deleting(capsys):
    user = User.objects.create_user(username="ret3", password="pass1234")
    _note(user, days=400)
    call_command("notifications_purge", "--dry-run", "--days", "180")
    assert "1 notification(s) seraient supprimées" in capsys.readouterr().out
    assert Notification.objects.filter(user=user).count() == 1


def test_an_announcement_delivery_survives_the_purge_of_its_notification(settings):
    from announcements.models import Announcement, AnnouncementDelivery

    settings.NOTIFICATION_RETENTION_DAYS = 30
    user = User.objects.create_user(username="ret4", password="pass1234")
    a = Announcement.objects.create(title="T", body="B", to_clients=True, status="published", published_at=timezone.now())
    n = _note(user, days=60, category="announcement")
    delivery = AnnouncementDelivery.objects.create(announcement=a, user=user, notification_id=n)
    notifications.purge()
    delivery.refresh_from_db()
    assert delivery.notification_id is None                                   # la livraison (vue, clic) reste ; seul le lien est retiré


# ── « Près de moi » ────────────────────────────────────────────────────────────────────────────────────────────────────

def _nearby_setup(make_handyman, make_service, make_category, n):
    category = make_category("plomberie-knn")
    for i in range(n):
        km = 0.5 + i * 0.7
        pro = make_handyman(f"knn{i}", approved=True, location=Point(ABIDJAN[1] + km / 111.2, ABIDJAN[0], srid=4326),
                            rating=float(i % 3))
        make_service(pro, category, title=f"Offre {i}", price=str(1000 + (i * 37) % 500))
        make_service(pro, category, title=f"Offre bis {i}", price=str(1000 + (i * 53) % 500))
    return category


def test_nearest_neighbour_order_is_exactly_the_distance_order(make_handyman, make_service, make_category, api_client):
    from django.contrib.gis.db.models.functions import Distance
    from django.db.models import F

    from handy.api import views

    _nearby_setup(make_handyman, make_service, make_category, 8)
    origin = Point(ABIDJAN[1], ABIDJAN[0], srid=4326)
    knn = list(views.search_services_nearby_qs(origin, None, 20).values_list("pk", flat=True))
    exact = list(views.search_services_nearby_qs(origin, None, 20).order_by(
        Distance("handyman__handyman_profile__location", origin), "-handyman__handyman_profile__rating",
        F("price").asc(nulls_last=True), "id").values_list("pk", flat=True))
    assert len(knn) == 16 and knn == exact
    r = api_client.get(f"/handy/services/nearby/?lat={ABIDJAN[0]}&lng={ABIDJAN[1]}&radius_km=20&page_size=100")
    rows = r.json()["results"]
    assert [row["id"] for row in rows] == knn
    assert [row["distance_km"] for row in rows] == sorted(row["distance_km"] for row in rows)


def test_the_nearby_total_is_capped_and_says_so(make_handyman, make_service, make_category, api_client, monkeypatch):
    from handy.api import views

    _nearby_setup(make_handyman, make_service, make_category, 6)       # 12 offres
    url = f"/handy/services/nearby/?lat={ABIDJAN[0]}&lng={ABIDJAN[1]}&radius_km=20&page_size=5"
    body = api_client.get(url).json()
    assert (body["count"], body["count_capped"], len(body["results"])) == (12, False, 5)
    monkeypatch.setattr(views, "NEARBY_COUNT_CAP", 10)
    body = api_client.get(url).json()
    assert (body["count"], body["count_capped"]) == (10, True)
    page2 = api_client.get(url + "&page=2").json()
    assert len(page2["results"]) == 5 and page2["next"] is None          # dernière page servie : celle du plafond
    assert api_client.get(url + "&page=3").status_code == 404           # au-delà du plafond : non servi


# ── Push : réservation atomique ────────────────────────────────────────────────────────────────────────────────────────

def test_two_runs_of_the_same_push_task_never_send_twice():
    from handy import push
    from handy.tasks import send_notification_push

    user = User.objects.create_user(username="push2", password="pass1234")
    n = Notification.objects.create(user=user, notification_type="booking_confirmed", category="booking", message="x", push_status="queued")
    with mock.patch.object(push, "send_to_user", return_value={"sent": 1, "removed": 0, "failed": 0, "devices": 1, "skipped": None}) as send:
        first = send_notification_push.apply(args=(n.pk,)).get()
        second = send_notification_push.apply(args=(n.pk,)).get()
    assert first["status"] == "sent" and second == {"skipped": "already_processed"} and send.call_count == 1
    # Exécution concurrente : la seconde ne peut pas réserver une notification déjà réservée.
    other = Notification.objects.create(user=user, notification_type="booking_confirmed", category="booking", message="y", push_status="queued")
    Notification.objects.filter(pk=other.pk).update(push_status="sending")
    with mock.patch.object(push, "send_to_user") as send:
        assert send_notification_push.apply(args=(other.pk,)).get() == {"skipped": "already_processed"}
    assert send.call_count == 0


def test_a_transient_failure_returns_the_notification_to_the_queue_for_the_retry():
    from celery.exceptions import Retry

    from handy import push
    from handy.tasks import send_notification_push

    user = User.objects.create_user(username="push3", password="pass1234")
    n = Notification.objects.create(user=user, notification_type="booking_confirmed", category="booking", message="x", push_status="queued")
    with mock.patch.object(push, "send_to_user", return_value={"sent": 0, "removed": 0, "failed": 1, "devices": 1, "skipped": None}), \
            mock.patch.object(send_notification_push, "retry", side_effect=Retry()):
        with pytest.raises(Retry):
            send_notification_push.run(n.pk)
    n.refresh_from_db()
    assert n.push_status == "queued"


# ── Files Celery et plafonds anti-fraude ──────────────────────────────────────────────────────────────────────────────

def test_flash_tasks_and_sms_alerts_have_their_own_queues():
    from tratra.celery import app

    route = lambda name: app.amqp.router.route({}, name)["queue"].name   # noqa: E731
    assert route("flash.tasks.wave_timeout") == route("flash.tasks.tick") == route("flash.tasks.close_offers") == "flash"
    assert route("handy.tasks.notify_arrival_imminent") == "otp"
    assert route("announcements.tasks.deliver_announcement") == route("trust.tasks.reevaluate_all_profiles") == "bulk"
    assert route("handy.tasks.notify_booking_status") == "default"
    assert settings.CELERY_TASK_IGNORE_RESULT is True


def test_sms_anti_fraud_caps_are_unchanged_and_never_raised_automatically():
    """Plafonds par défaut inchangés (les tests les neutralisent : on lit donc les réglages eux-mêmes), et aucun code ne les modifie à
    l'exécution : un relèvement reste une décision de l'exploitant (variable d'environnement)."""
    import re
    from pathlib import Path

    root = Path(settings.BASE_DIR)
    base = (root / "tratra/settings/base.py").read_text(encoding="utf-8")
    expected = {"SMS_GLOBAL_HOURLY_LIMIT": 30, "SMS_GLOBAL_DAILY_LIMIT": 150, "SMS_PER_NUMBER_HOURLY_LIMIT": 3, "SMS_PER_NUMBER_DAILY_LIMIT": 6,
                "SMS_PER_IP_HOURLY_LIMIT": 5, "SMS_PER_IP_DAILY_LIMIT": 15, "SMS_PER_USER_DAILY_LIMIT": 8, "SIGNUP_GLOBAL_HOURLY_LIMIT": 60,
                "SIGNUP_PER_IP_HOURLY_LIMIT": 5, "SIGNUP_PER_IP_DAILY_LIMIT": 20, "SIGNUP_PHONE_RANGE_DAILY_LIMIT": 5}
    for name, value in expected.items():
        assert re.search(rf"^{name} = config\('{name}', default={value}, cast=int\)", base, re.M), name
    writers = [str(p.relative_to(root)) for p in root.rglob("*.py")
               if p.parts[len(root.parts)] not in ("venv", ".venv", ".claude", "node_modules", "frontend")
               and not p.name.startswith("test_") and p.name != "conftest.py" and "settings" not in p.parts
               and re.search(r"settings\.(SMS|SIGNUP)_[A-Z_]*LIMIT\s*=", p.read_text(encoding="utf-8", errors="ignore"))]
    assert writers == []
