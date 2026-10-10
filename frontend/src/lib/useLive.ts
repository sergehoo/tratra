"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, get, post } from "./api";
import { liveSocketUrl, type LiveState } from "./live";

const POLL_MS = 5000;       // repli sans WebSocket : lecture périodique de GET /live/
const HEARTBEAT_MS = 20000; // avec WebSocket : simple filet de sécurité
const OPEN_PHASES = new Set(["confirmed", "en_route", "arrived", "in_progress"]);

function messageOf(e: unknown, fallback: string): string {
  const data = e instanceof ApiError && e.data && typeof e.data === "object" ? (e.data as { detail?: string }) : {};
  return data.detail ?? fallback;
}

/**
 * État du suivi d'une mission : WebSocket (billet signé de 60 s) avec reconnexion, et lecture périodique de
 * `GET /live/` si la connexion temps réel est absente ou perdue (réseau, serveur). `realtime` indique si le flux
 * direct est établi ; `offline` si le navigateur n'a plus de réseau.
 */
export function useLive(bookingId: number, enabled = true) {
  const [state, setState] = useState<LiveState | null>(null);
  const [error, setError] = useState("");
  const [realtime, setRealtime] = useState(false);
  const [offline, setOffline] = useState(false);
  const socket = useRef<WebSocket | null>(null);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const s = await get<LiveState>(`/bookings/${bookingId}/live/`);
      if (alive.current) {
        setState(s);
        setError("");
        setOffline(false);
      }
    } catch (e) {
      if (!alive.current) return;
      if (e instanceof ApiError) setError(messageOf(e, "Le suivi est indisponible."));
      else setOffline(true);
    }
  }, [bookingId]);

  // Lecture périodique (toujours active : repli du temps réel et mise à jour de l'ancienneté des positions)
  useEffect(() => {
    if (!enabled) return;
    alive.current = true;
    void refresh();
    const every = realtime ? HEARTBEAT_MS : POLL_MS;
    const id = window.setInterval(() => {
      if (state && !OPEN_PHASES.has(state.phase)) return; // mission terminée / annulée : plus de suivi
      void refresh();
    }, every);
    const onOnline = () => void refresh();
    window.addEventListener("online", onOnline);
    return () => {
      alive.current = false;
      window.clearInterval(id);
      window.removeEventListener("online", onOnline);
    };
  }, [enabled, refresh, realtime, state?.phase]); // eslint-disable-line react-hooks/exhaustive-deps

  // Flux temps réel
  useEffect(() => {
    if (!enabled) return;
    let closed = false;
    let retry: number | null = null;
    let attempt = 0;

    async function open() {
      try {
        const t = await post<{ ticket: string; path: string }>(`/bookings/${bookingId}/live/ticket/`);
        if (closed) return;
        const ws = new WebSocket(liveSocketUrl(t.path, t.ticket));
        socket.current = ws;
        ws.onopen = () => {
          attempt = 0;
          setRealtime(true);
        };
        ws.onmessage = (ev) => {
          try {
            const m = JSON.parse(ev.data) as { type: string; state?: LiveState };
            if (m.type === "state" && m.state) setState(m.state);
          } catch {
            /* message illisible : ignoré */
          }
        };
        ws.onclose = () => {
          setRealtime(false);
          if (!closed) {
            attempt += 1;
            retry = window.setTimeout(open, Math.min(30000, 1000 * 2 ** attempt)); // reconnexion progressive
          }
        };
        ws.onerror = () => ws.close();
      } catch {
        if (!closed) {
          attempt += 1;
          retry = window.setTimeout(open, Math.min(30000, 1000 * 2 ** attempt));
        }
      }
    }
    void open();
    return () => {
      closed = true;
      if (retry) window.clearTimeout(retry);
      socket.current?.close();
    };
  }, [bookingId, enabled]);

  const run = useCallback(
    async (path: string, body?: unknown) => {
      setError("");
      try {
        const s = await post<LiveState>(`/bookings/${bookingId}/live/${path}`, body);
        setState(s);
        return s;
      } catch (e) {
        setError(messageOf(e, "L’action a échoué. Réessayez dans un instant."));
        return null;
      }
    },
    [bookingId],
  );

  return {
    state,
    error,
    realtime,
    offline,
    refresh,
    setConsent: (share: boolean) => run("consent/", { share }),
    startRoute: () => run("en-route/", { consent: true }),
    arrive: () => run("arrived/"),
    sendPosition: (payload: Record<string, unknown>) => post(`/bookings/${bookingId}/live/position/`, payload),
  };
}
