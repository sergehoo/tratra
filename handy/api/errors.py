"""Erreurs codées de l'API (décision D13, §4.0 du document de conception).

Toute réponse qui porte un code du catalogue (annexe D) a la forme :

    {"code": "handyman_mismatch", "detail": "Message lisible.", "fields": {...}?, ...extra}

où ``fields`` vaut ``{champ: [{"code": "...", "message": "..."}]}``. Les vues et
serializers lèvent :class:`CodedAPIException` ; le gestionnaire global
:func:`exception_handler` (``REST_FRAMEWORK["EXCEPTION_HANDLER"]``) la sérialise.

Les autres erreurs DRF (validation de champ, 401, 403, 404, 405, 429…) gardent
EXACTEMENT leur format historique : les clients installés (React, Flutter) les
lisent tels quels. Seule exception ajoutée : une suppression bloquée par une
relation ``PROTECT`` (migration 0029) renvoie 409 au lieu d'une erreur 500.
"""
from typing import Dict, List, Optional

from django.db.models import ProtectedError, RestrictedError
from rest_framework import status as http_status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.views import set_rollback

FieldErrors = Dict[str, List[Dict[str, str]]]

PROTECTED_DELETE_DETAIL = (
    "Suppression impossible : des données liées (réservations, paiements, avis…) "
    "doivent être conservées."
)


def field_error(code: str, message: str) -> Dict[str, str]:
    """Une entrée de ``fields`` : ``{"code": ..., "message": ...}``."""
    return {"code": code, "message": str(message)}


class CodedAPIException(APIException):
    """Erreur métier portant un code stable du catalogue (annexe D).

    ``CodedAPIException("handyman_mismatch", "…", status=400,
    fields={"handyman": [field_error("handyman_mismatch", "…")]}, retry_after=42)``

    Elle n'hérite PAS de ``ValidationError`` : levée dans ``validate()`` d'un
    serializer, elle traverse ``is_valid()`` et atteint le gestionnaire global
    sans être convertie au format DRF ``{champ: [messages]}``.
    """

    status_code = http_status.HTTP_400_BAD_REQUEST
    default_code = "error"
    default_detail = "Requête refusée."

    def __init__(self, code: str, detail: Optional[str] = None,
                 status: int = http_status.HTTP_400_BAD_REQUEST,
                 fields: Optional[FieldErrors] = None, **extra):
        super().__init__(detail=detail or self.default_detail, code=code)
        self.code = code
        self.status_code = status
        self.fields = fields or None
        self.extra = extra

    def as_payload(self) -> dict:
        payload = {"code": self.code, "detail": str(self.detail)}
        if self.fields:
            payload["fields"] = self.fields
        for key, value in self.extra.items():
            payload.setdefault(key, value)
        return payload


def exception_handler(exc, context):
    """Gestionnaire global : format codé pour ``CodedAPIException``, 409 pour une
    suppression protégée, comportement DRF inchangé pour tout le reste."""
    if isinstance(exc, CodedAPIException):
        set_rollback()
        return Response(exc.as_payload(), status=exc.status_code)
    if isinstance(exc, (ProtectedError, RestrictedError)):
        # Auparavant : suppression en cascade (perte de paiements, avis…).
        # Depuis 0029 : refus explicite plutôt qu'une erreur 500.
        set_rollback()
        return Response({"detail": PROTECTED_DELETE_DETAIL}, status=http_status.HTTP_409_CONFLICT)
    return drf_exception_handler(exc, context)
