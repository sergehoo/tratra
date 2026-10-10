"""Annonces : audience, publication, diffusion (une livraison par utilisateur), expiration et statistiques."""
import logging
from typing import List
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import Lower
from django.utils import timezone

from announcements.models import Announcement, AnnouncementDelivery
from handy import notifications
from trust.models import audit

logger = logging.getLogger(__name__)
User = get_user_model()

BATCH = 500


# ------------------------------------------------------------------------------------------------------ validation

def validate_action(kind: str, value: str) -> None:
    """Action d'une annonce : jamais d'URL autre que https, jamais d'écran inconnu (pas de lien arbitraire, pas de javascript:)."""
    if kind == "none":
        return
    if not value:
        raise ValidationError("Une destination est requise pour cette action.")
    if kind == "link":
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValidationError("Le lien doit être une adresse https valide.")
    elif kind == "deeplink":
        name, _, ident = value.partition("/")
        if name not in Announcement.DEEPLINK_KINDS or (ident and not ident.isdigit()):
            raise ValidationError("Écran de l'application inconnu.")
        if name in ("booking", "mission") and not ident:
            raise ValidationError("Un identifiant est requis pour cet écran.")
    else:
        raise ValidationError("Action inconnue.")


def validate_for_publication(a: Announcement) -> None:
    if not (a.title or "").strip() or not (a.body or "").strip():
        raise ValidationError("Titre et contenu sont obligatoires.")
    if not (a.to_clients or a.to_artisans or a.to_companies):
        raise ValidationError("Choisissez au moins une audience (clients, artisans ou entreprises).")
    validate_action(a.action_kind, a.action_value)
    if a.expires_at and a.publish_at and a.expires_at <= a.publish_at:
        raise ValidationError("L'expiration doit suivre la publication.")
    if a.expires_at and a.expires_at <= timezone.now():
        raise ValidationError("L'expiration est déjà passée.")


# ------------------------------------------------------------------------------------------------------- audience

def audience_queryset(a: Announcement):
    """Utilisateurs ciblés. Rôles = capacités du compte unique (artisan : profil professionnel ; entreprise : profil ou
    adhésion Business ; client : compte sans profil professionnel ou ayant réservé). Géographie = villes/communes
    DÉCLARÉES uniquement. Promotion = consentement marketing obligatoire."""
    q = Q()
    if a.to_artisans:
        q |= Q(handyman_profile__isnull=False)
    if a.to_companies:
        q |= Q(company_profile__isnull=False) | Q(business_memberships__is_active=True)
    if a.to_clients:
        q |= (Q(handyman_profile__isnull=True, company_profile__isnull=True) | Q(client_bookings__isnull=False))
    users = User.objects.filter(is_active=True, is_staff=False)
    users = users.filter(q) if q else users.none()
    if a.kind == "promotion":
        users = users.filter(marketing_consent__granted=True)
    cities = [c.strip().lower() for c in (a.cities or []) if str(c).strip()]
    if cities:
        users = users.annotate(_city=Lower("city"), _commune=Lower("handyman_profile__commune"), _company=Lower("company_profile__city"),
                               _org=Lower("business_memberships__organization__city")).filter(
            Q(_city__in=cities) | Q(_commune__in=cities) | Q(_company__in=cities) | Q(_org__in=cities))
    return users.distinct()


# ---------------------------------------------------------------------------------------------------- cycle de vie

@transaction.atomic
def schedule(a: Announcement, publish_at, *, actor=None) -> Announcement:
    a = Announcement.objects.select_for_update().get(pk=a.pk)
    if a.status not in ("draft", "scheduled"):
        raise ValidationError("Seule une annonce en brouillon ou programmée peut être (re)programmée.")
    if publish_at <= timezone.now():
        raise ValidationError("La date de publication doit être dans le futur.")
    a.publish_at, a.status = publish_at, "scheduled"
    validate_for_publication(a)
    a.version += 1
    a.save(update_fields=["publish_at", "status", "version", "updated_at"])
    audit("announcement.scheduled", actor=actor, target=a, publish_at=publish_at.isoformat())
    return a


@transaction.atomic
def publish(a: Announcement, *, actor=None) -> Announcement:
    """Publie (immédiatement ou à l'heure programmée) puis lance la diffusion asynchrone. Idempotent."""
    a = Announcement.objects.select_for_update().get(pk=a.pk)
    if a.status == "published":
        return a
    if a.status not in ("draft", "scheduled"):
        raise ValidationError("Cette annonce ne peut plus être publiée.")
    validate_for_publication(a)
    now = timezone.now()
    a.status, a.published_at = "published", now
    if not a.publish_at or a.publish_at > now:
        a.publish_at = now
    a.version += 1
    a.save(update_fields=["status", "published_at", "publish_at", "version", "updated_at"])
    audit("announcement.published", actor=actor, target=a, kind=a.kind, audience=audience_summary(a))
    from announcements.tasks import deliver_announcement

    transaction.on_commit(lambda: _enqueue(deliver_announcement, a.pk))
    return a


