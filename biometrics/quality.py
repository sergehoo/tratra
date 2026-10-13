"""Contrôles techniques d'une capture (cadrage minimal, éclairage, netteté) : de vrais calculs sur l'image, sans modèle d'IA.
Ils servent à demander une nouvelle prise ; ils ne prouvent ni la présence d'un visage ni la présence réelle de la personne."""
import io
from typing import Dict, List, Tuple

from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError

MIN_SIDE = 480
MIN_BRIGHTNESS, MAX_BRIGHTNESS = 45.0, 220.0
MIN_SHARPNESS = 40.0          # variance du filtre de contours (échelle 0-255²) : en dessous, image floue
MAX_BYTES = 4 * 1024 * 1024


class CaptureRejected(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code, self.detail = code, detail


MESSAGES = {
    "not_jpeg": "Format non pris en charge (JPEG attendu).", "too_large": "Image trop volumineuse.", "unreadable": "Image illisible.",
    "too_small": "Image trop petite : rapprochez-vous de l'écran.", "too_dark": "Éclairage insuffisant : placez-vous face à une source de lumière.",
    "too_bright": "Image surexposée : évitez le contre-jour.", "blurry": "Image floue : tenez le téléphone immobile.",
}


def analyze(data: bytes) -> Tuple[Dict, List[str]]:
    """Renvoie (métriques, problèmes) ; `problems` vide = capture exploitable."""
    if len(data) > MAX_BYTES:
        raise CaptureRejected("too_large", MESSAGES["too_large"])
    if not data.startswith(b"\xff\xd8\xff"):
        raise CaptureRejected("not_jpeg", MESSAGES["not_jpeg"])
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError):
        raise CaptureRejected("unreadable", MESSAGES["unreadable"])
    width, height = img.size
    gray = img.convert("L")
    small = gray.resize((min(width, 640), max(1, int(height * min(width, 640) / width))))
    brightness = ImageStat.Stat(small).mean[0]
    edges = small.filter(ImageFilter.FIND_EDGES)
    w, h = edges.size
    sharpness = ImageStat.Stat(edges.crop((3, 3, max(4, w - 3), max(4, h - 3)))).var[0]       # sans la bordure : le filtre y laisse des artefacts
    metrics = {"width": width, "height": height, "brightness": round(brightness, 1), "sharpness": round(sharpness, 1)}
    problems = []
    if min(width, height) < MIN_SIDE:
        problems.append("too_small")
    if brightness < MIN_BRIGHTNESS:
        problems.append("too_dark")
    elif brightness > MAX_BRIGHTNESS:
        problems.append("too_bright")
    if sharpness < MIN_SHARPNESS:
        problems.append("blurry")
    return metrics, problems
