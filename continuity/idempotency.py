"""Écritures rejouables sans doublon : en-tête `Idempotency-Key` (identifiant unique généré par le client pour UNE intention).

 * même clé + même requête  → la réponse d'origine est rejouée (en-tête `Idempotent-Replay: true`) ;
 * même clé + requête différente → 422 `idempotency_key_reuse` (jamais d'exécution silencieuse d'une autre action) ;
 * deux requêtes simultanées avec la même clé → sérialisées par l'unicité en base (la seconde rejoue la première) ;
 * erreur (4xx/5xx ou exception) → rien n'est mémorisé et la clé reste réutilisable après correction.
Sans en-tête, l'appel se comporte comme avant (compatibilité des anciens clients)."""
import hashlib
import json
import re

from django.db import transaction
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from continuity.models import IdempotencyRecord

HEADER = "Idempotency-Key"
KEY_RE = re.compile(r"^[A-Za-z0-9_\-:.]{8,80}$")


def _fingerprint(request) -> str:
    data = request.data
    items = {}
    for name in sorted(data.keys()) if hasattr(data, "keys") else []:
        values = data.getlist(name) if hasattr(data, "getlist") else [data[name]]
        items[name] = [f"file:{getattr(v, 'name', '')}:{getattr(v, 'size', '')}" if hasattr(v, "read") else v for v in values]
    raw = json.dumps([request.method, request.path, items], sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def run_idempotent(request, scope: str, handler):
    """Exécute `handler()` (renvoie une Response DRF) une seule fois par (utilisateur, scope, clé)."""
    key = request.headers.get(HEADER)
    if not key:
        return handler()
    if not KEY_RE.match(key):
        return Response({"code": "invalid_idempotency_key", "detail": "Clé d'idempotence invalide (8 à 80 caractères : lettres, chiffres, - _ : .)."},
                        status=status.HTTP_400_BAD_REQUEST)
    fingerprint = _fingerprint(request)
    with transaction.atomic():
        record, created = IdempotencyRecord.objects.get_or_create(
            user=request.user, scope=scope, key=key, defaults={"request_hash": fingerprint})
        if not created:
            if record.request_hash != fingerprint:
                return Response({"code": "idempotency_key_reuse", "detail": "Cette clé a déjà servi pour une autre requête."},
                                status=status.HTTP_422_UNPROCESSABLE_ENTITY)
            replay = Response(record.response, status=record.status_code or status.HTTP_200_OK)
            replay["Idempotent-Replay"] = "true"
            return replay
        response = handler()
        if 200 <= response.status_code < 300:
            record.status_code = response.status_code
            record.response = json.loads(JSONRenderer().render(response.data)) if response.data is not None else None
            record.save(update_fields=["status_code", "response"])
        else:
            transaction.set_rollback(True)   # l'erreur n'est pas mémorisée : la clé reste utilisable
        return response
