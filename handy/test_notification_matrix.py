"""Matrice de notifications du PILOTE : missions, messages, annonces, espèces, contrats et échéances — de l'événement métier au push FCM.

FCM est simulé (aucune requête réelle) ; le chemin complet est exercé : événement → `notify` → tâche Celery d'envoi → appareils. Chaque
push porte un lien profond que l'application sait ouvrir ; un rejeu n'envoie jamais deux fois ; l'auteur d'une action n'est jamais notifié.
(Les rappels de maintenance Business et les cas fins de chaque famille ont leurs tests dédiés : business/, announcements/, engagements/.)"""
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.test import override_settings
from django.utils import timezone

from announcements import services as announcement_services
from announcements.models import Announcement
from engagements import tasks as engagement_tasks
from engagements.testing import make_contract, person, pro
from handy import push
from handy.models import Booking, CashDeclaration, Conversation, Device, Message, Notification, User
from handy.notifications import CATEGORY_BY_TYPE, CHANNEL_BY_CATEGORY, deeplink
from handy.services import cash as cash_svc
from handy.test_eligibility import artisan, service
from handy.test_push import FakeHTTP, service_account  # noqa: F401  (fixture partagée)

pytestmark = pytest.mark.django_db

# Types d'objets que l'application mobile sait ouvrir (miroir de `_kind` dans lib/core/deep_links.dart).
APP_DEEPLINK_KINDS = {"booking", "mission", "conversation", "reviews", "kyc", "business_request", "announcement", "contract", "posting", "replacements", "notifications"}
# Types réservés : déclarés mais volontairement jamais émis aujourd'hui.
RESERVED_TYPES = {"profile_completed"}


@pytest.fixture(autouse=True)
def _reset():
    push.reset_cache()
    yield
    push.reset_cache()


def sent(http):
    return [kw["json"]["message"] for url, kw in http.calls if "fcm.googleapis.com" in url]


def by(messages, token):
    return [m for m in messages if m["token"] == token]


def test_every_notification_type_has_a_category_a_channel_and_a_producer():
    types = [t for t, _ in Notification.TYPES]
    assert all(t in CATEGORY_BY_TYPE for t in types), [t for t in types if t not in CATEGORY_BY_TYPE]
    assert {CATEGORY_BY_TYPE[t] for t in types} <= set(CHANNEL_BY_CATEGORY) | {"system"}
    root = Path(__file__).resolve().parents[1]
    corpus = ""
    for path in root.rglob("*.py"):
        parts = path.relative_to(root).parts
        if parts[0] in ("venv", ".venv", "node_modules", "frontend", "staticfiles") or "migrations" in parts or "tests" in parts or path.name.startswith("test_") or path.name == "conftest.py":
            continue
        if "/".join(parts) in ("handy/models.py", "handy/notifications.py"):
            continue
        corpus += path.read_text(encoding="utf-8")
    # Les notifications « live » sont composées (`live_` + en_route|arrived) : même producteur, deux types.
    dynamic = {"live_en_route", "live_arrived"}
    orphans = [t for t in types if t not in RESERVED_TYPES | dynamic and not re.search(r"['\"]%s['\"]" % t, corpus)]
    assert orphans == [], f"type de notification sans producteur : {orphans}"


