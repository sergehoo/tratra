"""Centre de notifications : l'UNIQUE point de création des notifications Tratra.

  notify(...)  →  1. enregistre la notification en base (historique persistant, lu/non lu, navigation, déduplication) ;
                  2. planifie le push FCM de façon asynchrone (Celery) — le push ne dépend JAMAIS du WebSocket et sa
                     réussite n'est jamais nécessaire : l'enregistrement en base reste la source de vérité.

Règles : un événement ne notifie qu'une fois (`dedupe_key`), les préférences par catégorie sont respectées, les
notifications « compte » (vérification d'identité, sécurité) ne peuvent pas être coupées, et aucune annonce
promotionnelle n'est envoyée sans consentement marketing (voir `announcements`)."""
import logging
from typing import Dict, Iterable, List, Optional

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.utils import timezone

from handy.models import MarketingConsent, Notification, NotificationPreference

logger = logging.getLogger(__name__)

CATEGORY_BY_TYPE: Dict[str, str] = {
    "profile_incomplete": "account", "profile_completed": "account", "kyc_approved": "account", "kyc_rejected": "account",
    "booking_request": "booking", "booking_confirmed": "booking", "booking_cancelled": "booking",
    "booking_started": "booking", "booking_completed": "booking", "booking_status": "booking",
    "dispute_opened": "booking", "dispute_resolved": "booking",
    "payment_received": "payment", "refund_issued": "payment",
    "cash_declared": "payment", "cash_confirmed": "payment", "cash_contested": "payment",
    "review_received": "review", "review_reply": "review",
    "message_received": "message",
    "live_en_route": "live", "live_arrived": "live",
    "business_request": "business", "business_update": "business", "business_reminder": "business",
    "announcement": "announcement", "system": "system",
    # Engagements longue durée : contrats, échéances, planning, évaluations.
    "engagement_application": "engagement", "engagement_interview": "engagement", "engagement_selected": "engagement",
    "contract_proposed": "engagement", "contract_accepted": "engagement", "contract_active": "engagement",
    "contract_amendment": "engagement", "contract_suspended": "engagement", "contract_notice": "engagement",
    "contract_ended": "engagement", "contract_renewal": "engagement", "installment_due": "engagement",
    "installment_overdue": "engagement", "payment_declared": "engagement", "payment_confirmed": "engagement",
    "schedule_event": "engagement", "evaluation_received": "engagement", "engagement_dispute": "engagement",
}

# Catégories dont le push ne peut pas être désactivé (vérification d'identité, sécurité du compte).
LOCKED_CATEGORIES = {"account"}

# Canaux de notification Android (créés par MainActivity) : importance haute pour l'opérationnel, plus discrète pour le reste.
CHANNEL_BY_CATEGORY = {
    "booking": "tratra_default", "message": "tratra_default", "live": "tratra_default", "payment": "tratra_default",
    "account": "tratra_default", "review": "tratra_updates", "business": "tratra_updates", "system": "tratra_updates",
    "engagement": "tratra_default",
    "announcement": "tratra_announcements",
}
# Durée de vie d'un push non délivré (appareil éteint) : un « artisan en route » périmé n'a aucun intérêt.
TTL_BY_CATEGORY = {"live": 900, "message": 86400, "announcement": 259200}

TYPE_LABELS = dict(Notification.TYPES)
CATEGORY_LABELS = dict(Notification.CATEGORIES)


def category_of(ntype: str) -> str:
    return CATEGORY_BY_TYPE.get(ntype, "system")


def deeplink(data: Optional[dict]) -> str:
    """Lien profond canonique : tratra://booking/12, tratra://mission/12, tratra://conversation/5, tratra://announcement/3."""
    data = data or {}
    kind, obj_id = data.get("kind"), data.get("id")
    if kind and obj_id is not None:
        return f"tratra://{kind}/{obj_id}"
    return f"tratra://{kind}" if kind else "tratra://notifications"


def _user_id(user) -> int:
    return user if isinstance(user, int) else user.pk


# --------------------------------------------------------------------------------------------------- préférences

def push_enabled(user, category: str) -> bool:
    """Le push de cette catégorie est-il autorisé par l'utilisateur ? (défaut : oui)."""
    if category in LOCKED_CATEGORIES:
        return True
    pref = NotificationPreference.objects.filter(user_id=_user_id(user), category=category).first()
    return True if pref is None else pref.push_enabled


def preferences_for(user) -> List[dict]:
    stored = {p.category: p.push_enabled for p in NotificationPreference.objects.filter(user_id=_user_id(user))}
    return [{"category": code, "label": label, "push_enabled": True if code in LOCKED_CATEGORIES else stored.get(code, True),
             "locked": code in LOCKED_CATEGORIES} for code, label in Notification.CATEGORIES]


