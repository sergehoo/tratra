import { API_BASE } from "./config";
import { wipeContinuity } from "./localVault";
import { clearSessionHint, hasSessionHint, setSessionHint } from "./sessionHint";
export { hasSessionHint } from "./sessionHint";
import type { User } from "./types";

const ACCESS = "tratra_access";
const REFRESH = "tratra_refresh";
export const SESSION_EXPIRED_EVENT = "tratra:session-expired";

/**
 * Jeton d'ACCÈS (30 min) : mémoire de l'onglet (sessionStorage). Jeton de RAFRAÎCHISSEMENT : cookie HttpOnly posé par l'API
 * (handy/auth_tokens.py, jamais lisible ici), persistant si « Se souvenir de moi » est coché, sinon cookie de session (fin à la
 * fermeture du navigateur). Une ancienne session encore porteuse d'un jeton de rafraîchissement en sessionStorage migre vers le
 * cookie à son prochain renouvellement. Un simple indice (cookie lisible, sans secret) dit qu'une session peut être restaurée.
 */
const AUTH_TRANSPORT = { "X-Auth-Transport": "cookie" } as const;

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
  clearSessionHint();
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
  /** Le jeton de rafraîchissement est désormais dans le cookie HttpOnly : l'ancienne copie lisible est effacée. */
  dropRefresh() {
    try {
      storage("session")?.removeItem(REFRESH);
    } catch {
      // Best effort.
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
  if (!r && !hasSessionHint()) {
    expireSession();
    return null;
  }

  refreshInFlight = (async () => {
    try {
      const res = await fetch(apiUrl("/auth/refresh/"), {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", ...AUTH_TRANSPORT },
        body: JSON.stringify(r ? { refresh: r } : {}),
        cache: "no-store",
        credentials: "include",                      // cookie HttpOnly du jeton de rafraîchissement (même site que l'API)
      });
      if (!res.ok) {
        // Une erreur réseau/serveur ne détruit pas une session potentiellement valide.
        if (res.status >= 400 && res.status < 500) expireSession();
        return null;
      }
      const data = await res.json();
      if (data?.access) {
        tokens.set(data.access, data.refresh);
        if (!data.refresh) tokens.dropRefresh();   // rotation reçue dans le cookie : plus aucune copie lisible
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
export async function upload<T>(path: string, form: FormData, retry = true, extraHeaders: Record<string, string> = {}): Promise<T> {
  const headers: Record<string, string> = { ...extraHeaders };
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

/**
 * Envoi multipart AVEC progression (XMLHttpRequest : `fetch` n'expose pas la progression d'envoi). Rafraîchit le jeton sur 401 puis rejoue UNE fois.
 * `signal` permet d'annuler. Les envois de messages et de statuts sont idempotents (`client_id`) : rejouer après une coupure ne crée pas de doublon.
 */
export function uploadWithProgress<T>(path: string, form: FormData, onProgress?: (ratio: number) => void, signal?: AbortSignal): Promise<T> {
  const attempt = (access: string | null, retry: boolean): Promise<T> =>
    new Promise<T>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", apiUrl(path));
      xhr.setRequestHeader("Accept", "application/json");
      if (access) xhr.setRequestHeader("Authorization", `Bearer ${access}`);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress?.(e.loaded / e.total);
      };
      xhr.onerror = () => reject(new TypeError("network"));
      xhr.onabort = () => reject(new DOMException("aborted", "AbortError"));
      xhr.onload = async () => {
        if (xhr.status === 401 && retry) {
          const fresh = await refreshAccess();
          if (fresh) return attempt(fresh, false).then(resolve, reject);
        }
        let data: unknown = null;
        try {
          data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
        } catch {
          data = xhr.responseText;
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
        else reject(new ApiError(xhr.status, data));
      };
      signal?.addEventListener("abort", () => xhr.abort(), { once: true });
      xhr.send(form);
    });
  return attempt(tokens.access, true);
}

// ---- Auth ----
/** Connexion : `identifier` = téléphone (+225 par défaut), ou identifiant / e-mail d'un ancien compte. */
/** Connexion. `remember` (« Se souvenir de moi », coché par défaut) : session gardée après la fermeture du navigateur et restaurée
 *  automatiquement ; sinon elle s'arrête avec la session du navigateur. Aucun mot de passe n'est conservé. */
export async function login(identifier: string, password: string, remember = true): Promise<User> {
  const data = await apiJson<{ access: string; refresh?: string; user?: User }>(
    "/auth/login/",
    { method: "POST", body: JSON.stringify({ username: identifier, password, remember_me: remember }), headers: AUTH_TRANSPORT,
      credentials: "include" },
  );
  tokens.clear();                                  // changement de compte : rien de l'ancienne session ne survit
  tokens.set(data.access, data.refresh);           // `refresh` absent : il est dans le cookie HttpOnly (API à jour)
  setSessionHint(remember);
  return data.user ?? (await me());
}

/** Démarrage : session restaurable sans jeton d'accès (nouvel onglet, réouverture du navigateur) ? Renouvelle par le cookie. */
export async function resumeSession(): Promise<boolean> {
  if (tokens.access || tokens.refresh) return true;
  if (!hasSessionHint()) return false;
  return (await refreshAccess()) !== null;
}

export const me = () => get<User>("/users/me/");

/** Inscription du compte unique (POST /users/) puis connexion par téléphone. Le téléphone reste
 *  NON vérifié tant qu'un code n'a pas été validé. */
export async function register(payload: {
  first_name: string;
  last_name: string;
  /** E.164 (voir lib/phone.ts) ; le serveur revalide avec libphonenumber. */
  phone: string;
  /** Pays choisi pour le numéro (ISO 3166, ex. « CI »). */
  phone_country?: string;
  password: string;
  accept_terms: boolean;
}): Promise<User> {
  await apiJson("/users/", { method: "POST", body: JSON.stringify(payload) });
  return login(payload.phone, payload.password);
}

export async function logout(): Promise<void> {
  const refresh = tokens.refresh;
  try {
    // Révoque le jeton (cookie HttpOnly et, pour une ancienne session, copie lisible) ; l'API efface le cookie.
    await apiFetch("/auth/logout/", { method: "POST", body: JSON.stringify(refresh ? { refresh } : {}), headers: AUTH_TRANSPORT,
      credentials: "include" }, false);
  } catch {
    /* best-effort */
  }
  tokens.clear();
  clearSessionHint();
  // Déconnexion VOLONTAIRE : brouillons, file hors ligne et dernier état des activités sont effacés de cet appareil.
  // (Une session expirée ne purge rien : l'utilisateur retrouve ses brouillons à la reconnexion.)
  wipeContinuity();
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
