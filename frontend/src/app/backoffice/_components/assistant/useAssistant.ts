"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { assistantApi, newId, streamChat, type AssistantMessage, type AssistantSource, type AssistantStatus, type ConversationRow } from "@/lib/assistant";
import { boError } from "@/lib/bo";
import type { StreamEvent } from "@/lib/assistantStream";

const STORE = "tratra.bo.ai";

export interface UiMessage {
  id: number | string;
  role: "user" | "assistant";
  content: string;
  sources: AssistantSource[];
  error: { code: string; detail: string } | null;
  /** Réponse en cours de diffusion. */
  streaming?: boolean;
  /** Outil en cours de consultation (« Consultation des réservations… »). */
  statusLabel?: string;
  /** Question envoyée : sert à rejouer SANS la poser deux fois (le serveur reconnaît le même identifiant). */
  clientId?: string;
  /** Coupure réseau : la réponse peut être redemandée. */
  failed?: boolean;
  /** Arrêtée par l'administrateur. */
  stopped?: boolean;
}

interface Saved {
  open: boolean;
  conversation: number | null;
}

export function loadSaved(): Saved {
  try {
    const raw = JSON.parse(window.localStorage.getItem(STORE) ?? "{}") as Partial<Saved>;
    return { open: raw.open === true, conversation: typeof raw.conversation === "number" ? raw.conversation : null };
  } catch {
    return { open: false, conversation: null };
  }
}

export function persist(state: Saved) {
  try {
    window.localStorage.setItem(STORE, JSON.stringify(state));
  } catch {
    /* stockage indisponible (navigation privée) : l'état n'est simplement pas gardé */
  }
}

function fromServer(m: AssistantMessage): UiMessage {
  return { id: m.id, role: m.role, content: m.content, sources: m.sources ?? [], error: m.error };
}

const SERVER_TEXT: Record<string, string> = {
  ai_not_configured: "IA non configurée.",
  assistant_disabled: "Assistant désactivé par l’exploitant.",
  busy: "Une réponse est déjà en cours. Attendez sa fin.",
  in_progress: "Cette question est encore en cours de traitement. Réessayez dans un instant.",
};

/** Conversation avec Tratra AI : état, diffusion de la réponse (SSE), arrêt, nouvelle conversation, reprise après coupure. */
export function useAssistant(active: boolean) {
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [statusError, setStatusError] = useState("");
  const [convId, setConvId] = useState<number | null>(null);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [historyVersion, setHistoryVersion] = useState(0);
  const abort = useRef<AbortController | null>(null);
  const draftConversation = useRef(newId());

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await assistantApi.status());
      setStatusError("");
    } catch (e) {
      setStatusError(boError(e, "L’état de l’assistant n’a pas pu être chargé."));
    }
  }, []);

  const openConversation = useCallback(async (id: number) => {
    abort.current?.abort();
    setNotice("");
    try {
      const r = await assistantApi.conversation(id);
      setConvId(id);
      setMessages(r.results.map(fromServer));
      persist({ open: true, conversation: id });
    } catch (e) {
      setConvId(null);
      setMessages([]);
      persist({ open: true, conversation: null });
      if (!(e instanceof ApiError && e.status === 404)) setNotice(boError(e, "La conversation n’a pas pu être ouverte."));
    }
  }, []);

  // Chargement initial (une fois le panneau utilisé) : état du service puis conversation précédente.
  useEffect(() => {
    if (!active) return;
    void loadStatus();
    const saved = loadSaved();
    if (saved.conversation) void openConversation(saved.conversation);
  }, [active, loadStatus, openConversation]);

  const newConversation = useCallback(() => {
    abort.current?.abort();
    setConvId(null);
    setMessages([]);
    setNotice("");
    draftConversation.current = newId();
    persist({ open: true, conversation: null });
  }, []);

  const patch = useCallback((id: number | string, change: (m: UiMessage) => UiMessage) => {
    setMessages((list) => list.map((m) => (m.id === id ? change(m) : m)));
  }, []);

  const send = useCallback(
    async (text: string, retryClientId?: string) => {
      const content = text.trim();
      if (!content || busy) return;
      setNotice("");
      setBusy(true);
      const clientId = retryClientId ?? newId();
      const botId = `a-${clientId}`;
      let id = convId;
      try {
        if (id == null) {
          id = (await assistantApi.createConversation(draftConversation.current)).id;
          setConvId(id);
          persist({ open: true, conversation: id });
        }
      } catch (e) {
        setBusy(false);
        setNotice(boError(e, "La conversation n’a pas pu être créée."));
        return;
      }
      const bot: UiMessage = { id: botId, role: "assistant", content: "", sources: [], error: null, streaming: true, clientId };
      setMessages((list) =>
        retryClientId
          ? list.map((m) => (m.id === botId ? bot : m))
          : [...list, { id: `u-${clientId}`, role: "user", content, sources: [], error: null, clientId }, bot],
      );
      const controller = new AbortController();
      abort.current = controller;
      let current: number | string = botId;
      const onEvent = (ev: StreamEvent) => {
        if (ev.type === "status") patch(current, (m) => ({ ...m, statusLabel: ev.label }));
        else if (ev.type === "delta") patch(current, (m) => ({ ...m, content: m.content + ev.text, statusLabel: undefined }));
        else if (ev.type === "done") {
          patch(current, (m) => ({ ...m, id: ev.message, content: ev.content, sources: ev.sources, streaming: false, statusLabel: undefined, failed: false }));
          current = ev.message;
        } else if (ev.type === "error") {
          patch(current, (m) => ({ ...m, streaming: false, statusLabel: undefined, error: { code: ev.code, detail: ev.detail } }));
        }
      };
      try {
        await streamChat({ conversation: id, message: content, client_id: clientId }, onEvent, controller.signal);
        patch(current, (m) => (m.streaming ? { ...m, streaming: false, statusLabel: undefined, failed: true } : m));   // flux fermé sans conclusion
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") {
          patch(current, (m) => ({ ...m, streaming: false, statusLabel: undefined, stopped: true }));
        } else if (e instanceof ApiError) {
          const data = e.data as { code?: string; detail?: string } | null;
          const text = (data?.code && SERVER_TEXT[data.code]) || data?.detail || boError(e, "La question n’a pas pu être envoyée.");
          setMessages((list) => list.filter((m) => m.id !== botId && m.id !== `u-${clientId}`));       // refusée : rien n'a été posé au modèle
          setNotice(text);
        } else {
          patch(current, (m) => ({ ...m, streaming: false, statusLabel: undefined, failed: true }));
        }
      } finally {
        abort.current = null;
        setBusy(false);
        setHistoryVersion((v) => v + 1);
        void loadStatus();
      }
    },
    [busy, convId, loadStatus, patch],
  );

  const stop = useCallback(() => abort.current?.abort(), []);

  useEffect(() => () => abort.current?.abort(), []);

  return { status, statusError, convId, messages, busy, notice, setNotice, send, stop, newConversation, openConversation, historyVersion, reloadStatus: loadStatus };
}

export type { ConversationRow };
