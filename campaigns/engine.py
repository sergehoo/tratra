"""Moteur des campagnes d'engagement (Celery, `campaigns.tasks.tick`, toutes les 10 minutes) : programmer → envoyer → mesurer.

1. PROGRAMMER : pour chaque campagne ACTIVE et dans sa période, les comptes dont l'événement déclencheur est dans la fenêtre reçoivent
   un envoi « programmé » — contrainte d'unicité (campagne, compte, référence) : rejouer la tâche ne duplique rien.
2. ENVOYER (lots, verrou `skip_locked` : deux workers ne traitent jamais le même envoi) — dans l'ordre :
   campagne toujours active · compte actif · objectif déjà atteint → arrêt · désinscription (catégorie « tips ») · consentement marketing
   · heures autorisées (fuseau de l'exploitation) → report · priorité opérationnelle (Flash, réservation, sécurité) → report ·
   fréquence (écart minimal entre deux messages d'engagement) → report · push seulement si la limite hebdomadaire le permet.
   Canaux : message dans l'application (module Annonces, annonce SUPPORT de la campagne) + push FCM ; JAMAIS de SMS.
3. MESURER : un envoi dont l'objectif est atteint ensuite est marqué « converti »."""
import logging
from copy import copy
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from announcements.models import Announcement, AnnouncementDelivery
from campaigns import triggers
from campaigns.models import Campaign, CampaignSend
from handy import destinations, features, notifications

logger = logging.getLogger(__name__)
User = get_user_model()

ROLE_FIELDS = {"clients": "to_clients", "artisans": "to_artisans", "companies": "to_companies"}
MAX_DEFERRALS = 12


def setting(name: str, default):
    return getattr(settings, name, default)


def weekly_push_limit() -> int:
    return int(setting("CAMPAIGN_PUSH_WEEKLY_LIMIT", 2))


def send_hours() -> tuple:
    raw = str(setting("CAMPAIGN_SEND_HOURS", "9-20"))
    start, _, end = raw.partition("-")
    return int(start or 9), int(end or 20)


def required_features(campaign: Campaign) -> set:
    """Fonctions récentes que la campagne annonce (`feature`) ou dont elle ouvre l'écran (handy.features) : serveur et site en ligne
    avec cette version ; l'application, seulement chez ceux qui l'ont mise à jour — eux seuls sont visés (voir `schedule`)."""
    return ({campaign.feature} if campaign.feature else set()) | features.for_destination(campaign.action_value)


# ── Validation et annonce support ─────────────────────────────────────────────────────────────────────────────────────────────

def validate(campaign: Campaign) -> None:
    """Règles d'activation : message complet, déclencheur compatible avec l'audience, écran du registre ouvert à cette audience,
    fonction annoncée connue du registre (handy.features), période cohérente."""
    if not (campaign.title or "").strip() or not (campaign.body or "").strip():
        raise ValidationError("Titre et message sont obligatoires.")
    trigger = triggers.trigger_for(campaign)
    if trigger is None:
        raise ValidationError("Déclencheur inconnu.")
    if campaign.audience not in trigger.audiences:
        raise ValidationError(f"Le déclencheur « {campaign.get_trigger_display()} » ne concerne pas les {campaign.get_audience_display().lower()}.")
    if campaign.action_value:
        destinations.validate_for_announcement(campaign.action_value, [campaign.audience])
    unknown = features.unknown([campaign.feature])
    if unknown:
        raise ValidationError(f"Fonction inconnue : {', '.join(unknown)}. Une campagne ne doit jamais annoncer une fonction indisponible.")
    if campaign.starts_at and campaign.ends_at and campaign.ends_at <= campaign.starts_at:
        raise ValidationError("La fin doit suivre le début.")
    unknown = [p for p in campaign.progress or [] if p not in dict(Campaign.PROGRESS)]
    if unknown:
        raise ValidationError(f"Étape de progression inconnue : {', '.join(unknown)}.")


