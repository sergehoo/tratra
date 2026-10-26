"""Engagement automatisé : déclencheurs sur des événements réels, ciblage (audience, communes, progression), idempotence, consentement
et désinscription, limite hebdomadaire de push, heures autorisées, priorité opérationnelle, arrêt dès l'objectif atteint, nouveautés
réservées aux applications qui les ont, bibliothèque des 30 modèles, compatibilité FCM et Back-Office. Le serveur FCM est simulé."""
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone

from announcements import services as announcement_services
from announcements.models import Announcement, AnnouncementDelivery
from announcements.test_announcements import account, api, draft, staff
from announcements.test_destinations_push import _fcm
from campaigns import engine, library, triggers
from campaigns.models import Campaign, CampaignSend
from flash.models import MissionRequest
from handy import notifications
from handy.models import Booking, Device, HandymanDocument, Notification, Review, ServiceCategory, UserAddress
from handy.tasks import send_notification_push
from handy.test_eligibility import service
from handy.test_push import FakeHTTP, service_account  # noqa: F401  (fixture)
from handy.testing import make_eligible

User = get_user_model()
pytestmark = pytest.mark.django_db
URL = "/handy/backoffice/campaigns/"
ABIDJAN = ZoneInfo("Africa/Abidjan")


@pytest.fixture(autouse=True)
def _rules(settings):
    settings.CAMPAIGN_SEND_HOURS = "0-24"        # heures autorisées testées à part
    settings.CAMPAIGN_PUSH_WEEKLY_LIMIT = 2


def later(hours=3):
    """« Maintenant » du moteur, après les notifications créées par les comptes de test (priorité opérationnelle : 2 h)."""
    return timezone.now() + timedelta(hours=hours)


def joined(user, when):
    User.objects.filter(pk=user.pk).update(date_joined=when)


def pro(name, *, eligible=False, city=None):
    u = account(name, "handyman", city)
    if eligible:
        make_eligible(u.handyman_profile)
    return User.objects.get(pk=u.pk)


def complete_client(u):
    User.objects.filter(pk=u.pk).update(first_name="Awa", last_name="Koné")
    UserAddress.objects.create(user=u, city="Abidjan", commune="Cocody", is_primary=True)


def campaign(key, trigger="welcome", audience="clients", *, active=True, **over):
    fields = dict(key=key, name=key, trigger=trigger, audience=audience, title="Bonjour", body="Un message utile.", action_label="Voir",
                  action_value="home", delay_hours=0, min_gap_hours=0, marketing=False)
    fields.update(over)
    c = Campaign.objects.create(**fields)
    return engine.set_active(c, True) if active else c


def booking(client, artisan, status="completed", **over):
    return Booking.objects.create(client=client, handyman=artisan, service=service(artisan), address="Cocody", city="Abidjan",
                                  booking_date=timezone.now() - timedelta(days=2), status=status, total_price=Decimal("10000"), **over)


def sends(c):
    return CampaignSend.objects.filter(campaign=c).order_by("pk")


# ── Bibliothèque ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_library_installs_30_disabled_templates_valid_for_their_audience():
    keys = [t["key"] for t in library.TEMPLATES]
    assert len(keys) == len(set(keys)) == 30
    rows = Campaign.objects.filter(key__in=keys)
    assert rows.count() == 30 and not rows.filter(is_active=True).exists()
    assert library.seed() == 0                                            # idempotent : rien de réécrit
    assert {r.trigger for r in rows} == set(dict(Campaign.TRIGGERS))      # chaque déclencheur a au moins un modèle
    assert {r.audience for r in rows} == {"clients", "artisans", "companies"}
    for c in rows:
        engine.validate(c)                                                # écran ouvert à l'audience, déclencheur compatible
        assert len(c.title) <= 140 and len(c.body) <= 600 and len(c.action_label) <= 40
    assert all(c.feature for c in rows.filter(trigger="news"))            # une nouveauté désigne toujours sa fonction
    gated = {c.key for c in rows if engine.required_features(c)}
    assert gated >= {"bienvenue-client", "premiere-commande-j1", "inactif-client-30", "nouveau-j-ai-une-panne"}   # Flash, panne
    for c in rows:
        assert engine.set_active(c, True).is_active                       # tout est activable : les nouveautés attendent les applis à jour