def set_preferences(user, changes: Dict[str, bool]) -> List[dict]:
    uid = _user_id(user)
    valid = set(CATEGORY_LABELS)
    for category, enabled in changes.items():
        if category not in valid:
            raise ValueError(f"Catégorie inconnue : {category}")
        if category in LOCKED_CATEGORIES:
            continue  # jamais désactivable
        NotificationPreference.objects.update_or_create(user_id=uid, category=category, defaults={"push_enabled": bool(enabled)})
    return preferences_for(uid)


# ------------------------------------------------------------------------------------------ consentement marketing

def has_marketing_consent(user) -> bool:
    return MarketingConsent.objects.filter(user_id=_user_id(user), granted=True).exists()


def set_marketing_consent(user, granted: bool, *, source: str = "app", text_version: str = "v1", actor=None) -> MarketingConsent:
    """Enregistre le consentement (ou son retrait) avec preuve horodatée et journal d'audit."""
    from trust.models import audit

    now = timezone.now()
    consent, _ = MarketingConsent.objects.get_or_create(user_id=_user_id(user))
    if granted and not consent.granted:
        consent.granted, consent.granted_at, consent.revoked_at = True, now, None
        consent.source, consent.text_version = source, text_version
    elif not granted and consent.granted:
        consent.granted, consent.revoked_at = False, now
        consent.source = source
    else:
        return consent  # aucun changement : pas de bruit dans l'audit
    consent.save()
    audit("marketing_consent.granted" if granted else "marketing_consent.revoked", actor=actor or (user if not isinstance(user, int) else None),
          target_type="user", target_id=_user_id(user), source=source, text_version=text_version)
    return consent


# ------------------------------------------------------------------------------------------------------ création

def notify(user, ntype: str, message: str, *, title: str = "", data: Optional[dict] = None, dedupe_key: Optional[str] = None,
           content_object=None, push: bool = True, collapse_key: Optional[str] = None) -> Optional[Notification]:
    """Crée la notification (une seule fois par `dedupe_key`) puis planifie son push. Renvoie None si elle existait déjà.

    `data` décrit l'objet à ouvrir : {"kind": "booking"|"mission"|"conversation"|"announcement", "id": n}."""
    uid = _user_id(user)
    category = category_of(ntype)
    fields = dict(
        notification_type=ntype, category=category, title=(title or TYPE_LABELS.get(ntype, ""))[:140], message=message,
        data=data or {}, push_status="queued" if push else "",
    )
    if content_object is not None:
        fields.update(content_type=ContentType.objects.get_for_model(content_object), object_id=content_object.pk)
    try:
        with transaction.atomic():
            notification = Notification.objects.create(user_id=uid, dedupe_key=dedupe_key, **fields)
    except IntegrityError:
        # Course ou rejeu : la notification de cet événement existe déjà (contrainte d'unicité).
        if dedupe_key:
            return None
        raise
    if push:
        _schedule_push(notification, collapse_key)
    return notification


def _schedule_push(notification: Notification, collapse_key: Optional[str] = None) -> None:
    """Envoi asynchrone (Celery) après validation de la transaction. Sans broker, repli en exécution directe."""
    from handy.tasks import send_notification_push

    def run():
        try:
            send_notification_push.apply_async(args=(notification.pk, collapse_key), retry=False)
        except Exception:  # broker indisponible : la notification reste en base, le push est tenté sur place
            logger.warning("Broker indisponible : push de la notification #%s exécuté sur place.", notification.pk, exc_info=True)
            try:
                send_notification_push(notification.pk, collapse_key)
            except Exception:
                logger.exception("Push de la notification #%s non envoyé", notification.pk)

    transaction.on_commit(run)


def notify_many(users: Iterable, ntype: str, message: str, **kwargs) -> int:
    count = 0
    for user in users:
        if notify(user, ntype, message, **kwargs) is not None:
            count += 1
    return count


# ---------------------------------------------------------------------------------------------- lecture / compteurs

def unread_count(user, category: Optional[str] = None) -> int:
    qs = Notification.objects.filter(user_id=_user_id(user), is_read=False)
    return qs.filter(category=category).count() if category else qs.count()


def unread_by_category(user) -> Dict[str, int]:
    from django.db.models import Count

    rows = (Notification.objects.filter(user_id=_user_id(user), is_read=False)
            .values("category").annotate(n=Count("id")))
    return {r["category"]: r["n"] for r in rows}


def mark_read(user, *, ids: Optional[Iterable[int]] = None, category: Optional[str] = None) -> int:
    """Marque comme lues les notifications de L'UTILISATEUR (jamais celles d'un autre compte). Sans filtre : toutes."""
    qs = Notification.objects.filter(user_id=_user_id(user), is_read=False)
    if ids is not None:
        qs = qs.filter(pk__in=list(ids))
    if category:
        qs = qs.filter(category=category)
    return qs.update(is_read=True, read_at=timezone.now())