def sync_announcement(campaign: Campaign) -> Announcement:
    """Annonce SUPPORT (source « campaign ») : porte le message dans le flux de l'application et le lien de l'action du push. Publiée
    tant que la campagne est active ; annulée sinon (les messages disparaissent du flux, aucun push en attente ne part)."""
    a = campaign.announcement or Announcement(source="campaign", created_by=campaign.updated_by)
    a.title, a.body = campaign.title[:140], campaign.body
    a.kind = "promotion" if campaign.marketing else "service"
    a.action_kind, a.action_label, a.action_value = ("deeplink", campaign.action_label or "Voir", campaign.action_value) if campaign.action_value else ("none", "", "")
    for role, field in ROLE_FIELDS.items():
        setattr(a, field, role == campaign.audience)
    a.cities = list(campaign.communes or [])
    a.send_push = campaign.send_push
    if campaign.is_active:
        a.status, a.published_at = "published", a.published_at or timezone.now()
    else:
        a.status = "cancelled" if a.pk else "draft"
    a.save()
    if campaign.announcement_id != a.pk:
        Campaign.objects.filter(pk=campaign.pk).update(announcement=a)
        campaign.announcement = a
    return a


@transaction.atomic
def set_active(campaign: Campaign, active: bool, *, actor=None) -> Campaign:
    from trust.models import audit

    campaign = Campaign.objects.select_for_update().get(pk=campaign.pk)
    if active:
        validate(campaign)
    campaign.is_active = active
    if active and not campaign.activated_at:
        campaign.activated_at = timezone.now()
    campaign.updated_by = actor or campaign.updated_by
    campaign.version += 1
    campaign.save(update_fields=["is_active", "activated_at", "updated_by", "version", "updated_at"])
    sync_announcement(campaign)
    if not active:          # désactivation : rien de programmé ne part
        CampaignSend.objects.filter(campaign=campaign, status="scheduled").update(status="cancelled", reason="campaign_inactive")
    audit("campaign.activated" if active else "campaign.deactivated", actor=actor, target_type="campaign", target_id=campaign.pk, key=campaign.key)
    return campaign


def running(now) -> List[Campaign]:
    return list(Campaign.objects.filter(is_active=True).filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
                .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now)).order_by("priority", "pk"))


# ── 1. Programmer ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def schedule(campaign: Campaign, now, cap: int = 2000) -> int:
    """Programme les envois dus (idempotent). `cap` borne le travail d'un passage ; le suivant reprend là où il s'est arrêté."""
    trigger = triggers.trigger_for(campaign)
    if trigger is None:
        return 0
    created, batch = 0, []
    for uid, ref in trigger.candidates(campaign, now):
        batch.append((uid, ref))
        if len(batch) >= 200:
            created += _schedule_batch(campaign, trigger, batch, now)
            batch = []
            if created >= cap:
                return created
    if batch:
        created += _schedule_batch(campaign, trigger, batch, now)
    return created


def _schedule_batch(campaign, trigger, batch, now) -> int:
    existing = set(CampaignSend.objects.filter(campaign=campaign, user_id__in=[u for u, _ in batch]).values_list("user_id", "ref"))
    fresh = [(u, r) for u, r in batch if (u, r) not in existing]
    if not fresh:
        return 0
    users = {u.pk: u for u in User.objects.filter(pk__in=[u for u, _ in fresh]).select_related("handyman_profile")}
    # Application à mettre à jour : le compte n'est pas programmé ; il l'est au premier passage qui suit sa mise à jour.
    reachable = features.reachable_user_ids(users, required_features(campaign))
    rows = []
    for uid, ref in fresh:
        user = users.get(uid)
        if user is None or uid not in reachable or not trigger.start_ok(user, ref):
            continue
        if campaign.progress and triggers.progress_of(user) not in campaign.progress:
            continue
        rows.append(CampaignSend(campaign=campaign, user_id=uid, ref=ref, due_at=now))
    CampaignSend.objects.bulk_create(rows, ignore_conflicts=True)       # filet de sécurité : contrainte d'unicité
    return len(rows)


# ── 2. Envoyer ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def next_send_time(now) -> Optional[datetime]:
    """None si l'heure locale est dans la plage autorisée ; sinon le prochain début de plage (fuseau de l'exploitation)."""
    start, end = send_hours()
    local = now.astimezone(ZoneInfo(settings.TIME_ZONE))
    if start <= local.hour < end:
        return None
    day = local.date() + (timedelta(days=1) if local.hour >= end else timedelta(0))
    return datetime(day.year, day.month, day.day, start, tzinfo=local.tzinfo)


def pushes_this_week(user_id: int, now) -> int:
    since = now - timedelta(days=7)
    campaign_pushes = CampaignSend.objects.filter(user_id=user_id, push=True, sent_at__gte=since).count()
    promo_pushes = AnnouncementDelivery.objects.filter(user_id=user_id, delivered_at__gte=since, announcement__kind="promotion",
                                                       announcement__source="manual", announcement__send_push=True).count()
    return campaign_pushes + promo_pushes