def test_an_unknown_feature_cannot_be_announced():
    c = campaign("t-feature-unknown", "news", feature="teleportation", active=False)
    with pytest.raises(ValidationError, match="Fonction inconnue : teleportation"):
        engine.set_active(c, True)


def test_a_feature_news_waits_for_accounts_whose_app_cannot_open_it_yet():
    c = campaign("t-feature", "news", feature="favorites", action_value="flash_order", max_age_days=7)
    assert engine.required_features(c) == {"favorites", "flash"}
    web = account("ft_web")                                                # aucun téléphone : le site a la fonction
    ready = account("ft_ready")
    Device.objects.create(user=ready, device_token="ft-ready", device_type="android", capabilities=["rich1", "flash", "favorites"])
    old = account("ft_old")                                                # ancienne version de l'application
    Device.objects.create(user=old, device_token="ft-old", device_type="android", capabilities=["flash1", "rich1"])
    half = account("ft_half")                                              # une seule des deux fonctions
    Device.objects.create(user=half, device_token="ft-half", device_type="ios", capabilities=["flash"])
    both = account("ft_both")                                              # un vieux téléphone et un à jour
    Device.objects.create(user=both, device_token="ft-both-old", device_type="android", capabilities=[])
    Device.objects.create(user=both, device_token="ft-both-new", device_type="ios", capabilities=["favorites", "flash"])
    now = later(1)
    mine = {web.pk, ready.pk, old.pk, half.pk, both.pk}
    assert engine.schedule(c, now) >= 3
    assert set(sends(c).values_list("user_id", flat=True)) & mine == {web.pk, ready.pk, both.pk}
    assert engine.audience(c, now)["waiting_update"] >= 2 and engine.audience(c, now)["new"] == 0
    Device.objects.filter(device_token="ft-old").update(capabilities=["flash1", "rich1", "flash", "favorites"])   # mise à jour
    assert engine.schedule(c, later(2)) >= 1
    assert set(sends(c).values_list("user_id", flat=True)) & mine == {web.pk, ready.pk, both.pk, old.pk}


def test_the_destination_and_the_trigger_must_suit_the_audience():
    c = campaign("t-dest", active=False, action_value="reputation")      # écran réservé aux artisans
    with pytest.raises(ValidationError, match="artisans"):
        engine.set_active(c, True)
    c.action_value, c.trigger = "home", "kyc_pending"
    c.save()
    with pytest.raises(ValidationError, match="ne concerne pas"):
        engine.set_active(c, True)


# ── Déclencheurs et ciblage ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_welcome_targets_verified_accounts_of_the_audience_once_the_delay_has_passed():
    now = later()
    c = campaign("t-welcome", delay_hours=24)
    ok, unverified, too_soon, too_old = account("w_ok"), account("w_unv"), account("w_soon"), account("w_old")
    artisan, team = pro("w_pro"), staff("w_staff")
    User.objects.filter(pk__in=[unverified.pk, team.pk]).update(is_verified=True)
    User.objects.filter(pk=unverified.pk).update(is_verified=False)
    for u in (ok, unverified, artisan, team):
        joined(u, now - timedelta(hours=30))
    joined(too_soon, now - timedelta(hours=2))
    joined(too_old, now - timedelta(days=20))
    assert engine.audience_estimate(c, now) == 1
    assert engine.schedule(c, now) == 1
    assert engine.schedule(c, now) == 0                                   # rejeu : rien de nouveau
    assert engine.audience_estimate(c, now) == 0                          # déjà programmé : plus compté
    assert [s.user.username for s in sends(c)] == ["w_ok"]


