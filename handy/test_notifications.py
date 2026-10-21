"""Centre de notifications : historique persistant, déduplication, préférences, push asynchrone multi-appareils,
déclencheurs transactionnels et isolation entre utilisateurs. Le serveur FCM est simulé (aucun envoi réel)."""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from handy import notifications, push
from handy.models import (
    Booking, Conversation, Device, Dispute, HandymanDocument, MarketingConsent, Message, Notification,
    NotificationPreference, Payment, Review,
)
from handy.tasks import notify_booking_status, send_notification_push
from handy.test_push import FakeHTTP, service_account  # noqa: F401  (fixture)

User = get_user_model()
pytestmark = pytest.mark.django_db


def user(name, kind="client"):
    return User.objects.create_user(username=name, email=f"{name}@ex.com", password="pass1234", user_type=kind, is_verified=True)


def booking(client, artisan, status="pending"):
    return Booking.objects.create(client=client, handyman=artisan, status=status, booking_date=timezone.now() + timedelta(days=1),
                                  address="Rue 1", city="Abidjan", postal_code="00225")


def api(u):
    c = APIClient()
    c.force_authenticate(u)
    return c


def mine(u, **kw):
    return Notification.objects.filter(user=u, **kw)


# ── Création, déduplication, catégories ────────────────────────────────────────────────────────────────────────────

def test_notify_stores_history_with_category_title_and_deeplink(django_capture_on_commit_callbacks):
    u = user("n_hist")
    with django_capture_on_commit_callbacks(execute=False):
        n = notifications.notify(u, "booking_confirmed", "Votre réservation est confirmée.", title="Réservation confirmée",
                                 data={"kind": "booking", "id": 12})
    assert (n.category, n.title, n.is_read, n.push_status) == ("booking", "Réservation confirmée", False, "queued")
    assert notifications.deeplink(n.data) == "tratra://booking/12"
    assert notifications.deeplink({"kind": "reviews"}) == "tratra://reviews"
    assert notifications.deeplink({}) == "tratra://notifications"


def test_same_event_never_notifies_twice():
    u = user("n_dedupe")
    first = notifications.notify(u, "booking_confirmed", "m", dedupe_key="booking:1:confirmed")
    again = notifications.notify(u, "booking_confirmed", "m", dedupe_key="booking:1:confirmed")
    assert first is not None and again is None
    assert mine(u).count() == 1
    other = user("n_dedupe2")                      # la clé est propre à chaque destinataire
    assert notifications.notify(other, "booking_confirmed", "m", dedupe_key="booking:1:confirmed") is not None


def test_booking_status_task_replayed_does_not_duplicate():
    c, a = user("n_rep_c"), user("n_rep_a", "handyman")
    b = booking(c, a, "confirmed")
    Notification.objects.all().delete()
    notify_booking_status(b.id, "confirmed")
    notify_booking_status(b.id, "confirmed")       # rejeu Celery
    assert mine(c).count() == 1 and mine(a).count() == 1


# ── Préférences ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_preferences_default_on_and_account_category_is_locked():
    u = user("n_pref")
    prefs = {p["category"]: p for p in notifications.preferences_for(u)}
    assert all(p["push_enabled"] for p in prefs.values())
    assert prefs["account"]["locked"] is True
    notifications.set_preferences(u, {"review": False, "account": False})
    assert notifications.push_enabled(u, "review") is False
    assert notifications.push_enabled(u, "account") is True            # vérification d'identité : jamais coupée
    with pytest.raises(ValueError):
        notifications.set_preferences(u, {"inconnue": True})


# ── Push asynchrone multi-appareils ─────────────────────────────────────────────────────────────────────────────────

def _devices(u):
    Device.objects.create(user=u, device_token="tok-a1", device_type="android")
    Device.objects.create(user=u, device_token="tok-a2", device_type="android")
    Device.objects.create(user=u, device_token="tok-i1", device_type="ios")
    Device.objects.create(user=u, device_token="tok-web", device_type="web")


