"""Back-Office — Tratra AI : statut, conversations privées de chaque administrateur, dialogue (SSE ou JSON), synthèses de gestion, rédaction assistée.

 - droit `assistant.use` ; chaque OUTIL exige en plus son propre droit (backoffice.assistant.tools), vérifié à l'exécution ;
 - une conversation n'est visible que de son propriétaire (404 pour tout autre compte, super-administrateur compris) ;
 - aucun fournisseur n'est appelé sans clé (« IA non configurée »), ni au-delà des limites d'heure, de jour et de jetons ;
 - l'IA ne fait que proposer : jamais d'envoi, de suspension, de suppression ni de validation ;
 - l'audit conserve qui a posé une question, quels outils ont servi et combien de jetons ont été consommés — jamais le texte."""
import uuid

from django.db import IntegrityError
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.response import Response

from backoffice import rbac
from backoffice.assistant import agent, insights, limits, prompts, retention, safety, stream
from backoffice.assistant import tools as tools_mod
from backoffice.common import BOView, audit_op, bad_request, paginate
from backoffice.models import AssistantConversation, AssistantMessage
from intelligence import ai, chat

DEFAULT_TITLE = "Nouvelle conversation"
NOT_CONFIGURED = "IA non configurée."
ERROR_STATUS = {"not_configured": 503, "external_not_allowed": 503, "all_failed": 502, "deadline": 504, "interrupted": 502, "empty": 502}


class AnyAcceptNegotiation(DefaultContentNegotiation):
    """Le flux SSE (`text/event-stream`) n'a pas de moteur de rendu DRF : on n'écarte pas la requête sur son en-tête Accept."""

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type


def _configured() -> bool:
    return limits.enabled() and chat.available()


def _own(request, pk):
    try:
        return AssistantConversation.objects.filter(pk=int(pk), owner=request.user, deleted_at__isnull=True).first()
    except (TypeError, ValueError):
        return None


def _message_row(m: AssistantMessage) -> dict:
    return {"id": m.pk, "role": m.role, "content": m.content, "sources": m.sources, "provider": m.provider or None, "created_at": m.created_at,
            "error": {"code": m.error_code, "detail": agent.ERRORS.get(m.error_code, agent.ERRORS["internal"])} if m.error_code else None}


def _conversation_row(c: AssistantConversation) -> dict:
    return {"id": c.pk, "title": c.title, "created_at": c.created_at, "updated_at": c.updated_at}


def _uuid_or_none(raw):
    try:
        return uuid.UUID(str(raw)) if raw else None
    except ValueError:
        return None


class AssistantStatus(BOView):
    """État de l'assistant pour l'interface : jamais une clé ni un nom de modèle ; outils disponibles pour CE compte ; consommation du jour."""
    bo_permission = "assistant.use"

    def get(self, request):
        perms = rbac.user_permissions(request.user)
        ok = _configured()
        return Response({
            "enabled": limits.enabled(), "configured": ok,
            "message": None if ok else ("Assistant désactivé par l'exploitant." if not limits.enabled() else NOT_CONFIGURED),
            "providers": [{"name": p["name"], "configured": p["configured"]} for p in ai.status()["providers"]],
            "tools": [{"name": t.name, "label": t.label.rstrip("…").strip()} for t in tools_mod.allowed(perms)],
            "scopes": {scope: perm in perms for scope, perm in insights.SCOPES.items()},
            "limits": {**limits.usage_today(request.user), "max_input_chars": limits.INPUT_MAX},
            "retention_days": retention.retention_days(),
        })


class ConversationList(BOView):
    bo_permission = "assistant.use"

    def get(self, request):
        qs = AssistantConversation.objects.filter(owner=request.user, deleted_at__isnull=True)
        q = (request.query_params.get("q") or "").strip()[:60]
        if q:
            qs = qs.filter(title__icontains=q)
        return paginate(request, qs.order_by("-updated_at", "-id"), _conversation_row, page_size=30)

    def post(self, request):
        client_id = _uuid_or_none(request.data.get("client_id"))
        if request.data.get("client_id") and client_id is None:
            return bad_request("invalid_client_id", "Identifiant invalide.")
        if client_id:
            existing = AssistantConversation.objects.filter(owner=request.user, client_id=client_id, deleted_at__isnull=True).first()
            if existing:
                return Response(_conversation_row(existing), status=200)
        try:
            conv = AssistantConversation.objects.create(owner=request.user, client_id=client_id)
        except IntegrityError:                                       # course : l'autre requête a gagné
            conv = AssistantConversation.objects.get(owner=request.user, client_id=client_id)
            return Response(_conversation_row(conv), status=200)
        return Response(_conversation_row(conv), status=201)


