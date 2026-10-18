"""Dialogue avec outils et diffusion progressive (streaming) : DeepSeek en priorité, Anthropic en repli.

Complète `intelligence.ai` (tâches ponctuelles en JSON) pour l'assistant du Back-Office, qui a besoin de deux choses en plus :
 - des APPELS D'OUTILS (fonctions déclarées côté serveur, exécutées par le serveur, jamais par le fournisseur) ;
 - la DIFFUSION de la réponse au fil de l'eau.

Règles :
 - mêmes clés, même ordre de priorité et même journal `AIRun` que `intelligence.ai` (jamais de contenu, de clé ni de requête journalisés) ;
 - le repli vers le fournisseur suivant n'a lieu que si le premier a échoué AVANT d'avoir produit le moindre texte ou appel d'outil :
   après, une coupure lève `ChatInterrupted` (on ne mélange jamais deux réponses) ;
 - chaque appel a un délai de connexion, un délai de lecture et une échéance globale (`deadline`) ;
 - messages internes neutres : {"role": "user"|"assistant"|"tool", ...} ; la conversion vers chaque fournisseur est faite ici.

Événements produits par `stream_chat` (dictionnaires) :
   {"type": "delta", "text": str}  ·  {"type": "tool_calls", "calls": [ToolCall]}  ·  {"type": "usage", "tokens_in": int, "tokens_out": int}
   {"type": "end", "provider": str}"""
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

import requests

from intelligence import ai
from intelligence.models import AIRun

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5


class ChatInterrupted(Exception):
    """Le fournisseur s'est interrompu APRÈS avoir commencé à répondre : la réponse partielle est conservée, jamais complétée par un autre."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ChatFailure(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict = field(default_factory=dict)
    invalid: bool = False        # arguments non JSON : l'outil ne s'exécute pas, l'erreur est renvoyée au modèle


def _cfg(name: str, default=""):
    return ai._cfg(name, default)


def _read_timeout() -> int:
    return max(5, int(_cfg("AI_TIMEOUT", 30)))


def _check_deadline(deadline: Optional[float]) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise ChatFailure("deadline")


def _parse_arguments(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return {}, False
    try:
        data = json.loads(raw)
    except ValueError:
        return {}, True
    return (data, False) if isinstance(data, dict) else ({}, True)


def _sse_data(response) -> Iterator[Dict]:
    """Lignes `data: {...}` d'un flux SSE, au fur et à mesure de leur arrivée (`chunk_size=None`)."""
    for raw in response.iter_lines(chunk_size=None):
        if not raw:
            continue
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            return
        try:
            yield json.loads(payload)
        except ValueError:
            continue


# ------------------------------------------------------------------------------------------------ DeepSeek (API compatible OpenAI)

def to_openai_messages(system: str, messages: List[Dict]) -> List[Dict]:
    out: List[Dict] = [{"role": "system", "content": system}]
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": m.get("content") or None,
                        "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}}
                                       for c in m["tool_calls"]]})
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        else:
            out.append({"role": m["role"], "content": m.get("content", "")})
    return out


def _stream_deepseek(system: str, messages: List[Dict], tools: Optional[List[Dict]], max_tokens: int, deadline: Optional[float]) -> Iterator[Dict]:
    body = {"model": _cfg("AI_DEEPSEEK_MODEL"), "messages": to_openai_messages(system, messages), "stream": True,
            "stream_options": {"include_usage": True}, "temperature": 0.2, "max_tokens": max_tokens}
    if tools:
        body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}} for t in tools]
    url = f"{str(_cfg('AI_DEEPSEEK_URL')).rstrip('/')}/chat/completions"
    with requests.post(url, json=body, stream=True, timeout=(CONNECT_TIMEOUT, _read_timeout()),
                       headers={"Authorization": f"Bearer {_cfg('AI_DEEPSEEK_API_KEY')}", "Content-Type": "application/json"}) as response:
        if response.status_code >= 400:
            raise ChatFailure(f"http_{response.status_code}")
        slots: Dict[int, Dict] = {}
        for chunk in _sse_data(response):
            _check_deadline(deadline)
            usage = chunk.get("usage")
            if usage:
                yield {"type": "usage", "tokens_in": int(usage.get("prompt_tokens") or 0), "tokens_out": int(usage.get("completion_tokens") or 0)}
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    yield {"type": "delta", "text": delta["content"]}
                for tc in delta.get("tool_calls") or []:
                    slot = slots.setdefault(int(tc.get("index") or 0), {"id": "", "name": "", "args": ""})
                    slot["id"] = tc.get("id") or slot["id"]
                    function = tc.get("function") or {}
                    if function.get("name"):
                        slot["name"] = slot["name"] or function["name"]
                    slot["args"] += function.get("arguments") or ""
        if slots:
            calls = []
            for index in sorted(slots):
                slot = slots[index]
                args, invalid = _parse_arguments(slot["args"])
                calls.append(ToolCall(id=slot["id"] or f"call_{index}", name=slot["name"], arguments=args, invalid=invalid or not slot["name"]))
            yield {"type": "tool_calls", "calls": calls}