def _enqueue(task, *args) -> None:
    try:
        task.apply_async(args=args, retry=False)
    except Exception:  # broker indisponible : diffusion sur place (idempotente)
        logger.warning("Broker indisponible : diffusion exécutée sur place.", exc_info=True)
        task(*args)


@transaction.atomic
def cancel(a: Announcement, *, actor=None) -> Announcement:
    a = Announcement.objects.select_for_update().get(pk=a.pk)
    if a.status in ("cancelled", "expired"):
        return a
    a.status = "cancelled"
    a.version += 1
    a.save(update_fields=["status", "version", "updated_at"])
    audit("announcement.cancelled", actor=actor, target=a)
    return a


def audience_summary(a: Announcement) -> List[str]:
    return [n for flag, n in ((a.to_clients, "clients"), (a.to_artisans, "artisans"), (a.to_companies, "entreprises")) if flag]


# ----------------------------------------------------------------------------------------------------- diffusion

def deliver(announcement_id: int) -> int:
    """Crée UNE livraison + UNE notification par utilisateur ciblé (jamais deux, même si la tâche est rejouée). Les
    utilisateurs qui n'ont plus de consentement au moment de l'envoi sont exclus par l'audience elle-même."""
    a = Announcement.objects.filter(pk=announcement_id, status="published").first()
    if a is None:
        return 0
    created = 0
    ids = list(audience_queryset(a).values_list("pk", flat=True))
    for start in range(0, len(ids), BATCH):
        for user_id in ids[start:start + BATCH]:
            if a.expires_at and a.expires_at <= timezone.now():
                return created
            delivery, new = AnnouncementDelivery.objects.get_or_create(announcement=a, user_id=user_id)
            if not new:
                continue
            n = notifications.notify(user_id, "announcement", a.body[:200], title=a.title,
                                     data={"kind": "announcement", "id": a.pk}, dedupe_key=f"announcement:{a.pk}",
                                     push=a.send_push, collapse_key=f"announcement-{a.pk}")
            if n is not None:
                delivery.notification = n
                delivery.save(update_fields=["notification"])
            created += 1
    return created


def tick(now=None) -> dict:
    """Appelé chaque minute (Celery beat) : publie les annonces programmées échues, expire les annonces dépassées."""
    now = now or timezone.now()
    published = expired = 0
    for a in Announcement.objects.filter(status="scheduled", publish_at__lte=now):
        try:
            publish(a)
            published += 1
        except ValidationError:
            logger.warning("Annonce #%s programmée invalide : annulée.", a.pk)
            cancel(a)
    expired = Announcement.objects.filter(status="published", expires_at__lte=now).update(status="expired")
    return {"published": published, "expired": expired}


# ------------------------------------------------------------------------------------------------------ lecture

def feed_for(user):
    """Annonces VISIBLES de l'utilisateur : publiées, non expirées, non écartées ; une promotion disparaît si le
    consentement a été retiré depuis."""
    now = timezone.now()
    qs = (AnnouncementDelivery.objects.filter(user=user, announcement__status="published", dismissed_at__isnull=True)
          .filter(Q(announcement__expires_at__isnull=True) | Q(announcement__expires_at__gt=now))
          .select_related("announcement").order_by("-delivered_at", "-id"))
    if not notifications.has_marketing_consent(user):
        qs = qs.exclude(announcement__kind="promotion")
    return qs


def mark(user, announcement_id: int, field: str) -> AnnouncementDelivery:
    """Première vue / ouverture / fermeture : horodaté une seule fois, strictement sur SA livraison."""
    delivery = AnnouncementDelivery.objects.select_related("announcement").get(announcement_id=announcement_id, user=user)
    now = timezone.now()
    changed = []
    if getattr(delivery, field) is None:
        setattr(delivery, field, now)
        changed.append(field)
    if field == "opened_at" and delivery.seen_at is None:
        delivery.seen_at = now
        changed.append("seen_at")
    if changed:
        delivery.save(update_fields=changed)
    return delivery


def stats(a: Announcement) -> dict:
    """Statistiques agrégées (aucune donnée personnelle) : audience, livraisons, push, vues, ouvertures."""
    d = AnnouncementDelivery.objects.filter(announcement=a)
    total = d.count()
    push = dict(d.exclude(notification__isnull=True).values_list("notification__push_status").annotate(n=Count("id")))
    seen, opened = d.filter(seen_at__isnull=False).count(), d.filter(opened_at__isnull=False).count()
    return {
        "status": a.status, "audience_estimate": audience_queryset(a).count() if a.status in ("draft", "scheduled") else total,
        "delivered": total, "push": {k or "none": v for k, v in push.items()},
        "seen": seen, "opened": opened, "dismissed": d.filter(dismissed_at__isnull=False).count(),
        "seen_rate": round(seen / total, 4) if total else None, "open_rate": round(opened / total, 4) if total else None,
    }