class ConversationDetail(BOView):
    bo_permission = "assistant.use"

    def get(self, request, pk):
        conv = _own(request, pk)
        if conv is None:
            return bad_request("not_found", "Conversation introuvable.", 404)
        try:
            before = int(request.query_params["before"]) if request.query_params.get("before") else None
        except ValueError:
            before = None
        qs = conv.messages.order_by("-id")
        if before:
            qs = qs.filter(pk__lt=before)
        rows = list(qs[:41])
        more = len(rows) > 40
        rows = list(reversed(rows[:40]))
        return Response({"conversation": _conversation_row(conv), "has_more": more, "next_before": rows[0].pk if (rows and more) else None,
                         "results": [_message_row(m) for m in rows]})

    def patch(self, request, pk):
        conv = _own(request, pk)
        if conv is None:
            return bad_request("not_found", "Conversation introuvable.", 404)
        title = " ".join(str(request.data.get("title") or "").split())[:80]
        if not title:
            return bad_request("invalid_title", "Le titre est vide.")
        conv.title = title
        conv.save(update_fields=["title"])
        return Response(_conversation_row(conv))

    def delete(self, request, pk):
        conv = _own(request, pk)
        if conv is None:
            return bad_request("not_found", "Conversation introuvable.", 404)
        conv.deleted_at = timezone.now()
        conv.save(update_fields=["deleted_at"])
        audit_op(request, "assistant.conversation_deleted", conv)
        return Response(status=204)


class AssistantChat(BOView):
    """POST {conversation, message, client_id?, stream?=true} → flux SSE (meta, status, delta, done|error) ou, avec stream=false, une réponse JSON."""
    bo_permission = "assistant.use"
    content_negotiation_class = AnyAcceptNegotiation

    def post(self, request):
        if not limits.enabled():
            return bad_request("assistant_disabled", "Assistant désactivé par l'exploitant.", 503)
        data = request.data
        conv = _own(request, data.get("conversation"))
        if conv is None:
            return bad_request("not_found", "Conversation introuvable.", 404)
        text = str(data.get("message") or "").replace("\x00", "").strip()
        if not text:
            return bad_request("empty", "La question est vide.")
        if len(text) > limits.INPUT_MAX:
            return bad_request("too_long", f"Question trop longue : {limits.INPUT_MAX} caractères au maximum.")
        client_id = _uuid_or_none(data.get("client_id"))
        if data.get("client_id") and client_id is None:
            return bad_request("invalid_client_id", "Identifiant invalide.")
        if client_id:                                                # rejeu (double clic, coupure réseau) : jamais une deuxième question
            previous = AssistantMessage.objects.filter(conversation=conv, client_id=client_id).first()
            if previous is not None:
                reply = conv.messages.filter(pk__gt=previous.pk, role=AssistantMessage.ASSISTANT).order_by("pk").first()
                if reply is None:
                    return bad_request("in_progress", "Cette question est déjà en cours de traitement.", 409)
                return Response({"duplicate": True, "message": _message_row(reply)})
        if not _configured():
            return bad_request("ai_not_configured", NOT_CONFIGURED, 503)
        try:
            limits.check_chat(request.user)
        except limits.LimitError as exc:
            return bad_request(exc.code, exc.detail, exc.status)
        if not limits.acquire(request.user):
            return bad_request("busy", "Une réponse est déjà en cours. Attendez sa fin.", 429)
        clean, redacted = safety.redact_secrets(text)               # un secret collé par erreur n'est ni transmis ni conservé
        try:
            question = AssistantMessage.objects.create(conversation=conv, role=AssistantMessage.USER, content=clean, client_id=client_id)
        except IntegrityError:
            limits.release(request.user)
            return bad_request("in_progress", "Cette question est déjà en cours de traitement.", 409)
        if conv.title == DEFAULT_TITLE:
            conv.title = " ".join(clean.split())[:60] or DEFAULT_TITLE
            conv.save(update_fields=["title"])
        want_stream = data.get("stream", True) not in (False, "false", "0", 0)
        audit_op(request, "assistant.question", conv, characters=len(clean), secrets_redacted=redacted, stream=want_stream)
        owner = request.user

        def release():
            limits.release(owner)

        if not want_stream:
            try:
                events = list(agent.run(owner, conv, question))
            finally:
                release()
            final = events[-1]
            if final["type"] == "error":
                return Response({"code": final["code"], "detail": final["detail"]}, status=ERROR_STATUS.get(final["code"], 502))
            reply = AssistantMessage.objects.get(pk=final["message"])
            return Response({"message": _message_row(reply), "usage": final["usage"], "secrets_redacted": redacted})

        if hasattr(request._request, "scope"):                      # ASGI : diffusion réelle via un fil de travail
            body = stream.async_stream(lambda stop: agent.run(owner, conv, question, stop=stop), on_close=release)
        else:                                                       # WSGI : générateur synchrone
            def sync_body():
                try:
                    yield from stream.sync_stream(agent.run(owner, conv, question))
                finally:
                    release()
            body = sync_body()
        response = StreamingHttpResponse(body, content_type="text/event-stream; charset=utf-8")
        response["Cache-Control"] = "no-cache, no-store, no-transform"
        response["X-Accel-Buffering"] = "no"
        response["X-Redacted-Secrets"] = str(redacted)
        return response