def test_push_goes_to_every_mobile_device_with_deeplink_channel_and_badge(service_account, monkeypatch, django_capture_on_commit_callbacks):
    path, _ = service_account
    u = user("n_push")
    _devices(u)
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)
    with override_settings(FCM_CREDENTIALS_FILE=path, CELERY_TASK_ALWAYS_EAGER=True):
        with django_capture_on_commit_callbacks(execute=True):
            n = notifications.notify(u, "message_received", "Bonjour, à quelle heure ?", title="Moussa",
                                     data={"kind": "conversation", "id": 5}, dedupe_key="message:1", collapse_key="conversation-5")
    n.refresh_from_db()
    assert n.push_status == "sent" and n.push_sent_at is not None
    fcm = [kw["json"]["message"] for url, kw in http.calls if "fcm.googleapis.com" in url]
    assert {m["token"] for m in fcm} == {"tok-a1", "tok-a2", "tok-i1"}          # 3 appareils mobiles, jamais « web »
    m = fcm[0]
    # Écran verrouillé : texte neutre, jamais le contenu du message (aperçu activable par l'exploitant : PUSH_MESSAGE_PREVIEW).
    assert m["notification"] == {"title": "Nouveau message", "body": "Moussa vous a écrit."}
    assert m["android"]["notification"]["visibility"] == "PRIVATE"
    assert m["data"]["deeplink"] == "tratra://conversation/5" and m["data"]["nid"] == str(n.pk) and m["data"]["cat"] == "message"
    assert m["android"]["notification"]["channel_id"] == "tratra_activity" and m["android"]["notification"]["tag"] == "conversation-5"
    assert m["apns"]["payload"]["aps"]["badge"] == 1                           # compteur de non lues
    assert m["apns"]["headers"]["apns-collapse-id"] == "conversation-5"


def test_push_replayed_task_does_not_send_twice(service_account, monkeypatch, django_capture_on_commit_callbacks):
    path, _ = service_account
    u = user("n_once")
    Device.objects.create(user=u, device_token="tok-once", device_type="android")
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)
    with override_settings(FCM_CREDENTIALS_FILE=path, CELERY_TASK_ALWAYS_EAGER=True):
        with django_capture_on_commit_callbacks(execute=True):
            n = notifications.notify(u, "booking_confirmed", "ok", title="t", dedupe_key="k1")
        send_notification_push(n.pk)                 # rejeu manuel de la tâche
        send_notification_push(n.pk)
    assert len([1 for url, _ in http.calls if "fcm.googleapis.com" in url]) == 1


def test_push_states_without_firebase_without_device_and_when_disabled(service_account, monkeypatch, django_capture_on_commit_callbacks):
    path, _ = service_account
    u, v, w = user("n_s1"), user("n_s2"), user("n_s3")
    Device.objects.create(user=u, device_token="tok-s1", device_type="android")
    with override_settings(CELERY_TASK_ALWAYS_EAGER=True):
        with django_capture_on_commit_callbacks(execute=True):
            sans_firebase = notifications.notify(u, "booking_confirmed", "m", dedupe_key="s1")
    sans_firebase.refresh_from_db()
    assert sans_firebase.push_status == "unconfigured"                         # jamais d'erreur, l'historique reste
    monkeypatch.setattr(push.requests, "post", FakeHTTP().post)
    with override_settings(FCM_CREDENTIALS_FILE=path, CELERY_TASK_ALWAYS_EAGER=True):
        with django_capture_on_commit_callbacks(execute=True):
            sans_appareil = notifications.notify(v, "booking_confirmed", "m", dedupe_key="s2")
            notifications.set_preferences(w, {"booking": False})
            coupe = notifications.notify(w, "booking_confirmed", "m", dedupe_key="s3")
    sans_appareil.refresh_from_db(); coupe.refresh_from_db()
    assert sans_appareil.push_status == "no_device" and coupe.push_status == "disabled"
    assert mine(w).count() == 1                                                # coupé côté push seulement : historique conservé


def test_payload_errors_do_not_delete_the_device_but_dead_tokens_do(service_account, monkeypatch):
    path, _ = service_account
    u = user("n_dead")
    Device.objects.create(user=u, device_token="tok-ok", device_type="android")
    monkeypatch.setattr(push.requests, "post", FakeHTTP(400, {"error": {"status": "INVALID_ARGUMENT", "message": "Invalid value at message.data"}}).post)
    with override_settings(FCM_CREDENTIALS_FILE=path):
        push.send_to_user(u.id, "t", "b", {"a": "b"})
    assert Device.objects.filter(device_token="tok-ok").exists()               # charge utile fautive : appareil conservé
    monkeypatch.setattr(push.requests, "post", FakeHTTP(400, {"error": {"status": "INVALID_ARGUMENT", "message": "The registration token is not a valid FCM registration token"}}).post)
    with override_settings(FCM_CREDENTIALS_FILE=path):
        out = push.send_to_user(u.id, "t", "b", {"a": "b"})
    assert out["removed"] == 1 and not Device.objects.filter(device_token="tok-ok").exists()