def test_targeting_by_declared_commune_and_by_progress():
    now = later()
    c = campaign("t-target", communes=["Cocody"], progress=["profile_complete"])
    a, b, d = account("tg_a", city="Cocody"), account("tg_b", city="cocody"), account("tg_c", city="Yopougon")
    complete_client(a)
    complete_client(d)
    for u in (a, b, d):
        joined(u, now - timedelta(hours=1))
    assert engine.schedule(c, now) == 1                                   # b : profil incomplet ; d : autre commune
    assert sends(c).get().user_id == a.pk


def test_progress_reflects_the_real_state_of_the_account():
    client = account("pg_client")
    assert triggers.progress_of(client) == "verified"
    complete_client(client)
    assert triggers.progress_of(User.objects.get(pk=client.pk)) == "profile_complete"
    assert triggers.progress_of(pro("pg_new")) == "verified"
    ready = pro("pg_ready", eligible=True)
    assert triggers.progress_of(ready) == "publishable"
    service(ready)
    assert triggers.progress_of(ready) == "active"


def test_profile_reminder_stops_as_soon_as_the_profile_is_complete():
    now = later()
    c = campaign("t-profile", "profile_incomplete")
    pending, done = account("pi_pending"), account("pi_done")
    complete_client(done)
    for u in (pending, done):
        joined(u, now - timedelta(hours=1))
    assert engine.schedule(c, now) == 1                                   # objectif déjà atteint : rien de programmé
    complete_client(pending)                                              # complété avant l'envoi
    assert engine.dispatch(now) == {"goal_met": 1}
    assert sends(c).get().status == "goal_met"
    assert not Notification.objects.filter(user=pending, notification_type="campaign").exists()


def test_kyc_reminder_stops_once_the_id_is_sent_and_a_refusal_triggers_once_per_document():
    now = later()
    c = campaign("t-kyc", "kyc_pending", "artisans", action_value="kyc")
    p = pro("kyc_pro")
    joined(p, now - timedelta(hours=1))
    assert engine.schedule(c, now) == 1
    HandymanDocument.objects.create(handyman=p.handyman_profile, document_type="id_card", file="kyc/a.pdf", status="pending")
    assert engine.dispatch(now) == {"goal_met": 1}

    rejected = campaign("t-kyc-rej", "kyc_rejected", "artisans", action_value="kyc", delay_hours=1)
    q = pro("kyc_rej")
    doc = HandymanDocument.objects.create(handyman=q.handyman_profile, document_type="id_card", file="kyc/b.pdf", status="rejected",
                                          reviewed_at=now - timedelta(hours=2), rejection_reason="Photo floue")
    assert engine.schedule(rejected, now) == 1 and engine.schedule(rejected, now) == 0
    assert sends(rejected).get().ref == f"doc:{doc.pk}"
    assert engine.dispatch(now) == {"sent": 1}
    HandymanDocument.objects.create(handyman=q.handyman_profile, document_type="id_card", file="kyc/c.pdf", status="pending")
    assert engine.mark_conversions(now) == 1                              # nouvelle pièce transmise après le message


def test_first_service_and_first_order_target_only_accounts_that_have_not_done_it():
    now = later()
    first_service = campaign("t-first-service", "first_service", "artisans", action_value="pro")
    with_offer, without = pro("fs_with", eligible=True), pro("fs_without", eligible=True)
    service(with_offer)
    first_order = campaign("t-first-order", "first_order", action_value="explore")
    newcomer, customer = account("fo_new"), account("fo_customer")
    booking(customer, with_offer)
    for u in (with_offer, without, newcomer, customer):
        joined(u, now - timedelta(hours=1))
    assert engine.schedule(first_service, now) == 1 and sends(first_service).get().user_id == without.pk
    assert engine.schedule(first_order, now) == 1 and sends(first_order).get().user_id == newcomer.pk
    MissionRequest.objects.create(client=newcomer, category=ServiceCategory.objects.get(slug="plomberie"), address="Cocody",
                                  scheduled_for=now, is_immediate=True, amount=15000)   # demande Tratra Flash publiée avant l'envoi
    assert engine.dispatch(now) == {"goal_met": 1, "sent": 1}
    service(without)
    assert engine.mark_conversions(now) == 1
    assert engine.stats(first_service)["conversion_rate"] == 1.0


