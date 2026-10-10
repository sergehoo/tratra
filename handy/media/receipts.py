"""Justificatifs PRIVÉS (reçu d'un paiement en espèces ou entre parties) : image JPEG/PNG/WebP réencodée sans métadonnées, ou PDF ;
5 Mo au maximum ; stockage privé (jamais d'URL publique).

PDF : accepté tel quel (aucune exécution côté serveur ; téléchargement privé, `nosniff`, `no-store`) MAIS refusé s'il porte des
éléments actifs ou opaques — JavaScript, lancement de programme, fichier embarqué, média riche, envoi de formulaire, chiffrement.
Contrôle heuristique de défense en profondeur : les lecteurs de l'application (Android PdfRenderer, iOS PDFKit) n'exécutent
aucun script, et le navigateur ouvre le PDF dans son lecteur isolé."""
import re
from typing import Optional

from django.core.exceptions import ValidationError

from handy.media.sanitize import sanitize_image

MAX_BYTES = 5 * 1024 * 1024
# Noms PDF actifs ou opaques. La frontière `(?![A-Za-z0-9])` évite de confondre `/JSON` ou `/Launcher`.
_ACTIVE_PDF = re.compile(rb"/(JavaScript|JS|Launch|EmbeddedFiles?|RichMedia|SubmitForm|ImportData|GoToR|GoToE|Encrypt)(?![A-Za-z0-9])")

TOO_HEAVY = "Justificatif trop lourd (5 Mo au maximum)."
ACTIVE_PDF = "Ce PDF contient des éléments actifs (script, fichier embarqué, chiffrement) : il est refusé. Joignez une version simple ou une photo du document."
INVALID = "Justificatif invalide : image JPEG, PNG, WebP ou PDF attendu."


class ReceiptRefused(Exception):
    """Justificatif refusé : `message` en français, affichable tel quel."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def clean_receipt(upload) -> Optional[object]:
    """Fichier prêt à stocker (image réencodée ou PDF simple), ou None si aucun justificatif. Lève `ReceiptRefused`."""
    if upload is None:
        return None
    if getattr(upload, "size", 0) > MAX_BYTES:
        raise ReceiptRefused(TOO_HEAVY)
    head = upload.read(8)
    upload.seek(0)
    if head.startswith(b"%PDF-"):
        content = upload.read()
        upload.seek(0)
        if _ACTIVE_PDF.search(content):
            raise ReceiptRefused(ACTIVE_PDF)
        return upload
    try:
        return sanitize_image(upload, max_bytes=MAX_BYTES)
    except ValidationError:
        raise ReceiptRefused(INVALID)