class AssistantInsights(BOView):
    """Synthèses de gestion explicables (règles sur données réelles) : comptes, sécurité, réservations. Lecture seule ; aucune action exécutée."""
    bo_permission = "assistant.use"

    def get(self, request):
        scope = request.query_params.get("scope")
        if scope not in insights.SCOPES:
            return bad_request("invalid_scope", "Synthèse inconnue.")
        perms = rbac.user_permissions(request.user)
        if insights.SCOPES[scope] not in perms:
            return bad_request("forbidden", "Droits insuffisants pour cette synthèse.", 403)
        audit_op(request, "assistant.insights", scope=scope)
        with safety.read_only():
            return Response(insights.HANDLERS[scope](perms))


DRAFT_MAX_CONTEXT = 3
DRAFT_MAX_TEXT = 2000


def _context_block(thread_id):
    """Derniers messages du fil, coordonnées masquées, présentés comme DONNÉES (jamais comme consignes)."""
    from handy.models import Conversation

    conv = Conversation.objects.filter(pk=thread_id, kind=Conversation.SUPPORT).first() if thread_id else None
    if conv is None:
        return ""
    rows = list(conv.messages.order_by("-id")[:DRAFT_MAX_CONTEXT])
    rows.reverse()
    lines = [f"{'Équipe' if m.via_staff else 'Membre'} : {safety.mask_text(safety.redact_secrets((m.content or '')[:500])[0])}" for m in rows if m.content]
    return "\n".join(lines)


class MessageDraft(BOView):
    """Rédaction assistée d'un message (nouveau message ou réponse) : PROPOSE un texte, ne l'envoie jamais. L'envoi reste une action humaine
    distincte (aperçu puis confirmation côté Messagerie)."""
    bo_permission = "messages.send"
    MODES = prompts.DRAFT_MODES

    def post(self, request):
        user = request.user
        if not rbac.has_permission(user, "assistant.use") or not limits.enabled():
            return bad_request("forbidden", "Droits insuffisants pour la rédaction assistée.", 403)
        data = request.data
        mode = data.get("mode") or "compose"
        if mode not in self.MODES:
            return bad_request("invalid_mode", "Mode de rédaction inconnu.")
        purpose = data.get("purpose") if data.get("purpose") in ("service", "promotion") else "service"
        text = safety.redact_secrets(str(data.get("text") or "").strip())[0]
        instruction = safety.redact_secrets(str(data.get("instruction") or "").strip())[0]
        if len(text) > DRAFT_MAX_TEXT or len(instruction) > 500:
            return bad_request("too_long", "Texte ou consigne trop long.")
        if mode == "compose" and not instruction and not text:
            return bad_request("empty", "Décrivez ce que le message doit dire.")
        if mode != "compose" and not text:
            return bad_request("empty", "Il n'y a pas de texte à retravailler.")
        if not _configured():
            return bad_request("ai_not_configured", NOT_CONFIGURED, 503)
        try:
            limits.check_draft(user)
        except limits.LimitError as exc:
            return bad_request(exc.code, exc.detail, exc.status)
        context = _context_block(data.get("thread"))
        prompt = [f"Tâche : {self.MODES[mode]}", f"Nature du message : {'promotionnel (le membre a consenti à recevoir des offres)' if purpose == 'promotion' else 'information de service'}."]
        if instruction:
            prompt.append(f"Consigne de l'administrateur : {instruction}")
        if text:
            prompt.append(f"<texte>\n{text}\n</texte>")
        if context:
            prompt.append(f"Contexte (derniers messages du fil, coordonnées masquées) :\n<message_membre>\n{context}\n</message_membre>")
        try:
            result = ai.complete("message_draft", prompts.DRAFT_SYSTEM, "\n\n".join(prompt), sensitive=False, json_mode=True)
        except ai.AIUnavailable as exc:
            audit_op(request, "assistant.draft", mode=mode, ok=False, error=exc.code)
            status = 503 if exc.code in ("not_configured", "external_not_allowed") else 502
            return bad_request("ai_not_configured" if exc.code == "not_configured" else exc.code, NOT_CONFIGURED if exc.code == "not_configured" else exc.detail, status)
        except Exception:  # noqa: BLE001 - réponse du fournisseur illisible
            audit_op(request, "assistant.draft", mode=mode, ok=False, error="unreadable")
            return bad_request("unreadable", "La proposition n'a pas pu être lue. Réessayez.", 502)
        draft = str((result.get("data") or {}).get("draft") or "").strip()
        notes = str((result.get("data") or {}).get("notes") or "").strip()[:300]
        if not draft:
            audit_op(request, "assistant.draft", mode=mode, ok=False, error="empty")
            return bad_request("empty", "Le fournisseur d'IA n'a rien proposé. Réessayez.", 502)
        draft = safety.redact_secrets(draft[:DRAFT_MAX_TEXT])[0]
        audit_op(request, "assistant.draft", mode=mode, ok=True, provider=result.get("provider"), input_characters=len(text), characters=len(draft), contextual=bool(context))
        return Response({"draft": draft, "notes": notes, "mode": mode, "provider": result.get("provider"), "sent": False,
                         "note": "Proposition à relire et modifier : elle n'est envoyée qu'après votre confirmation."})