def test_transient_fcm_failures_are_counted_for_retry(service_account, monkeypatch):
    path, _ = service_account
    u = user("n_retry")
    Device.objects.create(user=u, device_token="tok-r", device_type="android")
    monkeypatch.setattr(push.requests, "post", FakeHTTP(503, {"error": {"status": "UNAVAILABLE"}}).post)
    with override_settings(FCM_CREDENTIALS_FILE=path):
        out = push.send_to_user(u.id, "t", "b")
    assert out["failed"] == 1 and out["sent"] == 0 and Device.objects.filter(device_token="tok-r").exists()


# ── Déclencheurs transactionnels ────────────────────────────────────────────────────────────────────────────────────

def test_booking_lifecycle_notifies_the_counterparty_with_role_specific_links():
    c, a = user("n_l_c"), user("n_l_a", "handyman")
    b = booking(c, a)
    req = mine(a, notification_type="booking_request").get()
    assert req.data == {"kind": "mission", "id": b.id, "audience": "artisan"} and not mine(c).exists()   # l'auteur n'est pas notifié

    b.transition_to("confirmed", actor=a)
    conf = mine(c, notification_type="booking_confirmed").get()
    assert conf.data["kind"] == "booking" and conf.title == "Réservation confirmée"
    notify_booking_status(b.id, "confirmed", a.id)                      # signal → tâche : acteur exclu
    assert not mine(a, notification_type="booking_confirmed").exists()

    b.transition_to("cancelled", actor=c)
    assert mine(a, notification_type="booking_cancelled").get().data["kind"] == "mission"
    assert not mine(c, notification_type="booking_cancelled").exists()


def test_message_notifies_other_participants_only_and_collapses_per_conversation():
    c, a = user("n_m_c"), user("n_m_a", "handyman")
    conv = Conversation.objects.create()
    conv.participants.add(c, a)
    m = Message.objects.create(conversation=conv, sender=c, content="Pouvez-vous passer à 10 h ?")
    n = mine(a, notification_type="message_received").get()
    assert n.data == {"kind": "conversation", "id": conv.id} and "10 h" in n.message and n.title == c.first_name or n.title
    assert not mine(c).exists() and m.pk


def test_review_kyc_payment_and_dispute_events():
    c, a = user("n_e_c"), user("n_e_a", "handyman")
    b = booking(c, a, "completed")
    Notification.objects.all().delete()
    review = Review.objects.create(booking=b, rating=5, comment="Parfait")
    assert mine(a, notification_type="review_received").count() == 1
    from handy.notification_events import review_replied
    review_replied(review)
    assert mine(c, notification_type="review_reply").count() == 1

    doc = HandymanDocument.objects.create(handyman=a.handyman_profile, document_type="id_card", file="kyc/x.pdf")
    doc.approve(by=a)
    doc.reject(by=a, reason="Photo floue")
    assert mine(a, notification_type="kyc_approved").count() == 1
    assert "Photo floue" in mine(a, notification_type="kyc_rejected").get().message

    pay = Payment.objects.create(booking=b, amount=15000, platform_fee=1500, method="cash", status="held")
    pay.release()
    assert "13500" in mine(a, notification_type="payment_received").get().message
    b2 = booking(c, a, "cancelled")
    refund = Payment.objects.create(booking=b2, amount=10000, platform_fee=1000, method="cash", status="held")
    refund.refund(amount=8000)
    assert mine(c, notification_type="refund_issued").count() == 1

    d = Dispute.objects.create(booking=b, reporter=c, reason="Travail non conforme")
    assert mine(a, notification_type="dispute_opened").count() == 1 and not mine(c, notification_type="dispute_opened").exists()
    d.status = "resolved"; d.save()
    assert mine(c, notification_type="dispute_resolved").count() == 1 and mine(a, notification_type="dispute_resolved").count() == 1
    d.save()                                                              # nouvelle sauvegarde : aucun doublon
    assert mine(c, notification_type="dispute_resolved").count() == 1


