"""Réencodage des images publiques (§10 L1a, S-S3 du document de conception).

Toute image destinée à être servie publiquement (images et bannières de services,
médias d'avis) est décodée puis réencodée par Pillow à partir de ses seuls pixels :

- les métadonnées (EXIF dont la position GPS, XMP, IPTC, commentaires, profils
  embarqués) sont supprimées ; l'orientation EXIF est appliquée aux pixels avant ;
- seuls les formats JPEG, PNG et WebP sont acceptés par l'API (un PDF, un SVG, un
  exécutable renommé en ``.jpg`` sont refusés) ;
- les dimensions sont conservées, sauf au-delà de ``PUBLIC_IMAGE_MAX_SIDE`` où
  l'image est réduite proportionnellement ; une image de plus de
  ``PUBLIC_IMAGE_MAX_PIXELS`` pixels est refusée (bombe de décompression) ;
- le fichier reçoit un nom aléatoire (le nom d'origine peut contenir des données
  personnelles) ; sortie PNG si l'image a de la transparence, JPEG sinon.
"""
import io
import uuid
import warnings
from typing import FrozenSet, Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

PUBLIC_IMAGE_FORMATS: FrozenSet[str] = frozenset({"JPEG", "PNG", "WEBP"})
JPEG_QUALITY = 85

# Attribut posé sur le fichier produit : évite un second réencodage (signal pre_save).
SANITIZED_MARKER = "tratra_sanitized"

_INVALID = "Image invalide : formats acceptés JPEG, PNG ou WebP."


def _setting(name: str, default: int) -> int:
    return int(getattr(settings, name, default))


def _rewind(file_obj) -> None:
    try:
        file_obj.seek(0)
    except (AttributeError, OSError, ValueError):
        pass


def sanitize_image(file_obj, *, allowed_formats: Optional[FrozenSet[str]] = PUBLIC_IMAGE_FORMATS,
                   max_side: Optional[int] = None, max_pixels: Optional[int] = None,
                   max_bytes: Optional[int] = None) -> ContentFile:
    """Décode ``file_obj`` et renvoie un ``ContentFile`` réencodé, sans métadonnées.

    ``allowed_formats=None`` accepte tout format matriciel décodable par Pillow
    (chemin d'administration) ; l'API passe la liste fermée JPEG, PNG, WebP.
    Lève ``django.core.exceptions.ValidationError`` (code ``invalid_image``).
    """
    max_side = max_side or _setting("PUBLIC_IMAGE_MAX_SIDE", 2048)
    max_pixels = max_pixels or _setting("PUBLIC_IMAGE_MAX_PIXELS", 50_000_000)
    max_bytes = max_bytes or _setting("PUBLIC_IMAGE_MAX_UPLOAD_BYTES", 10 * 1024 * 1024)

    size = getattr(file_obj, "size", None)
    if size is not None and size > max_bytes:
        raise ValidationError(
            f"Image trop lourde : {max_bytes // (1024 * 1024)} Mo au maximum.", code="invalid_image")

    _rewind(file_obj)
    try:
        with warnings.catch_warnings():
            # DecompressionBombWarning -> erreur : la borne est vérifiée juste après.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(file_obj) as probe:
                fmt = (probe.format or "").upper()
                width, height = probe.size
            if allowed_formats is not None and fmt not in allowed_formats:
                raise ValidationError(_INVALID, code="invalid_image")
            if width <= 0 or height <= 0 or width * height > max_pixels:
                raise ValidationError("Image trop grande.", code="invalid_image")
            _rewind(file_obj)
            with Image.open(file_obj) as img:
                # JPEG : décodage directement à l'échelle utile (mémoire bornée).
                img.draft("RGB", (max_side, max_side))
                img.load()  # décode réellement les pixels (fichier tronqué -> erreur)
                img = ImageOps.exif_transpose(img)
                has_alpha = img.mode in ("RGBA", "LA", "PA") or (
                    img.mode == "P" and "transparency" in img.info)
                img = img.convert("RGBA" if has_alpha else "RGB")
                if max(img.size) > max_side:
                    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
                # Nouvelle image construite à partir des SEULS pixels : aucun bloc
                # EXIF / XMP / ICC / texte ne peut survivre au réencodage.
                clean = Image.frombytes(img.mode, img.size, img.tobytes())
    except ValidationError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning,
            OSError, SyntaxError, ValueError, TypeError) as exc:
        raise ValidationError(_INVALID, code="invalid_image") from exc
    finally:
        _rewind(file_obj)

    buffer = io.BytesIO()
    if has_alpha:
        clean.save(buffer, format="PNG", optimize=True)
        ext = "png"
    else:
        clean.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        ext = "jpg"
    content = ContentFile(buffer.getvalue(), name=f"{uuid.uuid4().hex}.{ext}")
    setattr(content, SANITIZED_MARKER, True)
    return content


def is_sanitized(file_obj) -> bool:
    return bool(getattr(file_obj, SANITIZED_MARKER, False))


def sanitize_new_upload(instance, field_name: str) -> None:
    """Réencode le fichier d'un ``ImageField`` s'il s'agit d'un NOUVEL envoi.

    Appelé par le signal ``pre_save`` (admin, commandes, tout chemin hors API) :
    un fichier déjà en base (``_committed``) n'est jamais relu ni réécrit, et un
    fichier déjà produit par :func:`sanitize_image` (chemin API) n'est pas
    réencodé une seconde fois.
    """
    field_file = getattr(instance, field_name, None)
    if not field_file or getattr(field_file, "_committed", True):
        return
    pending = getattr(field_file, "_file", None)
    if pending is None or is_sanitized(pending):
        return
    setattr(instance, field_name, sanitize_image(pending, allowed_formats=None))
