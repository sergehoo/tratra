"""Statuts : publication (médias validés et compressés), visibilité, fil, vues, réponses, signalement, expiration et purge.

Toutes les autorisations sont ici (jamais dans l'interface) : visibilité = contacts Tratra ou audience élargie choisie par l'auteur,
moins exclusions individuelles et blocages ; la liste nominative des lecteurs n'est lisible que par l'auteur ; une vue n'est comptée
que sur appel explicite du client lorsque le statut est affiché."""
import logging
import time
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, F, Max, OuterRef, Q, Sum
from django.utils import timezone

from handy import contacts, inbox, messaging
from handy.media.validate import MediaRejected, check_upload
from statuses.models import Status, StatusExclusion, StatusPreference, StatusReport, StatusView

logger = logging.getLogger(__name__)
BACKGROUNDS = ("green", "yellow", "night", "sky", "rose", "violet")
FEED_CACHE_SECONDS = 30
MAX_FEED_STATUSES = 400


class StatusError(Exception):
    def __init__(self, code: str, detail: str, status: int = 400):
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def cfg(name: str, default):
    return getattr(settings, name, default)


def limits() -> Dict:
    """Paramètres en vigueur (publiés aux clients pour qu'ils bornent la saisie ; le serveur reste l'arbitre)."""
    return {"ttl_hours": int(cfg("STATUS_TTL_HOURS", 24)), "text_max": int(cfg("STATUS_TEXT_MAX", 700)),
            "video_max_seconds": int(cfg("STATUS_VIDEO_MAX_SECONDS", 30)), "image_max_bytes": int(cfg("STATUS_MAX_IMAGE_BYTES", 10 * 1024 * 1024)),
            "video_max_bytes": int(cfg("STATUS_MAX_VIDEO_BYTES", 30 * 1024 * 1024)), "max_active": int(cfg("STATUS_MAX_ACTIVE_PER_USER", 30)),
            "repeat_views": bool(cfg("STATUS_REPEAT_VIEWS_ENABLED", False)), "backgrounds": list(BACKGROUNDS)}


# ----------------------------------------------------------------------------------------------------------- cache

def _gver() -> str:
    v = cache.get("statuses:ver")
    if v is None:
        v = time.time_ns()
        cache.set("statuses:ver", v, None)
    return str(v)


def _vver(user_id: int) -> str:
    return f"{cache.get(f'statuses:vver:{user_id}') or 0}.{contacts.version(user_id)}"


def bump(*user_ids: int) -> None:
    """Invalide les fils en cache : publication/suppression/exclusion (global) ou vue/réglage d'un membre (le sien)."""
    if not user_ids:
        cache.set("statuses:ver", time.time_ns(), None)
    for uid in user_ids:
        cache.set(f"statuses:vver:{uid}", time.time_ns(), None)


def _feed_key(viewer_id: int, kind: str, extra: str = "") -> str:
    return f"statuses:{kind}:{viewer_id}:{_gver()}:{_vver(viewer_id)}:{extra}"


# ------------------------------------------------------------------------------------------------------ préférences

def preference(user) -> StatusPreference:
    return StatusPreference.objects.get_or_create(user=user)[0]


def set_preference(user, *, audience=None, allow_replies=None) -> StatusPreference:
    pref = preference(user)
    if audience is not None:
        if audience not in dict(Status.AUDIENCES):
            raise StatusError("invalid_audience", "Audience inconnue.")
        pref.audience = audience
    if allow_replies is not None:
        pref.allow_replies = bool(allow_replies)
    pref.save()
    bump(user.pk)
    return pref


def exclusions(user) -> List[Dict]:
    rows = StatusExclusion.objects.filter(author=user).select_related("excluded").order_by("-id")
    return [{"user": r.excluded_id, "name": messaging.display_name(r.excluded)} for r in rows]


def exclude(user, other_id: int) -> None:
    from django.contrib.auth import get_user_model

    other = get_user_model().objects.filter(pk=other_id, is_active=True).first()
    if other is None or other.pk == user.pk:
        raise StatusError("not_found", "Membre introuvable.", 404)
    StatusExclusion.objects.get_or_create(author=user, excluded=other)
    bump()


def include(user, other_id: int) -> None:
    StatusExclusion.objects.filter(author=user, excluded_id=other_id).delete()
    bump()


