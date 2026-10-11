"""Routeur d'IA : DeepSeek en priorité, Anthropic en repli (ordre configurable `AI_PROVIDERS`).

 - aucune dépendance obligatoire : sans clé, `complete()` lève `AIUnavailable` et les règles déterministes prennent le relais ;
 - une tâche SENSIBLE (document KYC) n'est envoyée à un fournisseur externe que si `AI_KYC_EXTERNAL_ENABLED` est activé ET qu'une base
   légale `AI_KYC_LEGAL_BASIS` est renseignée ; sinon refus immédiat, aucun octet ne sort ;
 - les images ne partent que vers un fournisseur qui les lit (Anthropic) ; DeepSeek ne reçoit que du texte ;
 - le contenu et les clés ne sont jamais journalisés : `AIRun` ne garde que fournisseur, tâche, durée et code d'erreur."""
import base64
import json
import logging
import time
from typing import Dict, List, Optional

import requests
from django.conf import settings

from intelligence.models import AIRun

logger = logging.getLogger(__name__)


class AIUnavailable(Exception):
    """Aucun fournisseur utilisable pour cette tâche (non configuré, refusé par les garde-fous, ou en panne)."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code, self.detail = code, detail


def _cfg(name: str, default=""):
    return getattr(settings, name, default)


def provider_order() -> List[str]:
    return [p.strip().lower() for p in str(_cfg("AI_PROVIDERS", "deepseek,anthropic")).split(",") if p.strip().lower() in ("deepseek", "anthropic")]


def configured(name: str) -> bool:
    return bool(_cfg(f"AI_{name.upper()}_API_KEY"))


def kyc_external_allowed() -> bool:
    """Garde-fou : activation explicite + base légale renseignée + au moins un fournisseur configuré."""
    return bool(_cfg("AI_KYC_EXTERNAL_ENABLED", False)) and bool(str(_cfg("AI_KYC_LEGAL_BASIS", "")).strip()) and any(configured(p) for p in provider_order())


def status() -> Dict:
    """État public (booléens uniquement : jamais une clé, un modèle secret ou une base légale détaillée)."""
    return {"providers": [{"name": p, "configured": configured(p), "images": p == "anthropic"} for p in provider_order()],
            "kyc_external_enabled": bool(_cfg("AI_KYC_EXTERNAL_ENABLED", False)), "legal_basis_set": bool(str(_cfg("AI_KYC_LEGAL_BASIS", "")).strip()),
            "kyc_external_allowed": kyc_external_allowed()}


def _deepseek(system: str, user: str, images, json_mode: bool) -> str:
    r = requests.post(f"{str(_cfg('AI_DEEPSEEK_URL')).rstrip('/')}/chat/completions", timeout=int(_cfg("AI_TIMEOUT", 30)),
                      headers={"Authorization": f"Bearer {_cfg('AI_DEEPSEEK_API_KEY')}", "Content-Type": "application/json"},
                      json={"model": _cfg("AI_DEEPSEEK_MODEL"), "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                            "temperature": 0, **({"response_format": {"type": "json_object"}} if json_mode else {})})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _anthropic(system: str, user: str, images, json_mode: bool) -> str:
    blocks = []
    for mime, data in images or []:
        kind = "document" if mime == "application/pdf" else "image"
        blocks.append({"type": kind, "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(data).decode()}})
    blocks.append({"type": "text", "text": user + ("\n\nRéponds UNIQUEMENT par un objet JSON valide." if json_mode else "")})
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=int(_cfg("AI_TIMEOUT", 30)),
                      headers={"x-api-key": _cfg("AI_ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01", "content-type": "application/json"},
                      json={"model": _cfg("AI_ANTHROPIC_MODEL"), "max_tokens": 1024, "temperature": 0, "system": system, "messages": [{"role": "user", "content": blocks}]})
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")


_CALLS = {"deepseek": _deepseek, "anthropic": _anthropic}


def complete(task: str, system: str, user: str, *, images: Optional[List] = None, sensitive: bool = False, json_mode: bool = True) -> Dict:
    """Premier fournisseur utilisable ; repli automatique en cas d'échec. Renvoie {provider, text, data?}."""
    if sensitive and not kyc_external_allowed():
        raise AIUnavailable("external_not_allowed", "L'envoi de documents à un fournisseur d'IA externe n'est pas autorisé (activation explicite et base légale requises).")
    candidates = [p for p in provider_order() if configured(p) and (not images or p == "anthropic")]
    if not candidates:
        raise AIUnavailable("not_configured", "Aucun fournisseur d'IA configuré pour cette tâche.")
    last = "unavailable"
    for name in candidates:
        started = time.monotonic()
        try:
            text = _CALLS[name](system, user, images, json_mode)
            AIRun.objects.create(provider=name, task=task, ok=True, sensitive=sensitive, latency_ms=int((time.monotonic() - started) * 1000))
            out = {"provider": name, "text": text}
            if json_mode:
                out["data"] = _parse_json(text)
            return out
        except Exception as exc:  # noqa: BLE001 - un fournisseur en échec laisse la main au suivant ; rien du contenu n'est journalisé
            last = type(exc).__name__
            logger.warning("Fournisseur d'IA %s en échec (%s)", name, last)
            AIRun.objects.create(provider=name, task=task, ok=False, sensitive=sensitive, error_code=last[:40], latency_ms=int((time.monotonic() - started) * 1000))
    raise AIUnavailable("all_failed", "Les fournisseurs d'IA sont indisponibles pour le moment.")


def _parse_json(text: str) -> Dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("réponse non JSON")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("objet JSON attendu")
    return data
