"""Fournisseur de liveness et de comparaison visage/document : interface agnostique.

 - `none` (défaut) : aucun fournisseur réel ; le serveur ne produit JAMAIS de résultat favorable (dossier EN ATTENTE, revue humaine) ;
 - `http` : contrat générique (voir docs/kyc-biometrique.md) à brancher sur le fournisseur retenu ; seul lui reçoit les captures ;
 - jamais DeepSeek ni Anthropic : ce sont des IA génératives, pas des moteurs biométriques ;
 - aucun fournisseur « simulé » n'est sélectionnable par la configuration : les tests injectent le leur (biometrics/testing.py)."""
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

Frame = Tuple[str, bytes]          # (type de capture, JPEG)


class ProviderError(Exception):
    """Fournisseur injoignable ou réponse inexploitable (jamais de contenu ni de clé dans le message)."""


@dataclass
class ProviderResult:
    liveness_passed: Optional[bool]
    liveness_score: Optional[float] = None
    match_score: Optional[float] = None
    flags: List[str] = field(default_factory=list)       # ex. screen_replay, mask, deepfake : indices techniques


class BiometricProvider:
    name = "none"

    def configured(self) -> bool:
        return False

    def verify(self, *, reference: str, challenges: List[str], frames: List[Frame], document: Optional[bytes]) -> ProviderResult:  # pragma: no cover - interface
        raise NotImplementedError


class NoProvider(BiometricProvider):
    name = "none"


class HttpProvider(BiometricProvider):
    """POST {BIOMETRIC_API_URL}/verify (multipart : `frames`, `document`, `session`, `challenges`), Authorization: Bearer <clé>.
    Réponse JSON : {"liveness": {"passed": bool, "score": 0..1}, "match": {"score": 0..1}, "flags": [str]}."""
    name = "http"

    def configured(self) -> bool:
        return bool(getattr(settings, "BIOMETRIC_API_URL", "")) and bool(getattr(settings, "BIOMETRIC_API_KEY", ""))

    def verify(self, *, reference, challenges, frames, document):
        files = [("frames", (f"{kind}.jpg", data, "image/jpeg")) for kind, data in frames]
        if document:
            files.append(("document", ("document.jpg", document, "image/jpeg")))
        try:
            r = requests.post(f"{settings.BIOMETRIC_API_URL.rstrip('/')}/verify", headers={"Authorization": f"Bearer {settings.BIOMETRIC_API_KEY}"},
                              data={"session": reference, "challenges": json.dumps(challenges)}, files=files, timeout=int(getattr(settings, "BIOMETRIC_TIMEOUT", 20)))
            r.raise_for_status()
            body = r.json()
            liveness, match = body.get("liveness") or {}, body.get("match") or {}
            passed = liveness.get("passed")
            if passed is not None and not isinstance(passed, bool):
                raise ValueError("liveness.passed invalide")
            return ProviderResult(liveness_passed=passed, liveness_score=_num(liveness.get("score")), match_score=_num(match.get("score")),
                                  flags=[str(x)[:40] for x in (body.get("flags") or [])][:10])
        except Exception as exc:  # noqa: BLE001 - jamais d'URL, de clé ni de contenu dans les journaux
            logger.warning("Fournisseur biométrique indisponible (%s)", type(exc).__name__)
            raise ProviderError(type(exc).__name__)


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if 0.0 <= f <= 1.0 else None


_PROVIDERS = {"none": NoProvider, "http": HttpProvider}


def get_provider() -> BiometricProvider:
    return _PROVIDERS.get(str(getattr(settings, "BIOMETRIC_PROVIDER", "none")).lower(), NoProvider)()
