"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { publicGet, resultsOf } from "@/lib/public";
import type { Paginated, Service } from "@/lib/types";

export type SearchStatus = "waiting" | "loading" | "ready" | "error";
export type MoreStatus = "idle" | "loading" | "error";

export interface ServiceSearch {
  items: Service[];
  /** Nombre total réel renvoyé par l'API (null tant qu'inconnu). */
  count: number | null;
  status: SearchStatus;
  more: MoreStatus;
  hasMore: boolean;
  loadMore: () => void;
  retry: () => void;
}

const TIMEOUT_MS = 8000;

function withPage(query: string, page: number): string {
  if (page <= 1) return query;
  return `${query}${query.includes("?") ? "&" : "?"}page=${page}`;
}

function totalOf(data: Paginated<Service> | Service[], fallback: number): number {
  return !Array.isArray(data) && typeof data.count === "number" ? data.count : fallback;
}

function nextOf(data: Paginated<Service> | Service[]): boolean {
  return !Array.isArray(data) && Boolean(data.next);
}

/**
 * Résultats paginés « Charger plus » pour une requête publique.
 * - `query = null` : prérequis non prêts (ex. catégories en cours de chargement).
 * - Toute requête obsolète est annulée (AbortController) ; une réponse tardive
 *   d'une ancienne requête n'écrase jamais la nouvelle.
 * - Les résultats précédents restent affichés (atténués) pendant un rechargement.
 */
export function useServiceSearch(query: string | null): ServiceSearch {
  const [items, setItems] = useState<Service[]>([]);
  const [count, setCount] = useState<number | null>(null);
  const [status, setStatus] = useState<SearchStatus>(query ? "loading" : "waiting");
  const [more, setMore] = useState<MoreStatus>("idle");
  const [hasMore, setHasMore] = useState(false);
  const [nonce, setNonce] = useState(0);

  const queryRef = useRef(query);
  const pageRef = useRef(1);
  const moreCtrl = useRef<AbortController | null>(null);

  useEffect(() => {
    queryRef.current = query;
    moreCtrl.current?.abort();
    moreCtrl.current = null;
    setMore("idle");
    if (!query) {
      setStatus("waiting");
      return;
    }
    const ctrl = new AbortController();
    setStatus("loading");
    publicGet<Paginated<Service> | Service[]>(query, { signal: ctrl.signal, timeoutMs: TIMEOUT_MS }).then((data) => {
      if (ctrl.signal.aborted) return;
      if (!data) {
        setItems([]);
        setCount(null);
        setHasMore(false);
        setStatus("error");
        return;
      }
      const results = resultsOf(data);
      pageRef.current = 1;
      setItems(results);
      setCount(totalOf(data, results.length));
      setHasMore(nextOf(data));
      setStatus("ready");
    });
    return () => ctrl.abort();
  }, [query, nonce]);

  useEffect(() => () => moreCtrl.current?.abort(), []);

  const loadMore = useCallback(() => {
    const q = queryRef.current;
    if (!q || moreCtrl.current) return;
    const nextPage = pageRef.current + 1;
    const ctrl = new AbortController();
    moreCtrl.current = ctrl;
    setMore("loading");
    publicGet<Paginated<Service> | Service[]>(withPage(q, nextPage), {
      signal: ctrl.signal,
      timeoutMs: TIMEOUT_MS,
    }).then((data) => {
      if (ctrl.signal.aborted || queryRef.current !== q) return;
      moreCtrl.current = null;
      if (!data) {
        setMore("error");
        return;
      }
      const results = resultsOf(data);
      pageRef.current = nextPage;
      setItems((prev) => {
        const seen = new Set(prev.map((s) => s.id));
        return [...prev, ...results.filter((s) => !seen.has(s.id))];
      });
      setCount((prev) => totalOf(data, prev ?? 0));
      setHasMore(nextOf(data));
      setMore("idle");
    });
  }, []);

  const retry = useCallback(() => setNonce((n) => n + 1), []);

  return { items, count, status, more, hasMore, loadMore, retry };
}
