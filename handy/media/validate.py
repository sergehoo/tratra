"""Validation RÉELLE des médias de la messagerie et des statuts : le type est déduit des octets du fichier (jamais de l'extension
ni du `Content-Type` annoncé par le client), puis le contenu est contrôlé.

 - image : décodée et réencodée par Pillow à partir des seuls pixels (EXIF/GPS supprimés, réduite à `max_side`), JPEG/PNG/WebP ;
 - vidéo : conteneur MP4/MOV (ISO BMFF) analysé — `ftyp`, `moov`, `mvhd` — pour mesurer la durée et les dimensions RÉELLES ; une durée
   supérieure à la limite est refusée. Aucun transcodage n'est fait côté serveur (pas de ffmpeg dans l'image) ;
 - document : PDF seulement (signature `%PDF-`), messagerie uniquement.

Toutes les erreurs sont des `MediaRejected` avec un message destiné à l'utilisateur."""
import io
import struct
from dataclasses import dataclass, field
from typing import Dict, Optional

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

from handy.media.sanitize import sanitize_image

IMAGE_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
VIDEO_BRANDS_REJECTED = frozenset({b"heic", b"heix", b"mif1", b"avif", b"avis", b"msf1"})   # images HEIF/AVIF au conteneur voisin
MAX_MOOV_BYTES = 16 * 1024 * 1024


class MediaRejected(ValueError):
    def __init__(self, detail: str, code: str = "invalid_media"):
        super().__init__(detail)
        self.detail, self.code = detail, code


@dataclass
class Checked:
    kind: str                      # image | video | file
    mime: str
    content: ContentFile
    size: int
    meta: Dict = field(default_factory=dict)


def sniff(head: bytes) -> Optional[str]:
    """Famille du fichier d'après ses premiers octets : image, video, file (PDF) ou None."""
    if head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n" or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
        return "image"
    if head[4:8] == b"ftyp" and head[8:12] not in VIDEO_BRANDS_REJECTED:
        return "video"
    if head[:5] == b"%PDF-":
        return "file"
    return None


def _read(upload, limit: int) -> bytes:
    size = getattr(upload, "size", None)
    if size is not None and size > limit:
        raise MediaRejected(f"Fichier trop lourd : {limit // (1024 * 1024)} Mo au maximum.", "too_large")
    try:
        upload.seek(0)
    except (AttributeError, OSError, ValueError):
        pass
    data = upload.read(limit + 1)
    if len(data) > limit:
        raise MediaRejected(f"Fichier trop lourd : {limit // (1024 * 1024)} Mo au maximum.", "too_large")
    if not data:
        raise MediaRejected("Fichier vide.", "empty")
    return data


# ------------------------------------------------------------------------------------------------------ vidéo (ISO BMFF)

def _boxes(buf: bytes, start: int = 0, end: Optional[int] = None):
    """Boîtes ISO BMFF d'un tampon : (type, début du contenu, fin). Tailles 32 et 64 bits, jamais hors du tampon."""
    end = len(buf) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", buf[pos:pos + 8])
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", buf[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            return
        yield kind, pos + header, pos + size
        pos += size


