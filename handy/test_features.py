"""Fonctions récentes (handy.features) : registre cohérent avec les écrans, capacités annoncées par l'application conservées à
l'enregistrement du téléphone, comptes atteignables (téléphone à jour ou site seulement) et push réservé aux téléphones à jour —
y compris pour une annonce manuelle dont le bouton ouvre une fonction récente. Le serveur FCM est simulé."""
import pytest

from announcements.models import Announcement
from announcements.test_announcements import account, api
from announcements.test_destinations_push import _fcm
from handy import destinations, features, push
from handy.models import Device, Notification
from handy.tasks import send_notification_push
from handy.test_push import FakeHTTP, service_account  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db

# Codes annoncés par l'application à jour (lib/services/push_service.dart, appFeatures) : même liste des deux côtés.
APP_FEATURES = {"flash", "favorites", "tratra_id", "engagements", "panne", "catalogue_families", "service_modes"}


def test_registry_matches_the_app_and_points_to_real_screens():
    assert set(features.BY_CODE) == APP_FEATURES
    assert all(len(code) <= 20 for code in features.BY_CODE)               # limite d'une capacité d'appareil
    for key, code in features.DESTINATION_FEATURE.items():
        assert key in destinations.BY_KEY and code in features.BY_CODE
    assert features.for_destination("panne") == {"panne"} and features.for_destination("badge") == {"tratra_id"}
    assert features.for_destination("category/4") == set() and features.for_destination("") == set()
    assert features.unknown(["panne", "", "teleportation"]) == ["teleportation"]


def test_the_app_announces_its_features_and_unknown_ones_are_dropped():
    u = account("feat_reg")
    caps = ["flash1", "rich1", *sorted(APP_FEATURES), "inconnue"]
    r = api(u).post("/handy/devices/", {"device_token": "tok-feat", "device_type": "android", "capabilities": caps}, format="json")
    assert r.status_code in (200, 201), r.json()
    assert Device.objects.get(device_token="tok-feat").capabilities == sorted({"flash1", "rich1", *APP_FEATURES})
    again = api(u).post("/handy/devices/", {"device_token": "tok-feat", "device_type": "android", "capabilities": ["flash1"]}, format="json")
    assert again.status_code == 200 and Device.objects.get(device_token="tok-feat").capabilities == ["flash1"]   # chaque démarrage fait foi


def test_reachable_accounts_have_an_up_to_date_phone_or_no_phone_at_all():
    web, ready, old, mixed = (account(f"feat_{n}") for n in ("web", "ready", "old", "mixed"))
    Device.objects.create(user=ready, device_token="r-1", device_type="android", capabilities=["panne"])
    Device.objects.create(user=old, device_token="o-1", device_type="android", capabilities=["rich1"])
    Device.objects.create(user=mixed, device_token="m-1", device_type="android", capabilities=[])
    Device.objects.create(user=mixed, device_token="m-2", device_type="ios", capabilities=["panne"])
    Device.objects.create(user=old, device_token="o-web", device_type="web", capabilities=["panne"])   # le site n'est pas un téléphone
    ids = [web.pk, ready.pk, old.pk, mixed.pk]
    assert features.reachable_user_ids(ids, {"panne"}) == {web.pk, ready.pk, mixed.pk}
    assert features.reachable_user_ids(ids, set()) == set(ids)
    assert features.adoption({"panne"}) == {"phones": 4, "ready": 2}


def test_a_manual_announcement_opening_a_recent_feature_pushes_only_to_up_to_date_phones(service_account, monkeypatch):
    path, _ = service_account
    u = account("feat_push")
    Device.objects.create(user=u, device_token="p-new", device_type="android", capabilities=["rich1", "panne"])
    Device.objects.create(user=u, device_token="p-old", device_type="android", capabilities=["rich1"])
    a = Announcement.objects.create(title="Une panne ?", body="Décrivez-la.", status="published", to_clients=True, kind="service",
                                    action_kind="deeplink", action_value="panne", action_label="J'ai une panne", send_push=True)
    n = Notification.objects.create(user=u, notification_type="announcement", category="announcement", message="Décrivez-la.",
                                    data={"kind": "announcement", "id": a.pk}, push_status="queued")
    sent = _fcm(monkeypatch, path, lambda: send_notification_push(n.pk))
    assert [m["token"] for m in sent] == ["p-new"]
    assert Notification.objects.get(pk=n.pk).push_status == "sent"

    Device.objects.filter(device_token="p-new").delete()
    n2 = Notification.objects.create(user=u, notification_type="announcement", category="announcement", message="Décrivez-la.",
                                     data={"kind": "announcement", "id": a.pk}, push_status="queued")
    assert _fcm(monkeypatch, path, lambda: send_notification_push(n2.pk)) == []
    assert Notification.objects.get(pk=n2.pk).push_status == "outdated_app"


def test_require_capabilities_never_reaches_a_phone_lacking_one(service_account, monkeypatch):
    path, _ = service_account
    u = account("feat_req")
    Device.objects.create(user=u, device_token="q-1", device_type="android", capabilities=["flash", "favorites"])
    Device.objects.create(user=u, device_token="q-2", device_type="ios", capabilities=["flash"])
    http = FakeHTTP()
    monkeypatch.setattr(push.requests, "post", http.post)
    from django.test import override_settings

    with override_settings(FCM_CREDENTIALS_FILE=path):
        result = push.send_to_user(u.pk, "T", "B", require_capabilities=["flash", "favorites"])
    tokens = [kw["json"]["message"]["token"] for url, kw in http.calls if "fcm.googleapis.com" in url]
    assert tokens == ["q-1"] and result["sent"] == 1 and result["devices"] == 2