def test_review_request_is_one_message_per_completed_booking_and_stops_once_reviewed():
    now = later()
    c = campaign("t-review", "review", action_value="bookings", delay_hours=2)
    client, artisan = account("rv_client"), pro("rv_pro", eligible=True)
    b1, b2 = booking(client, artisan), booking(client, artisan)
    Booking.objects.filter(pk__in=[b1.pk, b2.pk]).update(updated_at=now - timedelta(hours=3))
    assert engine.schedule(c, now) == 2
    assert sorted(s.ref for s in sends(c)) == sorted([f"booking:{b1.pk}", f"booking:{b2.pk}"])
    Review.objects.create(booking=b1, rating=5)
    assert engine.dispatch(now) == {"goal_met": 1, "sent": 1}
    assert AnnouncementDelivery.objects.filter(user=client).count() == 1  # un seul message dans le flux, remis en avant


def test_inactivity_triggers_once_per_episode_and_counts_the_return():
    now = later()
    c = campaign("t-inactive", "inactive", inactive_days=30, max_age_days=14)
    idle, recent, never = account("in_idle"), account("in_recent"), account("in_never")
    User.objects.filter(pk=idle.pk).update(last_login=now - timedelta(days=31))
    User.objects.filter(pk=recent.pk).update(last_login=now - timedelta(days=2))
    assert engine.schedule(c, now) == 1 and engine.schedule(c, now) == 0
    assert sends(c).get().ref == f"login:{now - timedelta(days=31):%Y%m%d}"
    assert engine.dispatch(now) == {"sent": 1}
    back = now + timedelta(days=1)
    User.objects.filter(pk=idle.pk).update(last_login=back)
    assert engine.mark_conversions(back) == 1
    again = back + timedelta(days=31)                                      # nouvel épisode d'inactivité : nouveau message
    assert engine.schedule(c, again) == 2                                  # idle (nouvel épisode) et recent, devenu inactif à son tour
    assert sends(c).filter(user=idle).count() == 2 and sends(c).filter(user=recent).count() == 1
    assert never.pk not in set(sends(c).values_list("user_id", flat=True))


def test_news_is_sent_once_to_the_audience_during_its_window():
    c = campaign("t-news", "news", max_age_days=7)
    first = account("nw_first")
    assert engine.schedule(c, later(1)) == 1
    late = account("nw_late")
    assert engine.schedule(c, later(24 * 8)) == 0                          # fenêtre terminée
    assert engine.schedule(c, later(2)) == 1 and engine.schedule(c, later(2)) == 0
    assert set(sends(c).values_list("user_id", flat=True)) == {first.pk, late.pk}


# ── Idempotence ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_replaying_the_task_never_duplicates_a_send_a_notification_or_a_delivery():
    now = later()
    c = campaign("t-idem")
    u = account("idem_user")
    joined(u, now - timedelta(hours=1))
    first = engine.tick(now)
    assert first["scheduled"] == 1 and first["sent"] == 1
    second = engine.tick(now)
    assert second["scheduled"] == 0 and "sent" not in second
    send = sends(c).get()
    assert engine.send_one(send.pk, now) == "locked"                       # déjà traité : jamais renvoyé
    assert Notification.objects.filter(user=u, notification_type="campaign").count() == 1
    assert AnnouncementDelivery.objects.filter(user=u, announcement=c.announcement).count() == 1
    with pytest.raises(IntegrityError), transaction.atomic():
        CampaignSend.objects.create(campaign=c, user=u, ref="", due_at=now)


# ── Consentement, désinscription, limites ─────────────────────────────────────────────────────────────────────────────────────

