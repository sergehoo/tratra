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
    "schedule_event": "engagement", "evaluation_received": "engagement", "evaluation_invite": "review", "engagement_dispute": "engagement",
    # Tratra Flash : propositions aux professionnels (alerte prioritaire), devis et suites côté client.
    "new_mission": "flash", "mission_paused": "flash", "mission_quote": "booking", "mission_unfulfilled": "booking", "mission_choice": "booking",
    "trust_penalty": "account",
}

# Catégories dont le push ne peut pas être désactivé (vérification d'identité, sécurité du compte).
LOCKED_CATEGORIES = {"account"}

# Canaux de notification Android (créés par MainActivity) : importance haute pour l'opérationnel (son « tratra_notification »), plus
# discrète pour le reste ; les nouvelles missions ont leur canal dédié (son « tratra_flash », vibration rythmée, actions).
CHANNEL_BY_CATEGORY = {
    "booking": "tratra_activity", "message": "tratra_activity", "live": "tratra_activity", "payment": "tratra_activity",
    "account": "tratra_activity", "review": "tratra_updates", "business": "tratra_updates", "system": "tratra_updates",
    "engagement": "tratra_activity",
    "announcement": "tratra_announcements",
    "flash": "tratra_new_missions",
}
FLASH_CHANNEL, FLASH_SOUND, FLASH_IOS_CATEGORY = "tratra_new_missions", "tratra_flash", "NEW_MISSION"
# Écran verrouillé : pour ces catégories, le push n'affiche qu'un texte NEUTRE (le détail — texte d'un message, montant, motif d'un
# refus KYC, sécurité du compte — reste dans l'application, après déverrouillage) et il est marqué « privé » sur Android.
# `PUSH_MESSAGE_PREVIEW=True` permet d'afficher l'aperçu des messages (choix de l'exploitant).
SENSITIVE_PUSH_CATEGORIES = {"message", "payment", "account"}
LOCK_SCREEN_TEXT = {
    "payment": ("Paiement", "Mise à jour d’un paiement : ouvrez Tratra pour le détail."),
    "account": ("Votre compte Tratra", "Mise à jour de votre compte : ouvrez Tratra pour le détail."),
}


def push_text(notification) -> tuple:
    """(titre, texte) du push : complet, sauf pour les catégories sensibles (texte neutre, sans contenu privé)."""
    from django.conf import settings

    title = notification.title or TYPE_LABELS.get(notification.notification_type, "Tratra")
    body = notification.message[:200]
    if notification.category == "message":
        if getattr(settings, "PUSH_MESSAGE_PREVIEW", False):
            return title, body
        return "Nouveau message", (f"{title} vous a écrit." if notification.title else "Vous avez reçu un message.")
    if notification.category in LOCK_SCREEN_TEXT:
        return LOCK_SCREEN_TEXT[notification.category]
    return title, body


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


def notify_bulk(user_ids: List[int], ntype: str, message: str, *, title: str = "", data: Optional[dict] = None, dedupe_key: str,
                push: bool = True, collapse_key: Optional[str] = None) -> Dict[int, Notification]:
    """Même notification pour PLUSIEURS comptes (diffusions de masse) : une insertion groupée au lieu d'une requête par compte.

    L'appelant garantit que ces comptes n'ont pas encore cette notification (`dedupe_key`), sous un verrou qui exclut toute diffusion
    concurrente de la même annonce ; la contrainte d'unicité reste le filet de sécurité. Renvoie {compte: notification créée}."""
    category = category_of(ntype)
    rows = Notification.objects.bulk_create([
        Notification(user_id=uid, dedupe_key=dedupe_key, notification_type=ntype, category=category,
                     title=(title or TYPE_LABELS.get(ntype, ""))[:140], message=message, data=data or {}, push_status="queued" if push else "")
        for uid in user_ids])
    if push:
        for n in rows:
            _schedule_push(n, collapse_key)
    return {n.user_id: n for n in rows}


