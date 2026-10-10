"""Justificatifs (paiement, frais) : image JPEG/PNG/WebP réencodée sans métadonnées, ou PDF ; 5 Mo au maximum ; stockage privé."""
from typing import Optional

from django.core.exceptions import ValidationError

from engagements.services.common import EngagementError
from handy.media.sanitize import sanitize_image

MAX_BYTES = 5 * 1024 * 1024


def clean_evidence(upload) -> Optional[object]:
    if upload is None:
        return None
    if getattr(upload, "size", 0) > MAX_BYTES:
        raise EngagementError("invalid", "Justificatif trop lourd (5 Mo au maximum).", 400, fields={"evidence": "Justificatif trop lourd (5 Mo au maximum)."})
    head = upload.read(8)
    upload.seek(0)
    if head.startswith(b"%PDF-"):
        return upload                                           # PDF accepté tel quel (aucune exécution, lecture par téléchargement)
    try:
        return sanitize_image(upload, max_bytes=MAX_BYTES)
    except ValidationError:
        raise EngagementError("invalid", "Justificatif invalide : image JPEG, PNG, WebP ou PDF attendu.", 400,
                              fields={"evidence": "Justificatif invalide : image JPEG, PNG, WebP ou PDF attendu."})