def test_marketing_needs_consent_and_the_tips_category_unsubscribes():
    now = later()
    c = campaign("t-marketing", marketing=True)
    no_consent, consenting, unsubscribed = account("mk_none"), account("mk_yes"), account("mk_out")
    for u in (consenting, unsubscribed):
        notifications.set_marketing_consent(u, True)
    notifications.set_preferences(unsubscribed, {"tips": False})
    for u in (no_consent, consenting, unsubscribed):
        joined(u, now - timedelta(hours=1))
    engine.schedule(c, now)
    assert engine.dispatch(now) == {"no_consent": 1, "sent": 1, "opted_out": 1}
    assert {s.user_id: s.reason for s in sends(c).filter(status="skipped")} == {no_consent.pk: "no_consent", unsubscribed.pk: "opted_out"}
    tips = next(p for p in notifications.preferences_for(consenting) if p["category"] == "tips")
    assert tips["push_enabled"] and not tips["locked"]                     # désinscription possible depuis les préférences
    assert c.announcement.kind == "promotion"
    assert [d.announcement_id for d in announcement_services.feed_for(consenting)] == [c.announcement_id]
    notifications.set_marketing_consent(consenting, False)
    assert not list(announcement_services.feed_for(consenting))            # consentement retiré : le message disparaît


def test_account_information_does_not_need_marketing_consent():
    now = later()
    c = campaign("t-info", marketing=False)
    u = account("info_user")
    joined(u, now - timedelta(hours=1))
    engine.schedule(c, now)
    assert engine.dispatch(now) == {"sent": 1}
    assert c.announcement.kind == "service"


def test_at_most_two_engagement_pushes_per_week_then_in_app_only():
    now = later()
    cs = [campaign(f"t-quota-{i}", priority=i + 1) for i in range(3)]
    u = account("quota_user")
    joined(u, now - timedelta(hours=1))
    assert engine.tick(now)["sent"] == 2
    rows = CampaignSend.objects.filter(user=u).order_by("campaign__priority")
    assert [(r.status, r.push, r.reason) for r in rows] == [("sent", True, ""), ("sent", True, ""), ("sent", False, "push_quota")]
    statuses = list(Notification.objects.filter(user=u, notification_type="campaign").order_by("pk").values_list("push_status", flat=True))
    assert statuses == ["queued", "queued", ""]                            # le 3e reste dans l'application, sans push
    assert engine.pushes_this_week(u.pk, now + timedelta(days=8)) == 0     # la semaine suivante, la limite repart
    assert len(cs) == 3


def test_manual_promotional_pushes_count_in_the_weekly_limit():
    now = later()
    u = account("promo_user")
    for i in range(2):
        promo = draft(title=f"Promo {i}", kind="promotion", send_push=True, status="published")
        AnnouncementDelivery.objects.create(announcement=promo, user=u)
    c = campaign("t-promo-quota")
    joined(u, now - timedelta(hours=1))
    engine.schedule(c, now)
    assert engine.dispatch(now) == {"sent_in_app": 1}
    assert sends(c).get().reason == "push_quota"


def test_messages_wait_for_the_allowed_hours_of_the_local_time_zone(settings):
    settings.CAMPAIGN_SEND_HOURS = "9-20"
    day = (timezone.now() + timedelta(days=2)).astimezone(ABIDJAN).date()
    night = datetime(day.year, day.month, day.day, 21, 30, tzinfo=ABIDJAN)
    assert engine.next_send_time(night) == datetime(day.year, day.month, day.day, 9, tzinfo=ABIDJAN) + timedelta(days=1)
    assert engine.next_send_time(night.replace(hour=7)) == datetime(day.year, day.month, day.day, 9, tzinfo=ABIDJAN)
    assert engine.next_send_time(night.replace(hour=12)) is None
    c = campaign("t-hours")
    u = account("hours_user")
    joined(u, night - timedelta(hours=1))
    engine.schedule(c, night)
    assert engine.dispatch(night) == {"deferred:quiet_hours": 1}
    send = sends(c).get()
    assert send.status == "scheduled" and send.due_at == engine.next_send_time(night) and send.attempts == 1
    assert engine.dispatch(night) == {}                                    # pas encore dû
    assert engine.dispatch(send.due_at) == {"sent": 1}


