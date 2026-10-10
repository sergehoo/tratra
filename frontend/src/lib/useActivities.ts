"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { get } from "./api";
import { useAuth } from "./auth";
import type { Activity, ActivitiesResponse } from "./continuity";
import { readLocal, writeLocal } from "./localVault";
import { flushQueue } from "./offlineQueue";

interface Cache {
  synced_at: string;
  cursor: string;
  items: Activity[];
}

export interface ActivitiesState {
  items: Activity[];
  primary: Activity | null;
  /** Dernier état connu (coffre local) affiché en attendant le serveur. */
  fromCache: boolean;
  /** Serveur injoignable : l'état affiché est le dernier connu, JAMAIS présenté comme à jour. */
  offline: boolean;
  syncedAt: string | null;
  /** Changement fait ailleurs (autre appareil, autre partie) pendant l'absence : affiché une fois. */
  notice: string | null;
  loading: boolean;
}

const POLL_MS = 60_000;
const RETRY_BASE_MS = 8_000;
const RETRY_MAX_MS = 60_000;
const MIN_INTERVAL_MS = 5_000;

/**
 * Reprise des activités : à l'ouverture, au retour sur l'onglet, quand le réseau revient et toutes les minutes, la page
 * interroge le serveur (source de vérité) et affiche d'abord le dernier état connu. Hors ligne : état conservé, signalé,
 * nouvelles tentatives espacées (8 s → 60 s). Chaque synchronisation réussie vide la file des actions sûres.
 */
export function useActivities() {
  const { user } = useAuth();
  const userId = user?.id ?? null;
  const [state, setState] = useState<ActivitiesState>({ items: [], primary: null, fromCache: false, offline: false, syncedAt: null, notice: null, loading: true });
  const cursor = useRef<string | null>(null);
  const items = useRef<Activity[]>([]);
  const failures = useRef(0);
  const retry = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastAttempt = useRef(0);
  const inFlight = useRef(false);
  const uid = useRef<typeof userId>(null);

  const refresh = useCallback(
    async (force = false) => {
      const current = uid.current;
      if (current === null || inFlight.current) return;
      if (!force && Date.now() - lastAttempt.current < MIN_INTERVAL_MS) return;
      lastAttempt.current = Date.now();
      inFlight.current = true;
      try {
        const path = cursor.current ? `/me/activities/?since=${encodeURIComponent(cursor.current)}` : "/me/activities/";
        const body = await get<ActivitiesResponse>(path);
        if (uid.current !== current) return; // le compte a changé pendant la requête : réponse ignorée
        const before = items.current;
        const stillActive = new Set(body.activities.map((a) => `${a.kind}:${a.id}`));
        const lines = (body.changes ?? [])
          .filter((c) => !c.active && before.some((b) => b.kind === c.kind && b.id === c.id) && !stillActive.has(`${c.kind}:${c.id}`))
          .map((c) => `« ${c.title} » : ${c.status_label.toLowerCase()}.`);
        items.current = body.activities;
        cursor.current = body.server_time;
        failures.current = 0;
        if (retry.current) clearTimeout(retry.current);
        writeLocal(current, "activities", { synced_at: body.server_time, cursor: body.server_time, items: body.activities } satisfies Cache);
        setState((s) => ({
          items: body.activities,
          primary: body.primary,
          fromCache: false,
          offline: false,
          syncedAt: body.server_time,
          notice: lines.length ? `Mise à jour depuis un autre appareil ou l’autre partie — ${lines.join(" ")}` : s.notice,
          loading: false,
        }));
        void flushQueue(current);
      } catch {
        if (uid.current !== current) return;
        failures.current += 1;
        const delay = Math.min(RETRY_BASE_MS * 2 ** Math.min(failures.current - 1, 6), RETRY_MAX_MS);
        if (retry.current) clearTimeout(retry.current);
        retry.current = setTimeout(() => void refresh(true), delay);
        // le détail technique n'est jamais affiché : seul l'état « hors ligne » l'est
        setState((s) => ({ ...s, offline: true, loading: false }));
      } finally {
        inFlight.current = false;
      }
    },
    [],
  );

  useEffect(() => {
    uid.current = userId;
    cursor.current = null;
    items.current = [];
    failures.current = 0;
    if (retry.current) clearTimeout(retry.current);
    if (userId === null) {
      setState({ items: [], primary: null, fromCache: false, offline: false, syncedAt: null, notice: null, loading: false });
      return;
    }
    const cached = readLocal<Cache>(userId, "activities");
    if (cached && Array.isArray(cached.items)) {
      items.current = cached.items;
      cursor.current = cached.cursor ?? null;
      setState({ items: cached.items, primary: cached.items[0] ?? null, fromCache: cached.items.length > 0, offline: false, syncedAt: cached.synced_at ?? null, notice: null, loading: true });
    } else {
      setState({ items: [], primary: null, fromCache: false, offline: false, syncedAt: null, notice: null, loading: true });
    }
    void refresh(true);
    const resume = () => {
      if (document.visibilityState === "visible") void refresh(true);
    };
    const online = () => void refresh(true);
    window.addEventListener("focus", resume);
    document.addEventListener("visibilitychange", resume);
    window.addEventListener("online", online);
    const poll = setInterval(() => document.visibilityState === "visible" && void refresh(), POLL_MS);
    return () => {
      uid.current = null;
      window.removeEventListener("focus", resume);
      document.removeEventListener("visibilitychange", resume);
      window.removeEventListener("online", online);
      clearInterval(poll);
      if (retry.current) clearTimeout(retry.current);
    };
  }, [userId, refresh]);

  const clearNotice = useCallback(() => setState((s) => ({ ...s, notice: null })), []);
  return { ...state, refresh, clearNotice };
}