# ------------------------------------------------------------------------------------------------------------------------ Anthropic

def to_anthropic_messages(messages: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    results: List[Dict] = []

    def flush():
        if results:
            out.append({"role": "user", "content": list(results)})
            results.clear()

    for m in messages:
        if m["role"] == "tool":
            results.append({"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]})
            continue
        flush()
        if m["role"] == "assistant":
            blocks: List[Dict] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for c in m.get("tool_calls") or []:
                blocks.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments})
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "…"}]})
        else:
            out.append({"role": "user", "content": m.get("content", "")})
    flush()
    return out


def _stream_anthropic(system: str, messages: List[Dict], tools: Optional[List[Dict]], max_tokens: int, deadline: Optional[float]) -> Iterator[Dict]:
    body = {"model": _cfg("AI_ANTHROPIC_MODEL"), "max_tokens": max_tokens, "system": system, "messages": to_anthropic_messages(messages), "stream": True}
    if tools:
        body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
    with requests.post("https://api.anthropic.com/v1/messages", json=body, stream=True, timeout=(CONNECT_TIMEOUT, _read_timeout()),
                       headers={"x-api-key": _cfg("AI_ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01", "content-type": "application/json"}) as response:
        if response.status_code >= 400:
            raise ChatFailure(f"http_{response.status_code}")
        blocks: Dict[int, Dict] = {}
        tokens_in = tokens_out = 0
        for chunk in _sse_data(response):
            _check_deadline(deadline)
            kind = chunk.get("type")
            if kind == "message_start":
                tokens_in = int(((chunk.get("message") or {}).get("usage") or {}).get("input_tokens") or 0)
            elif kind == "content_block_start":
                block = chunk.get("content_block") or {}
                if block.get("type") == "tool_use":
                    blocks[int(chunk.get("index") or 0)] = {"id": block.get("id") or "", "name": block.get("name") or "", "json": ""}
            elif kind == "content_block_delta":
                delta = chunk.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield {"type": "delta", "text": delta["text"]}
                elif delta.get("type") == "input_json_delta":
                    slot = blocks.get(int(chunk.get("index") or 0))
                    if slot is not None:
                        slot["json"] += delta.get("partial_json") or ""
            elif kind == "message_delta":
                tokens_out = int((chunk.get("usage") or {}).get("output_tokens") or tokens_out)
            elif kind == "error":
                raise ChatFailure("provider_error")
            elif kind == "message_stop":
                break
        yield {"type": "usage", "tokens_in": tokens_in, "tokens_out": tokens_out}
        if blocks:
            calls = []
            for index in sorted(blocks):
                slot = blocks[index]
                args, invalid = _parse_arguments(slot["json"])
                calls.append(ToolCall(id=slot["id"] or f"tool_{index}", name=slot["name"], arguments=args, invalid=invalid or not slot["name"]))
            yield {"type": "tool_calls", "calls": calls}


_STREAMS = {"deepseek": _stream_deepseek, "anthropic": _stream_anthropic}


# ---------------------------------------------------------------------------------------------------------------------------- routeur

def available() -> bool:
    return any(ai.configured(p) for p in ai.provider_order())


def stream_chat(task: str, system: str, messages: List[Dict], tools: Optional[List[Dict]] = None, *, max_tokens: int = 1024,
                deadline: Optional[float] = None) -> Iterator[Dict]:
    """Premier fournisseur utilisable ; repli automatique tant qu'aucune sortie n'a été produite. Lève `ai.AIUnavailable` si aucun ne répond."""
    candidates = [p for p in ai.provider_order() if ai.configured(p)]
    if not candidates:
        raise ai.AIUnavailable("not_configured", "IA non configurée.")
    for name in candidates:
        if deadline is not None and time.monotonic() > deadline:
            break                                              # échéance dépassée : aucun nouveau fournisseur n'est sollicité
        started = time.monotonic()
        produced = False
        try:
            for event in _STREAMS[name](system, messages, tools, max_tokens, deadline):
                if event["type"] in ("delta", "tool_calls"):
                    produced = True
                yield event
            AIRun.objects.create(provider=name, task=task, ok=True, latency_ms=int((time.monotonic() - started) * 1000))
            yield {"type": "end", "provider": name}
            return
        except Exception as exc:  # noqa: BLE001 - un fournisseur en échec laisse la main au suivant ; rien du contenu n'est journalisé
            code = getattr(exc, "code", None) or type(exc).__name__
            logger.warning("Fournisseur d'IA %s en échec pendant le dialogue (%s)", name, code)
            AIRun.objects.create(provider=name, task=task, ok=False, error_code=str(code)[:40], latency_ms=int((time.monotonic() - started) * 1000))
            if produced:
                raise ChatInterrupted(str(code)[:40])
    raise ai.AIUnavailable("all_failed", "Les fournisseurs d'IA sont indisponibles pour le moment.")