def test_flash_bookings_and_operational_alerts_take_priority():
    now = later()
    c = campaign("t-busy")
    u, artisan = account("busy_user"), pro("busy_pro", eligible=True)
    joined(u, now - timedelta(hours=1))
    engine.schedule(c, now)
    send = sends(c).get()
    request = MissionRequest.objects.create(client=u, category=ServiceCategory.objects.get_or_create(slug="plomberie", defaults={"name": "Plomberie"})[0],
                                            address="Cocody", scheduled_for=now, is_immediate=True, amount=15000)
    assert engine.send_one(send.pk, now) == "deferred:priority"
    send.refresh_from_db()
    assert send.due_at == now + timedelta(hours=2) and send.reason == "priority"
    MissionRequest.objects.filter(pk=request.pk).update(status=MissionRequest.CANCELLED)
    soon = booking(u, artisan, status="confirmed")
    Booking.objects.filter(pk=soon.pk).update(booking_date=now + timedelta(hours=5))
    assert engine.send_one(send.pk, now) == "deferred:priority"            # réservation dans moins de 24 h
    Booking.objects.filter(pk=soon.pk).update(status="completed")
    notifications.notify(u, "booking_confirmed", "Réservation confirmée", push=False)
    assert engine.send_one(send.pk, timezone.now() + timedelta(minutes=30)) == "deferred:priority"   # alerte opérationnelle récente
    assert engine.send_one(send.pk, now) == "sent"
    other = campaign("t-busy-max")
    engine.schedule(other, now)
    stale = sends(other).get()
    CampaignSend.objects.filter(pk=stale.pk).update(attempts=engine.MAX_DEFERRALS)
    MissionRequest.objects.filter(pk=request.pk).update(status=MissionRequest.SEARCHING)
    assert engine.send_one(stale.pk, now) == "priority"                    # trop de reports : abandonné, jamais envoyé en retard
    assert sends(other).get().status == "skipped"


def test_minimum_gap_between_two_engagement_messages():
    now = later()
    first = campaign("t-gap-a", priority=1)
    second = campaign("t-gap-b", priority=2, min_gap_hours=48)
    u = account("gap_user")
    joined(u, now - timedelta(hours=1))
    out = engine.tick(now)
    assert out["sent"] == 1 and out["deferred:frequency"] == 1
    sent, waiting = sends(first).get(), sends(second).get()
    assert waiting.status == "scheduled" and waiting.due_at == sent.sent_at + timedelta(hours=48)


def test_deactivation_cancels_what_is_scheduled_and_withdraws_the_message():
    now = later()
    c = campaign("t-off")
    reached, waiting = account("off_reached"), account("off_waiting")
    joined(reached, now - timedelta(hours=1))
    joined(waiting, now + timedelta(hours=1))                              # pas encore dans la fenêtre
    engine.tick(now)
    joined(waiting, now - timedelta(hours=1))
    engine.schedule(c, now)
    engine.set_active(c, False)
    assert sends(c).get(user=waiting).status == "cancelled" and sends(c).get(user=waiting).reason == "campaign_inactive"
    assert Announcement.objects.get(pk=c.announcement_id).status == "cancelled"
    assert not list(announcement_services.feed_for(reached))
    assert engine.tick(now)["scheduled"] == 0


