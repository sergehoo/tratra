"""Justificatifs d'engagement (paiement, frais) : mêmes règles que tous les justificatifs privés (`handy.media.receipts`) — image
réencodée sans métadonnées, ou PDF simple (sans script, fichier embarqué ni chiffrement) ; 5 Mo au maximum ; stockage privé."""
from typing import Optional

from engagements.services.common import EngagementError
from handy.media.receipts import MAX_BYTES, ReceiptRefused, clean_receipt  # noqa: F401  (MAX_BYTES réexporté)


def clean_evidence(upload) -> Optional[object]:
    try:
        return clean_receipt(upload)
    except ReceiptRefused as exc:
        raise EngagementError("invalid", exc.message, 400, fields={"evidence": exc.message})
