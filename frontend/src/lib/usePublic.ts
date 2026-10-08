"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { publicGet } from "./public";

export interface PublicDataState<T> {
  data: T | null;
  loading: boolean;
  error: boolean;
  reload: () => void;
}

export interface PublicDataOptions {
  /**
   * Recharge au montage même si une donnée pré-rendue existe (HTML ISR
   * potentiellement ancien : URLs média signées expirées, compteurs figés).
   * La donnée serveur reste affichée pendant ce rafraîchissement silencieux
   * (pas de `loading`) et est conservée s'il échoue.
   */
  refreshOnMount?: boolean;
}

/**
 * Données publiques hydratées : utilise `initial` (pré-rendu serveur) quand il
 * est disponible, sinon charge côté client (afficher un squelette tant que
 * `loading`). `path = null` désactive le chargement.
 */
export function usePublicData<T>(
  path: string | null,
  initial?: T | null,
  { refreshOnMount = false }: PublicDataOptions = {},
): PublicDataState<T> {
  const [data, setData] = useState<T | null>(initial ?? null);
  const [loading, setLoading] = useState<boolean>(initial == null && path != null);
  const [error, setError] = useState(false);
  const [nonce, setNonce] = useState(0);
  // Chemin couvert par la donnée pré-rendue : tant que ni le chemin ni le
  // compteur de rechargement ne changent, on ne refait pas l'appel (robuste au
  // double montage de React StrictMode en développement), sauf `refreshOnMount`.
  const initialPath = useRef(initial != null ? path : null);

  useEffect(() => {
    if (!path) return;
    const revalidating = nonce === 0 && path === initialPath.current;
    if (revalidating && !refreshOnMount) return;
    const controller = new AbortController();
    if (!revalidating) {
      setLoading(true);
      setError(false);
    }
    publicGet<T>(path, { signal: controller.signal }).then((result) => {
      if (controller.signal.aborted) return;
      if (revalidating) {
        // Rafraîchissement silencieux : un échec garde la donnée serveur.
        if (result !== null) setData(result);
        return;
      }
      setData(result);
      setError(result === null);
      setLoading(false);
    });
    return () => controller.abort();
  }, [path, nonce, refreshOnMount]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, loading, error, reload };
}