# Files Celery des push (routage explicite, un worker par file — docker-compose*.yml, vérifié par `manage.py celery_check`) :
# nouvelles missions Tratra Flash sur « flash » (90 s pour répondre : jamais derrière autre chose), diffusions de masse sur « bulk »
# (une annonce à des centaines de milliers de comptes ne retarde ni un message ni une réservation), le reste sur « default ».
PUSH_QUEUE, FLASH_PUSH_QUEUE, BULK_PUSH_QUEUE = "default", "flash", "bulk"
QUEUE_BY_CATEGORY = {"flash": FLASH_PUSH_QUEUE, "announcement": BULK_PUSH_QUEUE}


def push_queue(category: str) -> str:
    return QUEUE_BY_CATEGORY.get(category, PUSH_QUEUE)


def _schedule_push(notification: Notification, collapse_key: Optional[str] = None) -> None:
    """Envoi asynchrone (Celery) après validation de la transaction. Sans broker, repli en exécution directe."""
    from handy.tasks import send_notification_push

    def run():
        try:
            send_notification_push.apply_async(args=(notification.pk, collapse_key), retry=False,
                                               queue=push_queue(notification.category))
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


# ------------------------------------------------------------------------------------------------------- rétention

def _purgeable(now, days: int):
    """Notifications au-delà de la rétention : lues depuis plus de `days` jours ; non lues seulement si une rétention propre est réglée
    (NOTIFICATION_UNREAD_RETENTION_DAYS, désactivée par défaut). Jamais : catégories protégées (paiements, compte, engagements — preuves
    d'information utiles en cas de litige), push pas encore envoyé (« queued » ou en cours)."""
    from datetime import timedelta

    from django.conf import settings
    from django.db.models import Q

    q = Q(is_read=True, created_at__lt=now - timedelta(days=days))
    unread_days = int(getattr(settings, "NOTIFICATION_UNREAD_RETENTION_DAYS", 0) or 0)
    if unread_days > 0:
        q |= Q(is_read=False, created_at__lt=now - timedelta(days=unread_days))
    protected = set(getattr(settings, "NOTIFICATION_RETENTION_PROTECTED_CATEGORIES", ()))
    return Notification.objects.filter(q).exclude(category__in=protected).exclude(push_status__in=("queued", "sending"))


def purge(now=None, *, days: Optional[int] = None, dry_run: bool = False) -> Dict:
    """Purge par lots (le plus ancien d'abord, par l'index de la clé primaire) : chaque lot est une transaction courte, et un passage
    s'arrête après NOTIFICATION_PURGE_MAX_BATCHES lots (le suivant reprend). Désactivée tant que NOTIFICATION_RETENTION_DAYS vaut 0."""
    from django.conf import settings
    from django.db.models import Count

    days = int(settings.NOTIFICATION_RETENTION_DAYS if days is None else days)
    if days <= 0:
        return {"enabled": False, "deleted": 0}
    qs = _purgeable(now or timezone.now(), days)
    if dry_run:
        by_category = dict(qs.order_by().values_list("category").annotate(n=Count("id")))
        return {"enabled": True, "dry_run": True, "would_delete": sum(by_category.values()), "by_category": by_category}
    size, limit = int(settings.NOTIFICATION_PURGE_BATCH), int(settings.NOTIFICATION_PURGE_MAX_BATCHES)
    deleted = batches = 0
    while batches < limit:
        ids = list(qs.order_by("pk").values_list("pk", flat=True)[:size])
        if not ids:
            break
        with transaction.atomic():
            _, per_model = Notification.objects.filter(pk__in=ids).delete()
        deleted += per_model.get(Notification._meta.label, 0)
        batches += 1
    if deleted:
        logger.info("Rétention des notifications : %s supprimée(s) en %s lot(s) (au-delà de %s jours).", deleted, batches, days)
    return {"enabled": True, "deleted": deleted, "batches": batches, "complete": batches < limit}
