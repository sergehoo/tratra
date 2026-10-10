"""Échéances mensuelles → notification → push FCM : le téléphone reçoit chaque rappel UNE fois, avec le lien profond du contrat.
FCM est simulé (aucune requête réelle) ; le chemin complet (tick → notify → tâche d'envoi → appareils) est exercé."""
from datetime import timedelta

import pytest
from django.test import override_settings

from engagements import tasks
from engagements.testing import make_contract, person, pro
from handy import push
from handy.models import Device, Notification
from handy.test_push import FakeHTTP, service_account  # noqa: F401  (fixture partagée)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset():
    push.reset_cache()
    yield
    push.reset_cache()


def sent_messages(http):
    return [kw["json"]["message"] for url, kw in http.calls if "fcm.googleapis.com" in url]


def test_installment_reminders_reach_both_phones_once_with_the_contract_deeplink(service_account, monkeypatch, django_capture_on_commit_callbacks):
    path, _ = service_account
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)
    from django.utils import timezone

    today = timezone.localdate()
    owner, worker = person("pf_owner"), pro("pf_worker")
    Device.objects.create(user=owner, device_token="tok-owner", device_type="android")
    Device.objects.create(user=worker, device_token="tok-worker", device_type="ios")
    with override_settings(FCM_CREDENTIALS_FILE=path):
        with django_capture_on_commit_callbacks(execute=True):
            c = make_contract(owner, worker, start=today, today=today, months=12)
            tasks.run(today)
        inst = c.installments.order_by("sequence").first()
        http.calls.clear()
        with django_capture_on_commit_callbacks(execute=True):
            tasks.run(inst.due_date - timedelta(days=2))             # « échéance à venir »
        first = sent_messages(http)
        by_token = {m["token"]: m for m in first if m["data"].get("kind") == "contract"}
        assert {"tok-owner", "tok-worker"} <= set(by_token)
        for message in by_token.values():
            assert message["data"]["deeplink"] == f"tratra://contract/{c.pk}" and message["data"]["id"] == str(c.pk)
            assert message["android"]["priority"] == "high" and message["apns"]["headers"]["apns-priority"] == "10"
            assert message["notification"]["title"] and "Échéance" in message["notification"]["body"]
            assert "@" not in message["notification"]["body"] and "+225" not in message["notification"]["body"]      # aucune coordonnée dans un push
        http.calls.clear()
        with django_capture_on_commit_callbacks(execute=True):
            tasks.run(inst.due_date - timedelta(days=2)); tasks.run(inst.due_date - timedelta(days=1))              # rejeu du tick : pas de second envoi
        assert [m for m in sent_messages(http) if m["data"].get("kind") == "contract"] == []
        due = Notification.objects.filter(user=owner, notification_type="installment_due")
        assert due.count() == 1 and due.first().push_status in ("sent", "queued")
        # Retard : une alerte distincte, une seule fois.
        http.calls.clear()
        with django_capture_on_commit_callbacks(execute=True):
            tasks.run(inst.due_date + timedelta(days=7))
            tasks.run(inst.due_date + timedelta(days=8))
        late = [m for m in sent_messages(http) if m["data"].get("kind") == "contract" and "retard" in m["notification"]["title"].lower()]
        assert {m["token"] for m in late} == {"tok-owner", "tok-worker"} and len(late) == 2


def test_notification_preferences_still_apply_to_engagement_pushes(service_account, monkeypatch, django_capture_on_commit_callbacks):
    from handy.notifications import set_preferences
    from django.utils import timezone

    path, _ = service_account
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)
    today = timezone.localdate()
    owner, worker = person("pf_owner2"), pro("pf_worker2")
    Device.objects.create(user=worker, device_token="tok-w2", device_type="android")
    set_preferences(worker, {"engagement": False})                       # le prestataire coupe le push « contrats » : l'historique in-app reste
    with override_settings(FCM_CREDENTIALS_FILE=path):
        with django_capture_on_commit_callbacks(execute=True):
            make_contract(owner, worker, start=today, today=today, months=12)
            tasks.run(today)
    assert [m for m in sent_messages(http) if m["token"] == "tok-w2"] == []
    assert Notification.objects.filter(user=worker, category="engagement").exists()