def contact_candidates(user) -> List[Dict]:
    """Mes contacts Tratra (pour choisir ceux à exclure)."""
    from django.contrib.auth import get_user_model

    ids = contacts.contact_ids(user.pk)
    excluded = set(StatusExclusion.objects.filter(author=user).values_list("excluded_id", flat=True))
    users = get_user_model().objects.filter(pk__in=ids, is_active=True, is_staff=False).order_by("first_name", "id")[:300]
    return [{"user": u.pk, "name": messaging.display_name(u), "excluded": u.pk in excluded} for u in users]


# ----------------------------------------------------------------------------------------------------------- visibilité

def visible_qs(viewer):
    """Statuts QUE LE MEMBRE A LE DROIT DE VOIR (actifs, non supprimés, ni bloqués, ni exclus) — soi-même inclus."""
    now = timezone.now()
    base = Status.objects.filter(deleted_at__isnull=True, expires_at__gt=now, author__is_active=True)
    blocked = contacts.blocked_ids(viewer.pk)
    if blocked:
        base = base.exclude(author_id__in=blocked)
    base = base.exclude(Exists(StatusExclusion.objects.filter(author_id=OuterRef("author_id"), excluded_id=viewer.pk)))
    ids = contacts.contact_ids(viewer.pk)
    return base.filter(Q(author=viewer) | Q(author_id__in=ids, audience__in=(Status.CONTACTS, Status.EXTENDED)) | Q(audience=Status.EXTENDED))


def _seen_annotation(viewer):
    return Exists(StatusView.objects.filter(status_id=OuterRef("pk"), viewer=viewer))


# ---------------------------------------------------------------------------------------------------------- présentation

def avatar_url(user, request=None) -> Optional[str]:
    field = user.profile_picture
    profile = getattr(user, "handyman_profile", None)
    if not field and profile is not None and getattr(profile, "photo", None):
        field = profile.photo
    return messaging.media_url(field, request) if field else None


def author_payload(user, request=None) -> Dict:
    return {"id": user.pk, "name": messaging.display_name(user), "avatar": avatar_url(user, request)}


def payload(status: Status, viewer, request=None, *, seen: Optional[bool] = None, stats: Optional[Dict] = None) -> Dict:
    out = {"id": status.pk, "type": status.type, "kind": status.kind, "text": status.text, "background": status.background or None,
           "media": None, "created_at": status.created_at.isoformat(), "expires_at": status.expires_at.isoformat(),
           "audience": status.audience if status.author_id == viewer.pk else None,
           "allow_replies": status.allow_replies and status.author_id != viewer.pk, "mine": status.author_id == viewer.pk}
    if seen is not None:
        out["seen"] = seen
    if status.media:
        out["media"] = {"url": messaging.media_url(status.media, request), "mime": status.media_mime, "size": status.media_size, **(status.media_meta or {})}
    if status.author_id == viewer.pk:
        out["views"] = stats if stats is not None else counters(status)
    return out


def counters(status: Status) -> Dict:
    agg = StatusView.objects.filter(status=status).aggregate(unique=Count("id"), total=Sum("count"))
    unique = agg["unique"] or 0
    return {"unique": unique, "total": (agg["total"] or 0) if limits()["repeat_views"] else unique}


# ---------------------------------------------------------------------------------------------------------- publication

