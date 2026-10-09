import { API_BASE } from "./config";
import type { User } from "./types";

const ACCESS = "tratra_access";
const REFRESH = "tratra_refresh";
export const SESSION_EXPIRED_EVENT = "tratra:session-expired";

/**
 * Les jetons ne sont volontairement conservés que pour la session du navigateur.
 * Une migration serveur vers des cookies HttpOnly reste la protection XSS cible ;
 * le front ne peut pas créer ces cookies de manière sûre à lui seul.
 */
function storage(kind: "session" | "legacy"): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return kind === "session" ? window.sessionStorage : window.localStorage;
  } catch {
    return null;
  }
}

function readSession(key: string): string | null {
  try {
    return storage("session")?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function apiUrl(path: string) {
  const base = new URL(API_BASE);
  if (/^https?:\/\//i.test(path)) {
    const target = new URL(path);
    // Never forward a bearer token to an arbitrary URL returned by an API.
    if (target.origin !== base.origin) throw new Error("URL API non approuvée");
    return target.toString();
  }
  // DRF's reverse() returns a root-relative path such as /handy/... for a
  // guarded download action.  Avoid duplicating the /handy prefix.
  if (path.startsWith("/handy/")) return `${base.origin}${path}`;
  return `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
}

function expireSession() {
  tokens.clear();
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  }
}

export const tokens = {
  get access(): string | null {
    return readSession(ACCESS);
  },
  get refresh(): string | null {
    return readSession(REFRESH);
  },
  set(access?: string | null, refresh?: string | null) {
    const session = storage("session");
    const legacy = storage("legacy");
    try {
      if (access) session?.setItem(ACCESS, access);
      if (refresh) session?.setItem(REFRESH, refresh);
      // Ne jamais laisser une ancienne copie persistante après connexion.
      legacy?.removeItem(ACCESS);
      legacy?.removeItem(REFRESH);
    } catch {
      // Certains navigateurs bloquent le stockage privé : la session reste active
      // jusqu'au rechargement plutôt que de faire échouer la connexion.
    }
  },
  clear() {
    for (const kind of ["session", "legacy"] as const) {
      try {
        storage(kind)?.removeItem(ACCESS);
        storage(kind)?.removeItem(REFRESH);
      } catch {
        // Best effort : le stockage peut être indisponible en navigation privée.
      }
    }
  },
  /** Déplace une session créée par une ancienne version hors de localStorage. */
  migrateLegacy() {
    const session = storage("session");
    const legacy = storage("legacy");
    if (!session || !legacy) return;

    try {
      for (const key of [ACCESS, REFRESH]) {
        const value = legacy.getItem(key);
        if (value && !session.getItem(key)) session.setItem(key, value);
        legacy.removeItem(key);
      }
    } catch {
      // La lecture est facultative : ne pas bloquer l'application si elle échoue.
    }
  },
};

export class ApiError extends Error {
  status: number;
  data: unknown;
  constructor(status: number, data: unknown) {
    super(`API ${status}`);
    this.status = status;
    this.data = data;
  }
}

let refreshInFlight: Promise<string | null> | null = null;

async function refreshAccess(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;

  const r = tokens.refresh;
  if (!r) {
    expireSession();
    return null;
  }

  refreshInFlight = (async () => {
    try {
      const res = await fetch(apiUrl("/auth/refresh/"), {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ refresh: r }),
        cache: "no-store",
        credentials: "omit",
      });
      if (!res.ok) {
        // Une erreur réseau/serveur ne détruit pas une session potentiellement valide.
        if (res.status >= 400 && res.status < 500) expireSession();
        return null;
      }
      const data = await res.json();
      if (data?.access) {
        tokens.set(data.access, data.refresh);
        return data.access as string;
      }
      expireSession();
      return null;
    } catch {
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

/** fetch auto-authentifié : ajoute le Bearer, rafraîchit le token sur 401 puis rejoue. */
export async function apiFetch(
  path: string,
  opts: RequestInit = {},
  retry = true,
): Promise<Response> {
  const headers = new Headers(opts.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (opts.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const access = tokens.access;
  if (access) headers.set("Authorization", `Bearer ${access}`);

  const res = await fetch(apiUrl(path), {
    ...opts,
    headers,
    cache: "no-store",
    credentials: opts.credentials ?? "omit",
  });
  if (res.status === 401 && retry) {
    const na = await refreshAccess();
    if (na) return apiFetch(path, opts, false);
  }
  return res;
}

async function parse(res: Response): Promise<unknown> {
  if (res.status === 204) return null;
  const text = await res.text();
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    return text;
  }
}

export async function apiJson<T = unknown>(
  path: string,
  opts: RequestInit = {},
): Promise<T> {
  const res = await apiFetch(path, opts);
  const data = await parse(res);
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}

export const get = <T>(p: string) => apiJson<T>(p);
export const post = <T>(p: string, body?: unknown) =>
  apiJson<T>(p, { method: "POST", body: body ? JSON.stringify(body) : undefined });
export const patch = <T>(p: string, body?: unknown) =>
  apiJson<T>(p, { method: "PATCH", body: body ? JSON.stringify(body) : undefined });
export const del = <T = unknown>(p: string) => apiJson<T>(p, { method: "DELETE" });

/**
 * Fetches an authenticated, private document through the guarded API endpoint.
 * The caller owns the returned object URL and must revoke it after
 * opening/downloading the file.
 */
export async function privateFileUrl(path: string): Promise<string> {
  const res = await apiFetch(path);
  if (!res.ok) {
    const data = await parse(res);
    throw new ApiError(res.status, data);
  }
  return URL.createObjectURL(await res.blob());
}

/** Upload multipart (fichiers, ex. documents KYC) — gère aussi le refresh 401. */
export async function upload<T>(path: string, form: FormData, retry = true): Promise<T> {
  const headers: Record<string, string> = {};
  const access = tokens.access;
  if (access) headers["Authorization"] = `Bearer ${access}`;
  let res = await fetch(apiUrl(path), {
    method: "POST",
    headers,
    body: form,
    cache: "no-store",
    credentials: "omit",
  });
  if (res.status === 401 && retry) {
    const na = await refreshAccess();
    if (na) {
      headers["Authorization"] = `Bearer ${na}`;
      res = await fetch(apiUrl(path), {
        method: "POST",
        headers,
        body: form,
        cache: "no-store",
        credentials: "omit",
      });
    }
  }
  const data = await parse(res);
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}

// ---- Auth ----
export async function login(username: string, password: string): Promise<User> {
  const data = await apiJson<{ access: string; refresh: string; user?: User }>(
    "/auth/login/",
    { method: "POST", body: JSON.stringify({ username, password }) },
  );
  tokens.set(data.access, data.refresh);
  return data.user ?? (await me());
}

export const me = () => get<User>("/users/me/");

export async function register(payload: {
  username: string;
  email: string;
  password: string;
  user_type: string;
  first_name?: string;
  last_name?: string;
  phone?: string;
}): Promise<User> {
  await apiJson("/users/", { method: "POST", body: JSON.stringify(payload) });
  return login(payload.username, payload.password);
}

export async function logout(): Promise<void> {
  const refresh = tokens.refresh;
  try {
    if (refresh) await apiFetch("/auth/logout/", { method: "POST", body: JSON.stringify({ refresh }) });
  } catch {
    /* best-effort */
  }
  tokens.clear();
}

function collectErrorMessages(data: unknown): string[] {
  if (typeof data === "string") return [data];
  if (Array.isArray(data)) return data.flatMap(collectErrorMessages);
  if (data && typeof data === "object") {
    // Erreur codée {code, detail, fields} : `code` (chaîne) est destiné au programme.
    return Object.entries(data)
      .filter(([key, value]) => !(key === "code" && typeof value === "string"))
      .flatMap(([, value]) => collectErrorMessages(value));
  }
  return [];
}

/** Retourne un message affichable sans exposer de détail technique de l'API. */
export function apiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    const message = collectErrorMessages(error.data).filter(Boolean).join(" ");
    return message || fallback;
  }
  if (error instanceof TypeError) {
    return "Impossible de joindre le service. Vérifiez votre connexion puis réessayez.";
  }
  return fallback;
}
