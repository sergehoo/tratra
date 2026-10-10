"""Justificatifs (paiement, frais) : image JPEG/PNG/WebP réencodée sans métadonnées, ou PDF ; 5 Mo au maximum ; stockage privé.

PDF : accepté tel quel (aucune exécution côté serveur ; téléchargement privé, `nosniff`, `no-store`) MAIS refusé s'il porte des
éléments actifs ou opaques — JavaScript, lancement de programme, fichier embarqué, média riche, envoi de formulaire, chiffrement.
Contrôle heuristique de défense en profondeur : les lecteurs de l'application (Android PdfRenderer, iOS PDFKit) n'exécutent
aucun script, et le navigateur ouvre le PDF dans son lecteur isolé."""
import re
from typing import Optional

from django.core.exceptions import ValidationError

from engagements.services.common import EngagementError
from handy.media.sanitize import sanitize_image

MAX_BYTES = 5 * 1024 * 1024
# Noms PDF actifs ou opaques (voir l'en-tête du module). La frontière `(?![A-Za-z0-9])` évite de confondre `/JSON` ou `/Launcher`.
_ACTIVE_PDF = re.compile(rb"/(JavaScript|JS|Launch|EmbeddedFiles?|RichMedia|SubmitForm|ImportData|GoToR|GoToE|Encrypt)(?![A-Za-z0-9])")


def clean_evidence(upload) -> Optional[object]:
    if upload is None:
        return None
    if getattr(upload, "size", 0) > MAX_BYTES:
        raise EngagementError("invalid", "Justificatif trop lourd (5 Mo au maximum).", 400, fields={"evidence": "Justificatif trop lourd (5 Mo au maximum)."})
    head = upload.read(8)
    upload.seek(0)
    if head.startswith(b"%PDF-"):
        content = upload.read()
        upload.seek(0)
        if _ACTIVE_PDF.search(content):
            raise EngagementError("invalid", "Ce PDF contient des éléments actifs (script, fichier embarqué, chiffrement) : il est refusé. Joignez une version simple ou une photo du document.", 400,
                                  fields={"evidence": "PDF refusé : éléments actifs ou chiffrés."})
        return upload                                           # PDF simple accepté tel quel (aucune exécution, lecture par téléchargement)
    try:
        return sanitize_image(upload, max_bytes=MAX_BYTES)
    except ValidationError:
        raise EngagementError("invalid", "Justificatif invalide : image JPEG, PNG, WebP ou PDF attendu.", 400,
                              fields={"evidence": "Justificatif invalide : image JPEG, PNG, WebP ou PDF attendu."})
