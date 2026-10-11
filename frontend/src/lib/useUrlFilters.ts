"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

/**
 * Filtres d'une liste gardés dans l'URL (lien partageable, retour arrière, recherche globale qui pré-remplit `?q=`).
 *
 * - l'état local est immédiat (les champs ne « sautent » pas) ; l'URL est mise à jour après 300 ms, sans empiler l'historique
 *   et sans remonter la page ;
 * - une valeur égale à son défaut n'apparaît jamais dans l'URL ;
 * - un changement d'URL venu d'ailleurs (lien du menu, recherche globale, retour arrière) remet les champs à jour ;
 * - les autres paramètres (ex. `tab`) sont conservés tels quels.
 */
export function useUrlFilters<T extends Record<string, string>>(defaults: T) {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const defaultsRef = useRef(defaults);

  const read = useCallback((params: URLSearchParams): T => {
    const out: Record<string, string> = { ...defaultsRef.current };
    for (const key of Object.keys(out)) {
      const value = params.get(key);
      if (value !== null) out[key] = value;
    }
    return out as T;
  }, []);

  const [state, setState] = useState<T>(() => read(sp));
  const known = useRef(sp.toString());

  // URL → champs (changement extérieur).
  useEffect(() => {
    const current = sp.toString();
    if (current !== known.current) {
      known.current = current;
      setState(read(sp));
    }
  }, [sp, read]);

  // Champs → URL (débattu).
  useEffect(() => {
    const t = setTimeout(() => {
      const params = new URLSearchParams(window.location.search);
      let changed = false;
      for (const [key, def] of Object.entries(defaultsRef.current)) {
        const wanted = state[key] ?? def;
        if (wanted !== (params.get(key) ?? def)) {
          changed = true;
          if (wanted === def || wanted === "") params.delete(key);
          else params.set(key, wanted);
        }
      }
      if (!changed) return;
      const qs = params.toString();
      known.current = qs;
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    }, 300);
    return () => clearTimeout(t);
  }, [state, pathname, router]);

  const set = useCallback((patch: Partial<T>) => setState((s) => ({ ...s, ...patch })), []);
  const reset = useCallback(() => setState({ ...defaultsRef.current }), []);
  const active = Object.keys(defaultsRef.current).filter((k) => (state[k] ?? "") !== defaultsRef.current[k]).length;
  return { values: state, set, reset, active };
}

/**
 * Onglet courant lu dans `?tab=` (réactif : les sous-menus de la barre latérale changent d'onglet sans recharger la page).
 * Changer d'onglet efface les filtres de l'onglet précédent.
 */
export function useTabParam<T extends string>(allowed: readonly T[], fallback: T): [T, (t: T) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const fromUrl = (): T => {
    const raw = sp.get("tab");
    return (raw && (allowed as readonly string[]).includes(raw) ? raw : fallback) as T;
  };
  const [tab, setTabState] = useState<T>(fromUrl);
  const urlTab = sp.get("tab");
  useEffect(() => {
    setTabState(fromUrl());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlTab]);
  const setTab = useCallback(
    (t: T) => {
      setTabState(t);
      router.replace(`${pathname}?tab=${t}`, { scroll: false });
    },
    [router, pathname],
  );
  return [tab, setTab];
}