def publish(user, *, text: str = "", upload=None, audience: Optional[str] = None, allow_replies: Optional[bool] = None,
            background: str = "", client_id=None) -> Tuple[Status, bool]:
    """Publie un statut (texte, photo, vidéo ou média + texte). Idempotent sur `client_id`."""
    lim = limits()
    text = (text or "").strip()
    if len(text) > lim["text_max"]:
        raise StatusError("text_too_long", f"Texte trop long : {lim['text_max']} caractères au maximum.")
    if not text and upload is None:
        raise StatusError("empty", "Ajoutez un texte, une photo ou une vidéo.")
    if client_id is not None:
        import uuid

        try:
            client_id = uuid.UUID(str(client_id))
        except ValueError:
            raise StatusError("invalid_client_id", "Identifiant d'envoi invalide.")
        previous = Status.objects.filter(author=user, client_id=client_id).first()
        if previous is not None:
            return previous, False
    pref = preference(user)
    audience = audience or pref.audience
    if audience not in dict(Status.AUDIENCES):
        raise StatusError("invalid_audience", "Audience inconnue.")
    if background and background not in BACKGROUNDS:
        raise StatusError("invalid_background", "Couleur inconnue.")
    now = timezone.now()
    if Status.objects.filter(author=user, deleted_at__isnull=True, expires_at__gt=now).count() >= lim["max_active"]:
        raise StatusError("quota", f"Vous avez atteint la limite de {lim['max_active']} statuts actifs. Supprimez-en un ou attendez leur expiration.", 429)
    fields = dict(author=user, text=text, audience=audience, client_id=client_id, kind=Status.TEXT,
                  allow_replies=pref.allow_replies if allow_replies is None else bool(allow_replies),
                  background=(background or "green") if upload is None else "", expires_at=now + timedelta(hours=lim["ttl_hours"]))
    checked = None
    if upload is not None:
        try:
            checked = check_upload(upload, allow=("image", "video"), max_image_bytes=lim["image_max_bytes"], max_video_bytes=lim["video_max_bytes"],
                                   max_side=int(cfg("STATUS_IMAGE_MAX_SIDE", 1600)), max_video_seconds=lim["video_max_seconds"])
        except MediaRejected as exc:
            raise StatusError(exc.code, exc.detail, 413 if exc.code == "too_large" else 400)
        fields.update(kind=Status.PHOTO if checked.kind == "image" else Status.VIDEO, media_mime=checked.mime, media_size=checked.size,
                      media_meta=checked.meta)
    status = Status(**fields)
    if checked is not None:
        status.media.save(checked.content.name, checked.content, save=False)
    try:
        with transaction.atomic():
            status.save()
    except IntegrityError:
        if status.media:
            status.media.delete(save=False)
        existing = Status.objects.filter(author=user, client_id=client_id).first() if client_id else None
        if existing is None:
            raise
        return existing, False
    except Exception:
        if status.media:
            status.media.delete(save=False)             # aucun média orphelin si l'enregistrement échoue
        raise
    bump()
    transaction.on_commit(lambda: _announce(status.pk, "new"))
    return status, True


def _announce(status_id: int, action: str) -> None:
    status = Status.objects.filter(pk=status_id).first()
    if status is None:
        return
    audience = contacts.contact_ids(status.author_id) - set(StatusExclusion.objects.filter(author_id=status.author_id).values_list("excluded_id", flat=True))
    inbox.push(audience | {status.author_id}, {"type": "status", "action": action, "author": status.author_id, "status": status_id})


def delete(user, status_id: int) -> None:
    """Suppression par l'auteur : contenu et média retirés immédiatement (minimisation) ; la ligne reste pour l'audit jusqu'à la purge."""
    status = Status.objects.filter(pk=status_id, author=user, deleted_at__isnull=True).first()
    if status is None:
        raise StatusError("not_found", "Statut introuvable.", 404)
    _soft_delete(status)
    bump()
    transaction.on_commit(lambda: _announce(status_id, "deleted"))


def _soft_delete(status: Status, *, staff: bool = False) -> None:
    media = status.media
    status.deleted_at, status.text, status.removed_by_staff = timezone.now(), "", staff
    status.media_purged_at = timezone.now() if media else status.media_purged_at
    name = media.name if media else None
    status.media = None
    status.save(update_fields=["deleted_at", "text", "removed_by_staff", "media", "media_purged_at"])
    if name:
        transaction.on_commit(lambda: _delete_file(name))


def _delete_file(name: str) -> None:
    from django.core.files.storage import default_storage

    try:
        default_storage.delete(name)
    except Exception:
        logger.warning("Média de statut non supprimé (%s) : la purge périodique réessaiera.", name, exc_info=True)


# ----------------------------------------------------------------------------------------------------------------- fil

def _group(rows: List[Status], viewer, request, seen_ids: set) -> List[Dict]:
    by_author: Dict[int, Dict] = {}
    for st in rows:
        g = by_author.setdefault(st.author_id, {"author": author_payload(st.author, request), "statuses": [], "unseen": 0, "latest_at": st.created_at})
        seen = st.pk in seen_ids
        g["statuses"].append(payload(st, viewer, request, seen=seen))
        g["unseen"] += 0 if seen else 1
        g["latest_at"] = max(g["latest_at"], st.created_at)
    groups = list(by_author.values())
    groups.sort(key=lambda g: (g["unseen"] == 0, -g["latest_at"].timestamp()))     # non lus d'abord, puis le plus récent
    for g in groups:
        g["latest_at"] = g["latest_at"].isoformat()
        g["seen"] = g["unseen"] == 0
    return groups