def inspect_video(data: bytes, *, max_seconds: Optional[float] = None) -> Dict:
    """Mesure la durée et les dimensions d'un MP4/MOV. Lève MediaRejected si le conteneur n'est pas une vidéo exploitable."""
    if data[4:8] != b"ftyp":
        raise MediaRejected("Vidéo invalide : seuls les formats MP4 et MOV sont acceptés.", "invalid_video")
    moov = None
    for kind, a, b in _boxes(data):
        if kind == b"moov":
            if b - a > MAX_MOOV_BYTES:
                raise MediaRejected("Vidéo invalide.", "invalid_video")
            moov = (a, b)
            break
    if moov is None:
        raise MediaRejected("Vidéo invalide ou incomplète : le fichier ne contient pas d'index de lecture.", "invalid_video")
    duration = None
    width = height = None
    has_video_track = False
    for kind, a, b in _boxes(data, *moov):
        if kind == b"mvhd":
            version = data[a]
            if version == 1 and b - a >= 32:
                timescale, dur = struct.unpack(">IQ", data[a + 20:a + 32])
            elif version == 0 and b - a >= 20:
                timescale, dur = struct.unpack(">II", data[a + 12:a + 20])
            else:
                continue
            if timescale:
                duration = dur / timescale
        elif kind == b"trak":
            handler = None
            tk = None
            for k2, a2, b2 in _boxes(data, a, b):
                if k2 == b"tkhd":
                    tk = (a2, b2)
                elif k2 == b"mdia":
                    for k3, a3, b3 in _boxes(data, a2, b2):
                        if k3 == b"hdlr" and b3 - a3 >= 12:
                            handler = data[a3 + 8:a3 + 12]
            if handler == b"vide" and tk:
                has_video_track = True
                a2, b2 = tk
                version = data[a2]
                off = 88 if version == 1 else 76
                if b2 - a2 >= off + 8:
                    width, height = (v >> 16 for v in struct.unpack(">II", data[a2 + off:a2 + off + 8]))
                    mat = a2 + (52 if version == 1 else 40)   # matrice de rotation : 90°/270° => largeur et hauteur échangées
                    ma, mb = struct.unpack(">ii", data[mat:mat + 8])
                    if ma == 0 and mb != 0:
                        width, height = height, width
    if not has_video_track or duration is None or duration <= 0:
        raise MediaRejected("Vidéo invalide : aucune piste vidéo exploitable.", "invalid_video")
    if max_seconds is not None and duration > max_seconds + 0.5:     # tolérance d'une demi-seconde (arrondis des encodeurs)
        raise MediaRejected(f"Vidéo trop longue : {int(max_seconds)} secondes au maximum.", "video_too_long")
    return {"duration": round(duration, 2), "width": width, "height": height}


# --------------------------------------------------------------------------------------------------------------- API

def check_upload(upload, *, allow=("image", "video"), max_image_bytes: int, max_video_bytes: int, max_file_bytes: int = 0,
                 max_side: int = 1600, max_video_seconds: Optional[float] = None, name: str = "") -> Checked:
    """Valide et prépare un fichier envoyé. `allow` ⊆ {image, video, file}. Renvoie le contenu À STOCKER (image réencodée)."""
    head = upload.read(32)
    upload.seek(0)
    family = sniff(head)
    if family is None or family not in allow:
        raise MediaRejected("Format non accepté : " + ", ".join({"image": "photo JPEG, PNG ou WebP", "video": "vidéo MP4 ou MOV",
                                                                "file": "document PDF"}[a] for a in allow) + ".", "unsupported_type")
    if family == "image":
        try:
            sanitized = sanitize_image(upload, allowed_formats=IMAGE_FORMATS, max_side=max_side, max_bytes=max_image_bytes)
        except ValidationError as exc:
            raise MediaRejected(exc.messages[0], "invalid_image") from exc
        from PIL import Image

        with Image.open(io.BytesIO(sanitized.read())) as im:
            width, height = im.size
            mime = "image/png" if im.format == "PNG" else "image/jpeg"
        sanitized.seek(0)
        return Checked("image", mime, sanitized, sanitized.size, {"width": width, "height": height})
    if family == "video":
        data = _read(upload, max_video_bytes)
        meta = inspect_video(data, max_seconds=max_video_seconds)
        quicktime = data[8:12] == b"qt  "
        return Checked("video", "video/quicktime" if quicktime else "video/mp4",
                       ContentFile(data, name=f"{_rand()}.{'mov' if quicktime else 'mp4'}"), len(data), meta)
    data = _read(upload, max_file_bytes or max_image_bytes)
    return Checked("file", "application/pdf", ContentFile(data, name=f"{_rand()}.pdf"), len(data), {})


def _rand() -> str:
    import uuid

    return uuid.uuid4().hex
