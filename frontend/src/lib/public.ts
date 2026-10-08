import { API_BASE } from "./config";
import type { Paginated } from "./types";

/**
 * Lecture PUBLIQUE de l'API (landing, recherche) : jamais d'en-tête
 * Authorization. Un jeton expiré d'un visiteur ne doit ni faire échouer une
 * page publique ni déclencher de redirection vers /login.
 *
 * Utilisable côté serveur (Server Components, avec cache ISR) comme côté client.
 * Retourne `null` en cas d'échec réseau/HTTP : l'appelant affiche alors un état
 * vide ou recharge côté client — jamais de donnée inventée.
 */
const SERVER_API_BASE = (process.env.API_INTERNAL_BASE || API_BASE).replace(/\/+$/, "");

export interface PublicFetchOptions {
  /** Durée de cache ISR côté serveur (secondes). Ignoré côté navigateur. */
  revalidate?: number;
  timeoutMs?: number;
  signal?: AbortSignal;
}

export function publicUrl(path: string): string {
  const base = typeof window === "undefined" ? SERVER_API_BASE : API_BASE;
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function publicGet<T>(path: string, opts: PublicFetchOptions = {}): Promise<T | null> {
  const { revalidate = 300, timeoutMs = 4000, signal } = opts;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const onAbort = () => controller.abort();
  signal?.addEventListener("abort", onAbort);
  try {
    const init: RequestInit & { next?: { revalidate: number } } = {
      headers: { Accept: "application/json" },
      credentials: "omit",
      signal: controller.signal,
    };
    if (typeof window === "undefined") init.next = { revalidate };
    else init.cache = "no-store";
    const res = await fetch(publicUrl(path), init);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

/** Normalise une réponse paginée DRF ou un tableau brut. */
export function resultsOf<T>(data: Paginated<T> | T[] | null | undefined): T[] {
  if (!data) return [];
  return Array.isArray(data) ? data : data.results ?? [];
}

/** Construit une query string en ignorant les valeurs vides. */
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "" || v === false) continue;
    sp.set(k, v === true ? "1" : String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}
