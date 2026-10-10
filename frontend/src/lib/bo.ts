import { ApiError, apiErrorMessage, apiJson } from "./api";

/** Client du Back-Office : `/handy/backoffice/…`. Les droits sont appliqués par le serveur ; l'interface ne fait que les refléter. */
const root = (path: string) => `/backoffice${path.startsWith("/") ? path : `/${path}`}`;

export const bo = {
  get: <T>(path: string) => apiJson<T>(root(path)),
  post: <T>(path: string, body?: unknown) => apiJson<T>(root(path), { method: "POST", body: JSON.stringify(body ?? {}) }),
  put: <T>(path: string, body?: unknown) => apiJson<T>(root(path), { method: "PUT", body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body?: unknown) => apiJson<T>(root(path), { method: "PATCH", body: JSON.stringify(body ?? {}) }),
  delete: <T = unknown>(path: string) => apiJson<T>(root(path), { method: "DELETE" }),
};

export interface BoModule {
  id: string;
  label: string;
  permission: string;
  icon: string;
  path: string;
}

export interface BoMe {
  user: { id: number; name: string; is_superuser: boolean };
  roles: string[];
  permissions: string[];
  modules: BoModule[];
}

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/** Message affichable : détail du serveur, « droits insuffisants » sur 403, jamais de trace technique. */
export function boError(e: unknown, fallback: string): string {
  if (e instanceof ApiError && e.status === 403) return "Droits insuffisants pour cette opération.";
  return apiErrorMessage(e, fallback);
}

/** Erreurs par champ d'un formulaire invalide ({code:"invalid", fields:{champ: message}}). */
export function fieldErrors(e: unknown): Record<string, string> {
  if (!(e instanceof ApiError) || !e.data || typeof e.data !== "object") return {};
  const fields = (e.data as { fields?: Record<string, unknown> }).fields;
  if (!fields || typeof fields !== "object") return {};
  return Object.fromEntries(Object.entries(fields).map(([k, v]) => [k, Array.isArray(v) ? String(v[0]) : String(v)]));
}

/** Code d'erreur métier du serveur (`kyc_incomplete`, `not_pending`…). */
export function errorCode(e: unknown): string | null {
  const data = e instanceof ApiError ? (e.data as { code?: unknown } | null) : null;
  return data && typeof data.code === "string" ? data.code : null;
}

const nf = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });

/** « 10000.00 » → « 10 000 FCFA » ; 0 → « 0 FCFA » ; absent → « — ». */
export function moneyLabel(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${nf.format(n)} FCFA` : "—";
}

export const pct = (v: number | null | undefined): string => (v === null || v === undefined ? "—" : `${Math.round(v * 1000) / 10} %`);

/** Message d'un code de motif minimal côté interface (le serveur revalide). */
export const MIN_REASON = 5;