def opted_out(user_id: int) -> bool:
    return not notifications.push_enabled(user_id, "tips")


def dispatch(now, cap: int = 1000) -> Dict[str, int]:
    out: Dict[str, int] = {}
    ids = list(CampaignSend.objects.filter(status="scheduled", due_at__lte=now).order_by("campaign__priority", "due_at", "pk")
               .values_list("pk", flat=True)[:cap])
    for pk in ids:
        result = send_one(pk, now)
        out[result] = out.get(result, 0) + 1
    return out


def _close(send: CampaignSend, status: str, reason: str = "") -> str:
    send.status, send.reason = status, reason
    send.save(update_fields=["status", "reason"])
    return reason or status


def _defer(send: CampaignSend, when, reason: str) -> str:
    send.attempts += 1
    if send.attempts > MAX_DEFERRALS:
        return _close(send, "skipped", reason)
    send.due_at, send.reason = when, reason
    send.save(update_fields=["due_at", "reason", "attempts"])
    return f"deferred:{reason}"


def send_one(pk: int, now) -> str:
    with transaction.atomic():
        send = (CampaignSend.objects.select_for_update(skip_locked=True, of=("self",)).select_related("campaign", "user")
                .filter(pk=pk, status="scheduled").first())
        if send is None:
            return "locked"
        campaign, user = send.campaign, send.user
        if not campaign.is_active or (campaign.ends_at and campaign.ends_at <= now):
            return _close(send, "cancelled", "campaign_inactive")
        if not user.is_active:
            return _close(send, "skipped", "account_inactive")
        trigger = triggers.trigger_for(campaign)
        if trigger is None or trigger.goal_met(user, send.ref):
            return _close(send, "goal_met", "goal_met")
        if opted_out(user.pk):
            return _close(send, "skipped", "opted_out")
        if campaign.marketing and not notifications.has_marketing_consent(user.pk):
            return _close(send, "skipped", "no_consent")
        later = next_send_time(now)
        if later is not None:
            return _defer(send, later, "quiet_hours")
        if triggers.operational_busy(user, now):
            return _defer(send, now + timedelta(hours=2), "priority")
        last = CampaignSend.objects.filter(user=user, status="sent").exclude(pk=send.pk).order_by("-sent_at").values_list("sent_at", flat=True).first()
        if last and last > now - timedelta(hours=campaign.min_gap_hours):
            return _defer(send, last + timedelta(hours=campaign.min_gap_hours), "frequency")
        push = campaign.send_push and pushes_this_week(user.pk, now) < weekly_push_limit()
        _deliver(send, campaign, user, push, now)
        return "sent" if push else "sent_in_app"


def _deliver(send: CampaignSend, campaign: Campaign, user, push: bool, now) -> None:
    a = campaign.announcement if campaign.announcement_id and campaign.announcement.status == "published" else sync_announcement(campaign)
    delivery, created = AnnouncementDelivery.objects.get_or_create(announcement=a, user=user)
    n = notifications.notify(user, "campaign", campaign.body[:200], title=campaign.title, data={"kind": "announcement", "id": a.pk},
                             dedupe_key=f"campaign:{send.pk}", push=push, collapse_key=f"campaign-{campaign.pk}")
    updates = {"notification": n} if n is not None else {}
    if not created:                               # nouveau déclenchement (ex. autre réservation) : le message revient dans le flux
        updates.update(seen_at=None, opened_at=None, dismissed_at=None)
    if updates:
        AnnouncementDelivery.objects.filter(pk=delivery.pk).update(**updates)
    send.status, send.sent_at, send.push, send.notification, send.reason = "sent", now, push, n, "" if push or not campaign.send_push else "push_quota"
    send.save(update_fields=["status", "sent_at", "push", "notification", "reason"])


# ── 3. Mesurer ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def mark_conversions(now, cap: int = 500) -> int:
    n = 0
    sends = (CampaignSend.objects.filter(status="sent", converted_at__isnull=True, sent_at__gte=now - timedelta(days=30))
             .select_related("campaign", "user").order_by("sent_at")[:cap])
    for send in sends:
        trigger = triggers.trigger_for(send.campaign)
        if trigger is not None and send.campaign.trigger not in ("welcome", "news") and trigger.goal_met(send.user, send.ref):
            CampaignSend.objects.filter(pk=send.pk).update(converted_at=now)
            n += 1
    return n


