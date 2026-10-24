"""Diffusion d'une annonce à grande échelle : par lots (quelques requêtes par lot au lieu de huit par compte), audience jamais chargée
en entier, une seule livraison et une seule notification par compte même rejouée, push sur la file « bulk » pour ne jamais retarder
les alertes de mission ni les messages."""
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from announcements import services
from announcements.models import Announcement, AnnouncementDelivery
from handy import notifications
from handy.models import Notification

User = get_user_model()
pytestmark = pytest.mark.django_db


def _accounts(n, prefix):
    return User.objects.bulk_create([User(username=f"{prefix}{i}", user_type="client", is_verified=True)
                                     for i in range(n)])


def _published(**over):
    fields = dict(title="Nouveauté", body="Découvrez Tratra Flash.", kind="service", to_clients=True, send_push=False,
                  status="published", published_at=timezone.now())
    fields.update(over)
    return Announcement.objects.create(**fields)


def test_delivery_cost_grows_with_the_number_of_batches_not_of_accounts(monkeypatch):
    monkeypatch.setattr(services, "BATCH", 50)
    _accounts(30, "petit")
    a = _published()
    with CaptureQueriesContext(connection) as small:
        assert services.deliver(a.pk) == 30
    _accounts(170, "grand")
    b = _published()
    with CaptureQueriesContext(connection) as large:
        assert services.deliver(b.pk) == 200
    assert len(large) <= len(small) * 4 + 5          # 4 lots au lieu d'1 ; l'ancien code faisait ~8 requêtes par compte
    assert len(large) < 200


def test_each_account_gets_exactly_one_delivery_and_one_notification_even_when_replayed(monkeypatch, django_capture_on_commit_callbacks):
    monkeypatch.setattr(services, "BATCH", 7)
    users = _accounts(20, "rejeu")
    a = _published(send_push=True)
    with mock.patch("handy.tasks.send_notification_push.apply_async") as enqueue, django_capture_on_commit_callbacks(execute=True):
        assert services.deliver(a.pk) == 20
        assert services.deliver(a.pk) == 0                       # rejeu de la tâche : rien de neuf, aucun push de plus
    assert enqueue.call_count == 20
    assert {c.kwargs["queue"] for c in enqueue.call_args_list} == {"bulk"}
    deliveries = AnnouncementDelivery.objects.filter(announcement=a)
    assert deliveries.count() == 20 and not deliveries.filter(notification__isnull=True).exists()
    for u in users:
        n = Notification.objects.get(user=u, dedupe_key=f"announcement:{a.pk}")
        assert n.push_status == "queued" and n.category == "announcement" and deliveries.get(user=u).notification_id == n.pk


def test_a_cancelled_announcement_stops_between_batches(monkeypatch):
    monkeypatch.setattr(services, "BATCH", 5)
    _accounts(12, "annule")
    a = _published()
    real = services._deliver_chunk

    def cancel_after_first(announcement_id, ids):
        done = real(announcement_id, ids)
        Announcement.objects.filter(pk=announcement_id).update(status="cancelled")
        return done
    monkeypatch.setattr(services, "_deliver_chunk", cancel_after_first)
    assert services.deliver(a.pk) == 5


def test_mission_alerts_and_messages_never_wait_behind_a_mass_announcement(django_capture_on_commit_callbacks):
    user = _accounts(1, "file_push")[0]
    with mock.patch("handy.tasks.send_notification_push.apply_async") as enqueue, django_capture_on_commit_callbacks(execute=True):
        notifications.notify(user, "new_mission", "Nouvelle mission", dedupe_key="m1")
        notifications.notify(user, "message_received", "Bonjour", dedupe_key="m2")
        notifications.notify(user, "announcement", "Promo", dedupe_key="m3")
    assert [c.kwargs["queue"] for c in enqueue.call_args_list] == ["notifications", "notifications", "bulk"]