def test_pilot_scenario_missions_messages_announcements_cash_and_contracts_reach_the_phones(service_account, monkeypatch, django_capture_on_commit_callbacks):
    path, _ = service_account
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)
    client = User.objects.create_user("mx_client", "mxc@x.test", "pass1234", user_type="client", is_verified=True, first_name="Awa")
    worker = artisan("mx_pro")
    worker.first_name = "Moussa"
    worker.save(update_fields=["first_name"])
    Device.objects.create(user=client, device_token="tok-client", device_type="ios")
    Device.objects.create(user=worker, device_token="tok-pro", device_type="android")
    svc = service(worker)

    with override_settings(FCM_CREDENTIALS_FILE=path):
        # ── Mission : demande → acceptée → démarrée → terminée ─────────────────────────────────────────────────────
        with django_capture_on_commit_callbacks(execute=True):
            b = Booking.objects.create(client=client, handyman=worker, service=svc, address="Cocody", city="Abidjan", booking_date=timezone.now() + timedelta(days=1),
                                       total_price=Decimal("10000"))
        assert [m["data"]["deeplink"] for m in by(sent(http), "tok-pro")] == [f"tratra://mission/{b.pk}"]         # l'artisan reçoit la demande
        assert by(sent(http), "tok-client") == []                                                               # jamais l'auteur de la demande
        http.calls.clear()
        for status in ("confirmed", "in_progress"):
            with django_capture_on_commit_callbacks(execute=True):
                b.refresh_from_db()
                b.transition_to(status, actor=worker)
        client_pushes = by(sent(http), "tok-client")
        assert [m["data"]["deeplink"] for m in client_pushes] == [f"tratra://booking/{b.pk}"] * 2                 # confirmée puis démarrée : lien vers SA réservation
        assert all(m["android"]["priority"] == "high" and m["apns"]["headers"]["apns-priority"] == "10" for m in client_pushes)
        assert by(sent(http), "tok-pro") == []

        # ── Message : le destinataire seulement, lien vers la conversation ───────────────────────────────────────────
        http.calls.clear()
        conversation = Conversation.objects.create(booking=b)
        conversation.participants.add(client, worker)
        with django_capture_on_commit_callbacks(execute=True):
            Message.objects.create(conversation=conversation, sender=client, content="Le portail est ouvert.")
        pro_msgs = by(sent(http), "tok-pro")
        assert len(pro_msgs) == 1 and pro_msgs[0]["data"]["deeplink"].startswith("tratra://conversation/") and by(sent(http), "tok-client") == []
        assert pro_msgs[0]["data"]["id"] == str(conversation.pk) or pro_msgs[0]["data"]["deeplink"].endswith(f"/{conversation.pk}")

        # ── Espèces : déclaration → la contrepartie est invitée à confirmer ──────────────────────────────────────────
        http.calls.clear()
        with django_capture_on_commit_callbacks(execute=True):
            decl = cash_svc.declare(b, worker, {"amount": "10000"})
        assert [m["data"]["deeplink"] for m in by(sent(http), "tok-client")] == [f"tratra://booking/{b.pk}"] and by(sent(http), "tok-pro") == []
        assert Notification.objects.get(user=client, notification_type="cash_declared").category == "payment"
        http.calls.clear()
        with django_capture_on_commit_callbacks(execute=True):
            cash_svc.respond(decl, client, True)
        assert [m["data"]["deeplink"] for m in by(sent(http), "tok-pro")] == [f"tratra://mission/{b.pk}"]

        # ── Terminée : le client est invité à laisser un avis ───────────────────────────────────────────────────────
        http.calls.clear()
        with django_capture_on_commit_callbacks(execute=True):
            b.refresh_from_db()
            b.transition_to("completed", actor=worker)
        done = by(sent(http), "tok-client")
        assert len(done) == 1 and "avis" in done[0]["notification"]["body"].lower()

        # ── Annonce : programmée, publiée par la tâche, livrée UNE fois ──────────────────────────────────────────────
        http.calls.clear()
        a = Announcement.objects.create(title="Nouveau service", body="Découvrez nos nouveautés.", kind="service", to_clients=True, to_artisans=True)
        with django_capture_on_commit_callbacks(execute=True):
            announcement_services.publish(a)
        assert {m["token"] for m in sent(http)} == {"tok-client", "tok-pro"}
        assert all(m["data"]["deeplink"] == f"tratra://announcement/{a.pk}" and m["android"]["notification"]["channel_id"] == "tratra_announcements" for m in sent(http))
        http.calls.clear()
        with django_capture_on_commit_callbacks(execute=True):
            assert announcement_services.deliver(a.pk) == 0                                                     # rejeu : aucune double livraison
        assert sent(http) == []

    # Tout lien profond émis par ce scénario est ouvrable par l'application.
    for n in Notification.objects.exclude(data={}):
        assert n.data.get("kind") in APP_DEEPLINK_KINDS and deeplink(n.data).startswith(f"tratra://{n.data['kind']}")
    assert Notification.objects.filter(user=worker, notification_type="cash_confirmed").exists()               # l'auteur est informé de la réponse…
    assert not Notification.objects.filter(user=worker, notification_type="cash_declared").exists()            # …mais jamais de sa propre déclaration


def test_contract_and_monthly_installment_reminders_reach_both_phones_once(service_account, monkeypatch, django_capture_on_commit_callbacks):
    path, _ = service_account
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)
    today = timezone.localdate()
    owner, worker = person("mx_owner"), pro("mx_worker")
    Device.objects.create(user=owner, device_token="tok-owner", device_type="android")
    Device.objects.create(user=worker, device_token="tok-worker", device_type="ios")
    with override_settings(FCM_CREDENTIALS_FILE=path):
        with django_capture_on_commit_callbacks(execute=True):
            c = make_contract(owner, worker, start=today, today=today, months=12)
            engagement_tasks.run(today)
        proposed = [m for m in sent(http) if m["data"].get("kind") == "contract"]
        assert {m["token"] for m in proposed} == {"tok-owner", "tok-worker"}                                    # proposition, acceptation, activation
        assert all(m["data"]["deeplink"] == f"tratra://contract/{c.pk}" for m in proposed)
        inst = c.installments.order_by("sequence").first()
        http.calls.clear()
        with django_capture_on_commit_callbacks(execute=True):
            engagement_tasks.run(inst.due_date - timedelta(days=2))
            engagement_tasks.run(inst.due_date - timedelta(days=2))                                             # rejeu du tick
        due = [m for m in sent(http) if m["data"].get("kind") == "contract"]
        assert {m["token"] for m in due} == {"tok-owner", "tok-worker"} and len(due) == 2                       # une fois chacun
    assert Notification.objects.filter(user=owner, notification_type="installment_due").count() == 1