def feed(viewer, request=None) -> Dict:
    """Accueil : mes statuts, ceux de mes contacts Tratra (non lus d'abord) et le nombre de statuts à découvrir."""
    key = _feed_key(viewer.pk, "feed")
    hit = cache.get(key)
    if hit is not None:
        return hit
    ids = contacts.contact_ids(viewer.pk)
    qs = visible_qs(viewer).select_related("author", "author__handyman_profile").order_by("created_at")
    contact_rows = list(qs.filter(author_id__in=ids).exclude(author=viewer)[:MAX_FEED_STATUSES])
    seen_ids = set(StatusView.objects.filter(viewer=viewer, status_id__in=[s.pk for s in contact_rows]).values_list("status_id", flat=True))
    out = {"mine": mine(viewer, request), "contacts": _group(contact_rows, viewer, request, seen_ids),
           "discover_count": qs.filter(audience=Status.EXTENDED).exclude(author=viewer).exclude(author_id__in=ids).values("author_id").distinct().count(),
           "limits": limits()}
    cache.set(key, out, FEED_CACHE_SECONDS)
    return out


def mine(viewer, request=None) -> Dict:
    now = timezone.now()
    rows = list(Status.objects.filter(author=viewer, deleted_at__isnull=True, expires_at__gt=now).order_by("created_at")
                .annotate(unique_views=Count("views", distinct=True), total_views=Sum("views__count")))
    repeat = limits()["repeat_views"]
    items = [payload(s, viewer, request, stats={"unique": s.unique_views, "total": (s.total_views or 0) if repeat else s.unique_views}) for s in rows]
    return {"author": author_payload(viewer, request), "statuses": items, "count": len(items)}


def discover(viewer, request=None, page: int = 1, size: int = 20) -> Dict:
    """Statuts élargis de membres qui ne sont PAS mes contacts, regroupés par auteur (page « Découvrir les statuts »)."""
    size = max(1, min(int(size), 40))
    page = max(1, int(page))
    ids = contacts.contact_ids(viewer.pk)
    qs = visible_qs(viewer).filter(audience=Status.EXTENDED).exclude(author=viewer).exclude(author_id__in=ids)
    authors = list(qs.values("author_id").annotate(latest=Max("created_at")).order_by("-latest")[(page - 1) * size:page * size + 1])
    more = len(authors) > size
    author_ids = [a["author_id"] for a in authors[:size]]
    rows = list(qs.filter(author_id__in=author_ids).select_related("author", "author__handyman_profile").order_by("created_at"))
    seen_ids = set(StatusView.objects.filter(viewer=viewer, status_id__in=[s.pk for s in rows]).values_list("status_id", flat=True))
    return {"results": _group(rows, viewer, request, seen_ids), "has_more": more, "next_page": page + 1 if more else None}


# ------------------------------------------------------------------------------------------------------------------ vues

def record_view(viewer, status_id: int) -> Dict:
    """Enregistre une vue lorsque le client AFFICHE réellement le statut. Aucune vue pour son propre statut, pour un statut qu'on ne peut
    pas voir (404) ni pour une consultation répétée dans la fenêtre anti-double-comptage."""
    status = visible_qs(viewer).filter(pk=status_id).select_related("author").first()
    if status is None:
        raise StatusError("not_found", "Statut introuvable.", 404)
    if status.author_id == viewer.pk:
        return {"counted": False, "reason": "own"}
    now = timezone.now()
    view, created = StatusView.objects.get_or_create(status=status, viewer=viewer, defaults={"first_viewed_at": now, "last_viewed_at": now})
    counted = created
    if not created and limits()["repeat_views"]:
        window = now - timedelta(seconds=int(cfg("STATUS_VIEW_DEBOUNCE_SECONDS", 30)))
        counted = StatusView.objects.filter(pk=view.pk, last_viewed_at__lte=window).update(count=F("count") + 1, last_viewed_at=now) > 0
    if created or counted:
        bump(viewer.pk)
        if created:
            inbox.push([status.author_id], {"type": "status_view", "status": status.pk, "views": counters(status)})
    return {"counted": counted, "reason": None if counted else "already_counted"}


def viewers(author, status_id: int, page: int = 1, size: int = 50, request=None) -> Dict:
    """Liste NOMINATIVE des lecteurs : réservée à l'auteur (toute autre personne reçoit 404)."""
    status = Status.objects.filter(pk=status_id, author=author, deleted_at__isnull=True).first()
    if status is None:
        raise StatusError("not_found", "Statut introuvable.", 404)
    size = max(1, min(int(size), 100))
    page = max(1, int(page))
    rows = list(StatusView.objects.filter(status=status).select_related("viewer", "viewer__handyman_profile")
                .order_by("-first_viewed_at", "-id")[(page - 1) * size:page * size + 1])
    more = len(rows) > size
    repeat = limits()["repeat_views"]
    return {"counters": counters(status), "repeat_views": repeat, "has_more": more, "next_page": page + 1 if more else None,
            "results": [{"user": author_payload(v.viewer, request), "viewed_at": v.first_viewed_at.isoformat(),
                         **({"last_viewed_at": v.last_viewed_at.isoformat(), "count": v.count} if repeat else {})} for v in rows[:size]]}


