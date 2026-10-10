"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { bo, boError, type Page } from "./bo";

/** Valeur « débattue » (saisie de recherche) : évite une requête par frappe. */
export function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/**
 * Liste paginée d'un module : retourne à la page 1 quand un filtre change, garde les lignes précédentes pendant le
 * rechargement (pas de scintillement), expose l'erreur réelle et un rechargement manuel.
 */
export function useBoList<T>(path: string, params: Record<string, string | number | undefined | null> = {}, pageSize?: number) {
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<T[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const seq = useRef(0);
  const key = JSON.stringify(params);
  const lastKey = useRef(key);

  const load = useCallback(
    async (target: number) => {
      const mine = ++seq.current;
      setLoading(true);
      setError("");
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(JSON.parse(key) as Record<string, string | number | null>)) {
        if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
      }
      qs.set("page", String(target));
      if (pageSize) qs.set("page_size", String(pageSize));
      try {
        const data = await bo.get<Page<T>>(`${path}?${qs.toString()}`);
        if (mine !== seq.current) return; // une requête plus récente a pris le relais
        setRows(data.results);
        setCount(data.count);
      } catch (e) {
        if (mine !== seq.current) return;
        setError(boError(e, "La liste n’a pas pu être chargée."));
      } finally {
        if (mine === seq.current) setLoading(false);
      }
    },
    [path, key, pageSize],
  );

  useEffect(() => {
    if (lastKey.current !== key) {
      lastKey.current = key;
      if (page !== 1) {
        setPage(1);
        return;
      }
    }
    void load(page);
  }, [key, page, load]);

  return { rows, count, page, setPage, loading, error, reload: () => load(page), pageSize: pageSize ?? 25 };
}
