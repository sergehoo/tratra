"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { bo, boError, type Page } from "./bo";
import { useUrlFilters } from "./useUrlFilters";

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

/**
 * Liste de gestion complète : filtres gardés dans l'URL (partageables), recherche débattue, tri serveur (`ordering`), taille de page,
 * chargement paginé et actualisation. `defaults` = filtres propres à la page (valeur par défaut = « Tous »).
 */
export function useManagedList<T, D extends Record<string, string>>(path: string, defaults: D, extra: Record<string, string | number | undefined | null> = {}) {
  const filters = useUrlFilters({ q: "", ordering: "", size: "25", ...defaults });
  const { size, ...rest } = filters.values;
  const pageSize = [25, 50, 100].includes(Number(size)) ? Number(size) : 25;
  // Tous les filtres sont débattus ensemble : une frappe (recherche, ville…) ne lance pas une requête par lettre.
  const params = JSON.parse(useDebounced(JSON.stringify(rest), 300)) as Record<string, string>;
  const list = useBoList<T>(path, { ...params, ...extra }, pageSize);
  const filterKeys = ["q", ...Object.keys(defaults)];
  const activeCount = filterKeys.filter((k) => (filters.values[k] ?? "") !== (k === "q" ? "" : defaults[k])).length;
  const reset = () => filters.set(Object.fromEntries(filterKeys.map((k) => [k, k === "q" ? "" : defaults[k]])) as Partial<typeof filters.values>);
  return { values: filters.values as typeof filters.values & D, set: filters.set, reset, activeCount, list, pageSize };
}

/**
 * Compteurs réels par état (ex. KYC : à examiner / prêts / approuvés…) : une requête légère (`page_size=1`) par variante,
 * relancée quand `refresh` change. Une variante refusée (droit) ou en erreur reste « inconnue » (null), jamais 0.
 */
export function useCounts(path: string, variants: Record<string, string>, refresh: unknown = 0) {
  const [counts, setCounts] = useState<Record<string, number | null>>({});
  const key = JSON.stringify(variants);
  useEffect(() => {
    let alive = true;
    for (const [name, query] of Object.entries(JSON.parse(key) as Record<string, string>)) {
      bo.get<Page<unknown>>(`${path}?${query}${query ? "&" : ""}page_size=1`)
        .then((p) => alive && setCounts((c) => ({ ...c, [name]: p.count })))
        .catch(() => alive && setCounts((c) => ({ ...c, [name]: null })));
    }
    return () => {
      alive = false;
    };
  }, [path, key, refresh]);
  return counts;
}