# ------------------------------------------------------------------------------------------------- réponse, signalement

def reply(viewer, status_id: int, content: str):
    """Réponse à un statut = message privé vers son auteur (si l'auteur l'autorise), avec le statut en contexte."""
    status = visible_qs(viewer).filter(pk=status_id).select_related("author").first()
    if status is None or status.author_id == viewer.pk:
        raise StatusError("not_found", "Statut introuvable.", 404)
    if not status.allow_replies:
        raise StatusError("replies_disabled", "L'auteur n'accepte pas les réponses à ce statut.", 403)
    try:
        conv, _ = messaging.open_direct(viewer, status.author_id, allow_stranger=True)
        message, created = messaging.send(viewer, conv, content, context={"status": status.pk, "kind": status.kind,
                                                                         "text": (status.text or "")[:80]})
    except messaging.MessagingError as exc:
        raise StatusError(exc.code, exc.detail, exc.status)
    return conv, message


def report(viewer, status_id: int, reason: str) -> StatusReport:
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise StatusError("reason_required", "Indiquez le motif du signalement.")
    status = visible_qs(viewer).filter(pk=status_id).first()
    if status is None or status.author_id == viewer.pk:
        raise StatusError("not_found", "Statut introuvable.", 404)
    return StatusReport.objects.get_or_create(status=status, reporter=viewer, defaults={"reason": reason[:500]})[0]


def remove_by_staff(status: Status) -> None:
    if status.deleted_at is None:
        _soft_delete(status, staff=True)
        bump()


# ----------------------------------------------------------------------------------------------------------- purge

def purge(now=None) -> Dict:
    """Rejouable sans effet double. 1) retire du stockage les médias des statuts expirés depuis `STATUS_MEDIA_RETENTION_HOURS` ;
    2) supprime les lignes très anciennes (`STATUS_ROW_RETENTION_DAYS`) ; 3) supprime les fichiers orphelins (sans statut) de plus de 2 jours."""
    now = now or timezone.now()
    media_cutoff = now - timedelta(hours=int(cfg("STATUS_MEDIA_RETENTION_HOURS", 24)))
    purged = 0
    for st in Status.objects.filter(expires_at__lte=media_cutoff, media_purged_at__isnull=True).exclude(media="").exclude(media__isnull=True)[:500]:
        name = st.media.name
        _delete_file(name)
        Status.objects.filter(pk=st.pk).update(media="", media_purged_at=now)
        purged += 1
    row_cutoff = now - timedelta(days=int(cfg("STATUS_ROW_RETENTION_DAYS", 30)))
    stale = Status.objects.filter(expires_at__lte=row_cutoff, media_purged_at__isnull=False)
    rows_deleted = stale.count()
    stale.delete()
    expired_unpurged = Status.objects.filter(expires_at__lte=now, deleted_at__isnull=True).count()
    return {"media_purged": purged, "rows_deleted": rows_deleted, "orphans_deleted": purge_orphans(now), "expired": expired_unpurged}


def purge_orphans(now, *, max_files: int = 2000, min_age_hours: int = 48) -> int:
    """Fichiers de `statuses/` qu'aucun statut ne référence (échec entre l'envoi du fichier et l'enregistrement) : supprimés après 2 jours."""
    from django.core.files.storage import default_storage

    deleted = seen = 0
    referenced = None
    stack = ["statuses"]
    while stack and seen < max_files:
        folder = stack.pop()
        try:
            dirs, files = default_storage.listdir(folder)
        except Exception:
            continue
        stack.extend(f"{folder}/{d}" for d in dirs)
        for name in files:
            seen += 1
            path = f"{folder}/{name}"
            if referenced is None:
                referenced = set(Status.objects.exclude(media="").exclude(media__isnull=True).values_list("media", flat=True))
            if path in referenced:
                continue
            try:
                mtime = default_storage.get_modified_time(path)
                if timezone.is_naive(mtime):
                    mtime = timezone.make_aware(mtime)
                if now - mtime < timedelta(hours=min_age_hours):
                    continue
                default_storage.delete(path)
                deleted += 1
            except Exception:
                logger.warning("Fichier orphelin %s non traité", path, exc_info=True)
    return deleted