# ── API : historique, filtres, compteur, lecture, préférences, isolation ──────────────────────────────────────────

def test_api_list_filters_counter_and_mark_read():
    u = user("n_api")
    notifications.notify(u, "booking_confirmed", "a", dedupe_key="1", push=False)
    notifications.notify(u, "message_received", "b", dedupe_key="2", push=False)
    notifications.notify(u, "review_received", "c", dedupe_key="3", push=False)
    c = api(u)
    assert c.get("/handy/notifications/").json()["count"] == 3
    only = c.get("/handy/notifications/?category=message").json()["results"]
    assert [n["category"] for n in only] == ["message"] and only[0]["deeplink"] == "tratra://notifications"
    counter = c.get("/handy/notifications/unread-count/").json()
    assert counter["unread"] == 3 and counter["by_category"] == {"booking": 1, "message": 1, "review": 1}
    first = c.get("/handy/notifications/").json()["results"][0]
    assert c.patch(f"/handy/notifications/{first['id']}/", {"is_read": True}, format="json").json()["is_read"] is True
    assert c.get("/handy/notifications/?is_read=false").json()["count"] == 2
    assert c.post("/handy/notifications/mark-read/", {"category": "booking"}, format="json").json() == {"updated": 1, "unread": 1}
    assert c.post("/handy/notifications/mark-read/", {}, format="json").json()["unread"] == 0
    assert c.get("/handy/me/dashboard/").json()["counts"]["notifications"] == 0 if "counts" in c.get("/handy/me/dashboard/").json() else True


def test_api_cannot_create_edit_or_read_other_users_notifications_even_as_staff():
    a, b, staff = user("n_iso_a"), user("n_iso_b"), user("n_iso_s")
    staff.is_staff = True; staff.save()
    na = notifications.notify(a, "booking_confirmed", "secret A", dedupe_key="x", push=False)
    ca, cb, cs = api(a), api(b), api(staff)
    assert ca.post("/handy/notifications/", {"notification_type": "system", "message": "faux"}, format="json").status_code == 405
    assert cb.get(f"/handy/notifications/{na.pk}/").status_code == 404
    assert cb.patch(f"/handy/notifications/{na.pk}/", {"is_read": True}, format="json").status_code == 404
    assert cb.delete(f"/handy/notifications/{na.pk}/").status_code == 404
    assert cs.get("/handy/notifications/").json()["count"] == 0          # le personnel ne lit pas l'historique d'autrui ici
    assert cb.post("/handy/notifications/mark-read/", {"ids": [na.pk]}, format="json").json()["updated"] == 0
    na.refresh_from_db()
    assert na.is_read is False
    assert "secret A" not in str(cb.get("/handy/notifications/unread-count/").json())


def test_api_preferences_and_marketing_consent_with_audit():
    from trust.models import AuditEvent

    u = user("n_prefapi")
    c = api(u)
    body = c.get("/handy/me/notification-preferences/").json()
    assert {p["category"] for p in body["preferences"]} >= {"booking", "message", "payment", "live", "review", "account", "announcement"}
    assert body["marketing_consent"]["granted"] is False
    out = c.put("/handy/me/notification-preferences/", {"preferences": {"review": False, "account": False}}, format="json").json()
    prefs = {p["category"]: p for p in out["preferences"]}
    assert prefs["review"]["push_enabled"] is False and prefs["account"]["push_enabled"] is True
    assert c.put("/handy/me/notification-preferences/", {"preferences": {"zzz": True}}, format="json").status_code == 400
    assert c.put("/handy/me/notification-preferences/", {"preferences": {"review": "oui"}}, format="json").status_code == 400
    assert c.put("/handy/me/marketing-consent/", {"granted": True, "source": "app"}, format="json").json()["granted"] is True
    assert c.put("/handy/me/marketing-consent/", {"granted": True}, format="json").status_code == 200   # idempotent
    assert c.put("/handy/me/marketing-consent/", {"granted": False}, format="json").json()["granted"] is False
    actions = list(AuditEvent.objects.filter(target_type="user", target_id=u.pk).values_list("action", flat=True))
    assert actions.count("marketing_consent.granted") == 1 and actions.count("marketing_consent.revoked") == 1
    assert MarketingConsent.objects.get(user=u).revoked_at is not None
