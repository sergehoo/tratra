"""Tour de conversation de Tratra AI : question → (outils en lecture seule)* → réponse, diffusée événement par événement.

Événements produits (dictionnaires) :
  meta {conversation, message} · status {tool, label} · delta {text} · done {message, content, sources, provider, usage} · error {code, detail}

Garanties : au plus MAX_STEPS tours de modèle et MAX_TOOL_CALLS appels d'outils ; échéance globale ; un outil non autorisé ou inventé est refusé ;
la réponse (même partielle) et l'audit sont toujours enregistrés, y compris si le navigateur ferme la connexion ; l'audit ne contient jamais le texte."""
import logging
import threading
import time
from typing import Dict, Iterator, List, Optional

from django.utils import timezone

from backoffice import rbac
from backoffice.assistant import limits, prompts, safety
from backoffice.assistant import tools as tools_mod
from backoffice.models import AssistantConversation, AssistantMessage
from intelligence import ai, chat
from trust.models import audit

logger = logging.getLogger(__name__)

MAX_STEPS = 4
MAX_TOOL_CALLS = 6

ERRORS = {
    "not_configured": "IA non configurée.",
    "all_failed": "Les fournisseurs d'IA sont indisponibles pour le moment. Réessayez dans quelques instants.",
    "external_not_allowed": "L'envoi vers un fournisseur d'IA externe n'est pas autorisé.",
    "interrupted": "La réponse a été interrompue par le fournisseur d'IA ; ce qui a été reçu est conservé.",
    "deadline": "La réponse a pris trop de temps ; ce qui a été reçu est conservé. Reformulez avec une demande plus précise.",
    "empty": "Le fournisseur d'IA n'a renvoyé aucune réponse. Réessayez.",
    "client_disconnected": "Connexion fermée avant la fin de la réponse.",
    "internal": "La réponse a été interrompue.",
}


class _Stopped(Exception):
    pass


def history(conversation: AssistantConversation, before_id: int) -> List[Dict]:
    """Derniers échanges RÉUSSIS avant la question courante (les tours en erreur et les contenus vides ne sont jamais rejoués)."""
    rows = list(conversation.messages.filter(pk__lt=before_id, role__in=("user", "assistant")).exclude(content="").filter(error_code="")
                .order_by("-id")[: limits.HISTORY_MESSAGES])
    rows.reverse()
    while rows and rows[0].role != "user":
        rows.pop(0)
    return [{"role": m.role, "content": m.content[: limits.HISTORY_CHARS]} for m in rows]


def run(owner, conversation: AssistantConversation, question: AssistantMessage, *, stop: Optional[threading.Event] = None) -> Iterator[Dict]:
    perms = rbac.user_permissions(owner)
    allowed = tools_mod.allowed(perms)
    tool_defs = [t.schema() for t in allowed]
    roles = rbac.user_roles(owner)
    messages: List[Dict] = history(conversation, question.pk) + [{"role": "user", "content": question.content}]
    deadline = time.monotonic() + limits.deadline_seconds()
    parts: List[str] = []
    sources: List[Dict] = []
    provider = ""
    tokens_in = tokens_out = calls_done = length = 0
    error = ""
    yield {"type": "meta", "conversation": conversation.pk, "message": question.pk}
    try:
        for step in range(MAX_STEPS + 1):
            last = step == MAX_STEPS or calls_done >= MAX_TOOL_CALLS
            system = prompts.system_prompt(roles, allowed, last_step=last)
            step_text: List[str] = []
            calls: List[chat.ToolCall] = []
            gap = bool(parts)
            for event in chat.stream_chat("assistant_chat", system, messages, None if last else tool_defs, max_tokens=limits.max_tokens(), deadline=deadline):
                if stop is not None and stop.is_set():
                    raise _Stopped()
                kind = event["type"]
                if kind == "delta":
                    text = event["text"]
                    if gap:
                        text, gap = "\n\n" + text.lstrip(), False
                    if length >= limits.ANSWER_MAX_CHARS:
                        continue                                       # réponse plafonnée : le reste est ignoré
                    text = text[: limits.ANSWER_MAX_CHARS - length]
                    length += len(text)
                    parts.append(text)
                    step_text.append(text)
                    yield {"type": "delta", "text": text}
                elif kind == "tool_calls":
                    calls = event["calls"]
                elif kind == "usage":
                    tokens_in += event["tokens_in"]
                    tokens_out += event["tokens_out"]
                elif kind == "end":
                    provider = event["provider"]
            if not calls or last:
                break
            messages.append({"role": "assistant", "content": "".join(step_text), "tool_calls": calls})
            for call in calls:
                if calls_done >= MAX_TOOL_CALLS:
                    messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name,
                                     "content": safety.wrap_tool_result(call.name, '{"erreur":"Limite d\'outils atteinte pour ce tour."}')})
                    continue
                calls_done += 1
                yield {"type": "status", "tool": call.name, "label": tools_mod.label_of(call.name)}
                result = tools_mod.execute(owner, call.name, call.arguments, invalid=call.invalid)
                audit("backoffice.assistant.tool", actor=owner, target_type="assistantconversation", target_id=conversation.pk,
                      tool=call.name, ok=result.ok, denied=result.denied, args=result.args or {})
                tool = tools_mod.REGISTRY.get(call.name)
                sources.append({"tool": call.name, "label": (tool.label.rstrip("…").strip() if tool else call.name), "ok": result.ok})
                messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": result.content})
        if not parts:
            error = "empty"
    except ai.AIUnavailable as exc:
        error = exc.code
    except chat.ChatInterrupted as exc:
        error = "deadline" if "deadline" in exc.code else "interrupted"
    except _Stopped:
        error = "client_disconnected"
    except Exception:  # noqa: BLE001
        logger.exception("Tour de l'assistant en échec")
        error = "internal"
    finally:
        answer = "".join(parts).strip()
        saved = AssistantMessage.objects.create(conversation=conversation, role=AssistantMessage.ASSISTANT, content=answer, sources=sources, provider=provider,
                                                tokens_in=tokens_in, tokens_out=tokens_out, error_code=error[:40])
        AssistantConversation.objects.filter(pk=conversation.pk).update(updated_at=timezone.now())
        audit("backoffice.assistant.answer", actor=owner, target_type="assistantconversation", target_id=conversation.pk, provider=provider,
              tools=[s["tool"] for s in sources], tokens_in=tokens_in, tokens_out=tokens_out, error=error, characters=len(answer))
    if error:
        yield {"type": "error", "code": error, "detail": ERRORS.get(error, ERRORS["internal"]), "message": saved.pk}
    else:
        yield {"type": "done", "message": saved.pk, "content": answer, "sources": sources, "provider": provider,
               "usage": {"tokens_in": tokens_in, "tokens_out": tokens_out}}