def tick(now=None) -> Dict[str, int]:
    now = now or timezone.now()
    scheduled = sum(schedule(c, now) for c in running(now))
    result = {"scheduled": scheduled, **dispatch(now), "converted": mark_conversions(now)}
    return result


def stats(campaign: Campaign) -> Dict:
    by_status = dict(CampaignSend.objects.filter(campaign=campaign).values_list("status").annotate(n=Count("id")))
    sent = CampaignSend.objects.filter(campaign=campaign, status="sent")
    reasons = dict(CampaignSend.objects.filter(campaign=campaign, status="skipped").values_list("reason").annotate(n=Count("id")))
    deliveries = AnnouncementDelivery.objects.filter(announcement=campaign.announcement) if campaign.announcement_id else AnnouncementDelivery.objects.none()
    total_sent = sent.count()
    converted = sent.filter(converted_at__isnull=False).count()
    opened = deliveries.filter(opened_at__isnull=False).count()
    return {"scheduled": by_status.get("scheduled", 0), "sent": total_sent, "push": sent.filter(push=True).count(),
            "goal_met_before_send": by_status.get("goal_met", 0), "skipped": by_status.get("skipped", 0), "skipped_reasons": reasons,
            "cancelled": by_status.get("cancelled", 0), "opened": opened, "converted": converted,
            "open_rate": round(opened / total_sent, 4) if total_sent else None,
            "conversion_rate": round(converted / total_sent, 4) if total_sent else None}


def audience(campaign: Campaign, now=None, limit: int = 5000) -> Dict[str, int]:
    """NOUVEAUX destinataires au prochain passage : événements dans la fenêtre, hors envois déjà programmés ou faits (borné :
    estimation ; l'objectif et la progression sont vérifiés à la programmation) — `waiting_update` : ceux dont l'application doit
    d'abord être mise à jour pour ouvrir la fonction (ils seront visés ensuite)."""
    now = now or timezone.now()
    trigger = triggers.trigger_for(campaign)
    if trigger is None:
        return {"new": 0, "waiting_update": 0}
    if campaign.trigger == "news" and not (campaign.starts_at or campaign.activated_at):
        campaign = copy(campaign)              # nouveauté pas encore activée : estimée comme si elle démarrait maintenant
        campaign.activated_at = now
    pairs = []
    for pair in trigger.candidates(campaign, now):
        pairs.append(pair)
        if len(pairs) >= limit:
            break
    known = set(CampaignSend.objects.filter(campaign=campaign, user_id__in=[u for u, _ in pairs]).values_list("user_id", "ref"))
    fresh = [pair for pair in pairs if pair not in known]
    reachable = features.reachable_user_ids({u for u, _ in fresh}, required_features(campaign))
    new = sum(1 for u, _ in fresh if u in reachable)
    return {"new": new, "waiting_update": len(fresh) - new}


def audience_estimate(campaign: Campaign, now=None, limit: int = 5000) -> int:
    return audience(campaign, now, limit)["new"]


def preview(campaign: Campaign) -> Dict:
    """Ce que verra le destinataire : carte dans l'application, notification push (titre, texte, bouton, lien app et web)."""
    action = None
    if campaign.action_value:
        action = {"label": campaign.action_label or "Voir", "destination": destinations.describe(campaign.action_value),
                  "app": f"tratra://{campaign.action_value}", "web": destinations.web_href(campaign.action_value)}
    return {"in_app": {"title": campaign.title, "body": campaign.body, "action": action},
            "push": {"enabled": campaign.send_push, "title": campaign.title[:140], "body": campaign.body[:200],
                     "channel": notifications.CHANNEL_BY_CATEGORY["tips"], "deeplink": f"tratra://{campaign.action_value}" if campaign.action_value
                     else "tratra://announcement", "weekly_limit": weekly_push_limit()},
            "rules": {"marketing": campaign.marketing, "consent_required": campaign.marketing, "send_hours": "%dh-%dh" % send_hours(),
                      "timezone": settings.TIME_ZONE, "min_gap_hours": campaign.min_gap_hours,
                      "features": describe_features(required_features(campaign)),
                      "app": features.adoption(required_features(campaign)) if required_features(campaign) else None}}


def describe_features(codes) -> List[Dict[str, str]]:
    return [{"code": c, "label": features.label(c)} for c in sorted(codes)]