# ── Compatibilité FCM ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_campaign_push_reaches_the_app_as_an_announcement_with_its_link_and_button(service_account, monkeypatch, settings,
                                                                                  django_capture_on_commit_callbacks):
    path, _ = service_account
    now = later()
    c = campaign("t-fcm", action_value="panne", action_label="Décrire ma panne", marketing=True, title="Une panne ?")
    u = account("fcm_user")
    notifications.set_marketing_consent(u, True)
    joined(u, now - timedelta(hours=1))
    Device.objects.create(user=u, device_token="tok-c-rich", device_type="android", capabilities=["flash1", "rich1", "panne"])
    Device.objects.create(user=u, device_token="tok-c-old", device_type="android", capabilities=["flash1", "panne"])
    Device.objects.create(user=u, device_token="tok-c-outdated", device_type="android", capabilities=["flash1", "rich1"])

    def run():
        with django_capture_on_commit_callbacks(execute=True):
            engine.tick(now)

    by_token = {m["token"]: m for m in _fcm(monkeypatch, path, run)}
    assert set(by_token) == {"tok-c-rich", "tok-c-old"}                    # l'ancienne version n'a pas l'écran « J'ai une panne »
    rich = by_token["tok-c-rich"]
    assert "notification" not in rich                                      # construit par l'application (récepteur « announcement »)
    assert rich["data"]["t"] == "announcement" and rich["data"]["id"] == str(c.announcement_id) and rich["data"]["cat"] == "tips"
    assert rich["data"]["deeplink"] == "tratra://panne" and rich["data"]["cta"] == "Décrire ma panne"
    assert rich["data"]["title"] == "Une panne ?"
    old = by_token["tok-c-old"]
    assert old["android"]["notification"]["channel_id"] == "tratra_announcements" and old["data"]["deeplink"] == "tratra://panne"
    n = Notification.objects.get(user=u, notification_type="campaign")
    assert n.category == "tips" and n.push_status == "sent" and notifications.push_queue("tips") == "bulk"


def test_no_push_leaves_once_the_campaign_is_off_or_the_user_unsubscribed(service_account, monkeypatch):
    path, _ = service_account
    now = later()
    c = campaign("t-fcm-off")
    a, b = account("fcm_off_a"), account("fcm_off_b")
    for i, u in enumerate((a, b)):
        joined(u, now - timedelta(hours=1))
        Device.objects.create(user=u, device_token=f"tok-off-{i}", device_type="android", capabilities=["rich1"])
    engine.tick(now)                                                       # push en file, pas encore parti
    na, nb = (Notification.objects.get(user=u, notification_type="campaign") for u in (a, b))
    notifications.set_preferences(b, {"tips": False})
    engine.set_active(c, False)
    assert _fcm(monkeypatch, path, lambda: (send_notification_push(na.pk), send_notification_push(nb.pk))) == []
    assert set(Notification.objects.filter(pk__in=[na.pk, nb.pk]).values_list("push_status", flat=True)) == {"disabled"}


# ── Back-Office ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_back_office_engagement_is_reserved_to_marketing():
    assert api().get(URL).status_code in (401, 403)
    assert api(account("cbo_user")).get(URL).status_code == 403
    assert api(staff("cbo_support", "support")).get(URL).status_code == 403
    body = api(staff("cbo_mkt", "marketing")).get(URL).json()
    assert len(body["results"]) == 30 and not any(r["is_active"] for r in body["results"])
    assert body["meta"]["rules"]["weekly_push_limit"] == 2 and body["meta"]["rules"]["sms"] is False
    assert {t["id"] for t in body["meta"]["triggers"]} == set(dict(Campaign.TRIGGERS))
    assert "panne" in {d["key"] for d in body["meta"]["destinations"]}


