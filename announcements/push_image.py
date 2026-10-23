"""Image des notifications push d'une annonce.

Android affiche l'image d'une notification déroulée au format paysage 2:1 : on en produit donc une variante dédiée, recadrée au
centre (ce que montre l'aperçu du Back-Office), réduite à 1024 x 512 au plus (jamais agrandie), en JPEG léger (< 300 Ko) — la
transparence est posée sur fond blanc. Elle est générée une fois, à la diffusion, à partir de l'image déjà réencodée sans
métadonnées. Son adresse n'est transmise que si elle est publique et en HTTPS ; sinon la notification part sans image (texte seul).
"""
import io
import logging
import uuid
from typing import Optional
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, ImageOps

from handy.media.sanitize import SANITIZED_MARKER

logger = logging.getLogger(__name__)

RATIO = 2.0
MAX_SIZE = (1024, 512)
MAX_BYTES = 300 * 1024


def render(source) -> bytes:
    """JPEG 2:1 recadré au centre, sans agrandissement, sous MAX_BYTES (qualité abaissée si besoin)."""
    with Image.open(source) as img:
        img.draft("RGB", (MAX_SIZE[0] * 2, MAX_SIZE[0] * 2))
        img.load()
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            img = flat
        else:
            img = img.convert("RGB")
    w, h = img.size
    if w / h > RATIO:                                   # trop large : on rogne les côtés
        cw = int(round(h * RATIO))
        box = ((w - cw) // 2, 0, (w - cw) // 2 + cw, h)
    else:                                               # trop haute : on rogne le haut et le bas
        ch = int(round(w / RATIO))
        box = (0, (h - ch) // 2, w, (h - ch) // 2 + ch)
    img = img.crop(box)
    if img.width > MAX_SIZE[0]:
        img = img.resize(MAX_SIZE, Image.Resampling.LANCZOS)
    for quality in (82, 72, 62, 52):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
        if buf.tell() <= MAX_BYTES:
            break
    return buf.getvalue()


def ensure(announcement) -> bool:
    """Génère (une seule fois par image d'origine) la variante push. Vrai si elle est disponible ; jamais d'exception."""
    from announcements.models import Announcement

    a = announcement
    if not a.image:
        return False
    if a.push_image and a.push_image_source == a.image.name:
        return True
    try:
        with a.image.open("rb") as fh:
            data = render(fh)
        content = ContentFile(data, name=f"{uuid.uuid4().hex}.jpg")
        setattr(content, SANITIZED_MARKER, True)          # déjà réencodée : pas de second passage
        old = a.push_image.name if a.push_image else ""
        a.push_image.save(content.name, content, save=False)
        a.push_image_source = a.image.name
        Announcement.objects.filter(pk=a.pk).update(push_image=a.push_image.name, push_image_source=a.push_image_source)
        if old and old != a.push_image.name:
            try:
                a.push_image.storage.delete(old)
            except Exception:
                logger.warning("Ancienne image push de l'annonce #%s non supprimée.", a.pk, exc_info=True)
        return True
    except Exception:
        logger.warning("Image push de l'annonce #%s non générée : notification texte seul.", a.pk, exc_info=True)
        return False


def public_url(announcement) -> Optional[str]:
    """Adresse PUBLIQUE de la variante push, ou None (absente, ou pas en HTTPS alors que c'est exigé)."""
    a = announcement
    if not a.push_image or a.push_image_source != (a.image.name if a.image else ""):
        return None
    try:
        url = a.push_image.url
    except Exception:
        return None
    if not urlsplit(url).scheme:
        base = (getattr(settings, "API_PUBLIC_URL", "") or "").rstrip("/")
        if not base:
            return None
        url = urljoin(base + "/", url.lstrip("/"))
    scheme = urlsplit(url).scheme
    if scheme == "https" or (scheme == "http" and not getattr(settings, "PUSH_IMAGE_REQUIRE_HTTPS", True)):
        return url
    return None
