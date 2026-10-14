"use client";
/**
 * Temps réel de la messagerie et des statuts : UNE WebSocket par session (`/ws/inbox/`), billet signé de 60 s.
 * Le WebSocket n'est qu'un confort : toutes les écritures passent par l'API REST ; à chaque (re)connexion ou lorsque la
 * connexion est coupée, les pages rechargent leurs données par l'API (évènement `resync`) et un sondage prend le relais.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { get, post } from "./api";
import { useAuth } from "./auth";
import { liveSocketUrl } from "./live";

export type InboxStatus = "connecting" | "live" | "offline";

export interface ChatMessage {
  id: number;
  conversation: number;
  mine: boolean;
  content: string;
  kind: "text" | "image" | "video" | "file";
  created_at: string;
  is_read: boolean;
  state: "sent" | "delivered" | "read";
  client_id: string | null;
  sender: string;
  via_staff: boolean;
  attachment: { url: string | null; kind: string; mime: string; size: number; name: string; width?: number; height?: number; duration?: number } | null;
  context: { status?: number; kind?: string; text?: string } | null;
}

export interface Conversation {
  id: number;
  kind: "booking" | "direct" | "support";
  booking_id: number | null;
  counterpart: string;
  counterpart_id: number | null;
  last_message: string | null;
  last_at: string;
  unread: number;
  blocked: boolean;
  can_send: boolean;
}

export type InboxEvent =
  | { type: "message"; message: ChatMessage; conversation: Conversation; unread_total: number }
  | { type: "read"; conversation: number; reader: number; upto: number; count: number; at: string }
  | { type: "read_self"; conversation: number; count: number; unread_total: number }
  | { type: "delivered"; ids: number[]; at: string }
  | { type: "status"; action: "new" | "deleted"; author: number; status: number }
  | { type: "status_view"; status: number; views: { unique: number; total: number } }
  | { type: "resync" };

type Listener = (e: InboxEvent) => void;
interface InboxValue {
  status: InboxStatus;
  unread: number;
  subscribe: (fn: Listener) => () => void;
  refreshUnread: () => Promise<void>;
}

const Ctx = createContext<InboxValue | null>(null);
const POLL_MS = 15000;

export function InboxProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [status, setStatus] = useState<InboxStatus>("connecting");
  const [unread, setUnread] = useState(0);
  const listeners = useRef(new Set<Listener>());
  const emit = useCallback((e: InboxEvent) => listeners.current.forEach((fn) => fn(e)), []);

  const refreshUnread = useCallback(async () => {
    try {
      setUnread((await get<{ total: number }>("/me/messages/unread/")).total);
    } catch {
      /* le compteur se met à jour à la prochaine occasion */
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let backoff = 1000;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let ping: ReturnType<typeof setInterval> | undefined;
    let pong = 0;
    let poll: ReturnType<typeof setInterval> | undefined;

    const stopPoll = () => poll && clearInterval(poll);
    const startPoll = () => {
      stopPoll();
      poll = setInterval(() => {
        void refreshUnread();
        emit({ type: "resync" });
      }, POLL_MS);
    };

    async function connect() {
      if (closed) return;
      setStatus((s) => (s === "live" ? s : "connecting"));
      try {
        const { ticket } = await post<{ ticket: string }>("/me/realtime/ticket/");
        if (closed) return;
        ws = new WebSocket(liveSocketUrl("/ws/inbox/", ticket));
      } catch {
        return fail();
      }
      ws.onopen = () => {
        backoff = 1000;
        stopPoll();
        setStatus("live");
        pong = Date.now();
        ping = setInterval(() => {
          if (!ws || ws.readyState !== WebSocket.OPEN) return;
          if (Date.now() - pong > 70000) return ws.close(); // aucune réponse : connexion fantôme, on la rétablit
          ws.send(JSON.stringify({ type: "ping" }));
        }, 25000);
        void refreshUnread();
        emit({ type: "resync" });                              // rattrapage de ce qui a pu arriver pendant la coupure
      };
      ws.onmessage = (ev) => {
        pong = Date.now();
        let data: { type?: string; unread_total?: number } & Record<string, unknown>;
        try {
          data = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (data.type === "ready" && typeof data.unread_total === "number") setUnread(data.unread_total);
        else if (data.type === "message") {
          if (typeof data.unread_total === "number") setUnread(data.unread_total);
          const m = data.message as ChatMessage;
          if (!m.mine && ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ack", ids: [m.id] })); // accusé : « distribué »
          emit(data as unknown as InboxEvent);
        } else if (data.type === "read") {
          void refreshUnread();
          emit(data as unknown as InboxEvent);
        } else if (data.type === "read_self") {
          // Lu sur un autre appareil : seul le compteur est synchronisé (les messages du lecteur ne changent pas d'état).
          if (typeof data.unread_total === "number") setUnread(data.unread_total);
          emit({ type: "resync" });
        } else if (data.type === "delivered" || data.type === "status" || data.type === "status_view") emit(data as unknown as InboxEvent);
      };
      ws.onclose = () => {
        ping && clearInterval(ping);
        fail();
      };
      ws.onerror = () => ws?.close();
    }

    function fail() {
      if (closed) return;
      setStatus("offline");
      startPoll();                                             // repli : l'API REST reste la source de vérité
      retry = setTimeout(() => void connect(), backoff);
      backoff = Math.min(backoff * 2, 30000);
    }

    const onVisible = () => {
      if (document.visibilityState === "visible") {
        void refreshUnread();
        emit({ type: "resync" });
        if (!ws || ws.readyState > WebSocket.OPEN) {
          clearTimeout(retry);
          void connect();
        }
      }
    };
    const onOnline = () => {
      clearTimeout(retry);
      backoff = 1000;
      void connect();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onOnline);
    void refreshUnread();
    void connect();
    return () => {
      closed = true;
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
      clearTimeout(retry);
      ping && clearInterval(ping);
      stopPoll();
      ws?.close();
    };
  }, [user, emit, refreshUnread]);

  const value = useMemo<InboxValue>(
    () => ({
      status,
      unread,
      refreshUnread,
      subscribe: (fn) => {
        listeners.current.add(fn);
        return () => listeners.current.delete(fn);
      },
    }),
    [status, unread, refreshUnread],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useInbox(): InboxValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useInbox doit être utilisé sous <InboxProvider>.");
  return v;
}

/** Abonnement à un type d'évènements temps réel pendant la vie du composant. */
export function useInboxEvents(handler: Listener) {
  const { subscribe } = useInbox();
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => subscribe((e) => ref.current(e)), [subscribe]);
}
