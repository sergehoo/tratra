import { ApiError, apiFetch } from "./api";
import { bo, MFA_EVENT, type Page } from "./bo";
import { parseSse, type StreamEvent } from "./assistantStream";

/** Client de Tratra AI (`/handy/backoffice/assistant/…`). Les clés des fournisseurs, les droits et les limites restent côté serveur. */
export interface AssistantStatus {
  enabled: boolean;
  configured: boolean;
  /** « IA non configurée. » quand aucune clé n'est définie sur le serveur (ou message d'interrupteur général). */
  message: string | null;
  providers: { name: string; configured: boolean }[];
  tools: { name: string; label: string }[];
  scopes: { accounts: boolean; security: boolean; bookings: boolean };
  limits: { questions_last_hour: number; questions_per_hour_limit: number; tokens_last_24h: number; tokens_daily_limit: number; max_input_chars: number };
  /** Durée de conservation de l'historique après la dernière activité. */
  retention_days: number;
}

export interface ConversationRow {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface AssistantSource {
  tool: string;
  label: string;
  ok: boolean;
}

export interface AssistantMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources: AssistantSource[];
  provider: string | null;
  created_at: string;
  error: { code: string; detail: string } | null;
}

export interface InsightAlert {
  key: string;
  severity: "info" | "warning" | "danger";
  title: string;
  count: number;
  explanation: string;
  examples: { label: string; link?: string }[];
  actions: { label: string; href: string; executed: boolean }[];
}

export interface Insight {
  scope: "accounts" | "security" | "bookings";
  generated_at: string;
  stats: Record<string, unknown>;
  alerts: InsightAlert[];
  omitted: string[];
  note: string;
}

export const assistantApi = {
  status: () => bo.get<AssistantStatus>("/assistant/status/"),
  conversations: (q = "") => bo.get<Page<ConversationRow>>(`/assistant/conversations/${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  createConversation: (clientId: string) => bo.post<ConversationRow>("/assistant/conversations/", { client_id: clientId }),
  conversation: (id: number) => bo.get<{ conversation: ConversationRow; has_more: boolean; results: AssistantMessage[] }>(`/assistant/conversations/${id}/`),
  rename: (id: number, title: string) => bo.patch<ConversationRow>(`/assistant/conversations/${id}/`, { title }),
  remove: (id: number) => bo.delete(`/assistant/conversations/${id}/`),
  insights: (scope: Insight["scope"]) => bo.get<Insight>(`/assistant/insights/?scope=${scope}`),
};

export function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
      });
}

/**
 * Envoie une question et transmet chaque événement du flux à `onEvent`. Résout à la fin du flux ; rejette avec `ApiError` si le serveur refuse
 * (droits, limites, IA non configurée…) et avec `TypeError`/`AbortError` si la connexion tombe ou est annulée.
 * Un rejeu (même `client_id`) après coupure ne repose jamais la question : le serveur renvoie la réponse déjà produite.
 */
export async function streamChat(body: { conversation: number; message: string; client_id: string }, onEvent: (e: StreamEvent) => void, signal?: AbortSignal): Promise<void> {
  const res = await apiFetch("/backoffice/assistant/chat/", { method: "POST", body: JSON.stringify(body), headers: { Accept: "text/event-stream" }, signal });
  const type = res.headers.get("content-type") ?? "";
  if (!res.ok || !type.includes("text/event-stream")) {
    let data: unknown = null;
    try {
      data = await res.json();
    } catch {
      /* corps non JSON */
    }
    if (res.ok) {
      const dup = data as { duplicate?: boolean; message?: AssistantMessage } | null;
      if (dup?.duplicate && dup.message) {
        onEvent({ type: "delta", text: dup.message.content });
        onEvent({ type: "done", message: dup.message.id, content: dup.message.content, sources: dup.message.sources, provider: dup.message.provider ?? "", usage: { tokens_in: 0, tokens_out: 0 } });
        return;
      }
    }
    const code = (data as { code?: unknown } | null)?.code;
    if (res.status === 403 && (code === "mfa_required" || code === "mfa_enrollment_required") && typeof window !== "undefined") window.dispatchEvent(new Event(MFA_EVENT));
    throw new ApiError(res.status, data);
  }
  const reader = res.body?.getReader();
  if (!reader) throw new TypeError("flux indisponible");
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSse(buffer);
    buffer = parsed.rest;
    parsed.events.forEach(onEvent);
  }
  buffer += decoder.decode();
  parseSse(buffer + "\n\n").events.forEach(onEvent);
}

/** Rédaction assistée d'un message : renvoie une PROPOSITION ; l'envoi reste une action humaine distincte. */
export interface DraftResult {
  draft: string;
  notes: string;
  mode: string;
  provider: string | null;
  sent: false;
  note: string;
}
export type DraftMode = "compose" | "rewrite" | "correct" | "professional" | "shorten";

export const draftApi = {
  create: (body: { mode: DraftMode; text?: string; instruction?: string; purpose?: string; thread?: number }) => bo.post<DraftResult>("/messages/ai-draft/", body),
};