def test_back_office_edits_previews_activates_and_lists_the_sends(settings):
    mkt = api(staff("cbo_mkt2", "marketing"))
    c = Campaign.objects.get(key="kyc-artisan-j1")
    detail = mkt.get(f"{URL}{c.pk}/").json()
    assert detail["preview"]["push"]["deeplink"] == "tratra://kyc" and detail["preview"]["push"]["channel"] == "tratra_announcements"
    assert detail["preview"]["in_app"]["action"]["web"] and detail["stats"]["sent"] == 0 and detail["goal"]
    assert mkt.patch(f"{URL}{c.pk}/", {"version": c.version + 5, "body": "x"}, format="json").status_code == 409
    r = mkt.patch(f"{URL}{c.pk}/", {"version": c.version, "body": "Envoyez votre pièce d'identité.", "communes": ["Cocody", " "],
                                    "delay_hours": 48}, format="json")
    assert r.status_code == 200, r.json()
    edited = r.json()
    assert edited["body"] == "Envoyez votre pièce d'identité." and edited["communes"] == ["Cocody"] and edited["version"] == c.version + 1
    bad = mkt.patch(f"{URL}{c.pk}/", {"version": edited["version"], "action_value": "business"}, format="json")
    assert bad.status_code == 400                                          # écran réservé aux entreprises
    out_of_range = mkt.patch(f"{URL}{c.pk}/", {"version": edited["version"], "delay_hours": 999999}, format="json")
    assert out_of_range.status_code == 400 and "delay_hours" in out_of_range.json()["fields"]
    on = mkt.post(f"{URL}{c.pk}/activate/")
    assert on.status_code == 200 and on.json()["is_active"]
    carrier = Announcement.objects.get(pk=Campaign.objects.get(pk=c.pk).announcement_id)
    assert carrier.source == "campaign" and carrier.status == "published" and (carrier.to_artisans, carrier.to_clients) == (True, False)
    assert carrier.cities == ["Cocody"] and carrier.body == "Envoyez votre pièce d'identité."
    listed = api(staff("cbo_mkt3", "marketing")).get("/handy/backoffice/announcements/").json()["results"]
    assert carrier.pk not in {row["id"] for row in listed}                 # jamais mélangée aux annonces manuelles
    locked = mkt.patch(f"{URL}{c.pk}/", {"version": on.json()["version"], "trigger": "welcome"}, format="json")
    assert locked.status_code == 400 and "trigger" in locked.json()["fields"]
    news = Campaign.objects.get(key="nouveau-trouvez-moi-un-pro")
    Device.objects.create(user=account("cbo_phone_old"), device_token="cbo-old", device_type="android", capabilities=["rich1"])
    Device.objects.create(user=account("cbo_phone_new"), device_token="cbo-new", device_type="android", capabilities=["flash"])
    page = mkt.get(URL).json()
    row = next(r for r in page["results"] if r["id"] == news.pk)
    assert row["features"] == [{"code": "flash", "label": "« Trouvez-moi un professionnel » (Tratra Flash)"}]
    assert row["app"] == {"phones": 2, "ready": 1}                         # téléphones dont l'application ouvre la fonction
    assert {"code": "panne", "label": "« J'ai une panne »", "phones": 2, "ready": 0} in page["meta"]["features"]
    assert "deployed_features" not in page["meta"]
    estimate = mkt.get(f"{URL}{news.pk}/?estimate=1").json()
    assert estimate["preview"]["rules"]["app"] == {"phones": 2, "ready": 1}
    assert estimate["audience_estimate"] >= 1 and estimate["audience_waiting_update"] >= 1   # comme si elle démarrait maintenant
    activated = mkt.post(f"{URL}{news.pk}/activate/")
    assert activated.status_code == 200 and activated.json()["is_active"]
    reach = mkt.get(f"{URL}{news.pk}/").json()
    assert reach["audience_waiting_update"] >= 1 and reach["audience_estimate"] >= 1
    mkt.post(f"{URL}{news.pk}/deactivate/")
    run = mkt.post(f"{URL}run/")
    assert run.status_code == 200 and "scheduled" in run.json()
    assert mkt.get(f"{URL}{c.pk}/sends/").json()["count"] == 0
    off = mkt.post(f"{URL}{c.pk}/deactivate/")
    assert off.status_code == 200 and not off.json()["is_active"]
    assert Announcement.objects.get(pk=carrier.pk).status == "cancelled"
