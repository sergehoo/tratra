/**
 * Connexion bloquée après trop de tentatives : le serveur répond 429 `login_locked` avec le temps restant (`retry_after`, en secondes).
 * Fonctions pures (testées par `npm run test:bo`).
 */
export const DEFAULT_SUPPORT_EMAIL = "support@tratra.net";

export interface LoginLock {
  /** Secondes restantes au moment de la réponse. */
  seconds: number;
  supportEmail: string;
}

/** Lit un blocage dans une erreur d'API (`status` 429, `data.code` « login_locked », `data.retry_after` > 0) ; sinon `null`. */
export function parseLoginLock(err: unknown): LoginLock | null {
  const e = err as { status?: unknown; data?: unknown } | null;
  if (!e || e.status !== 429 || typeof e.data !== "object" || e.data === null) return null;
  const data = e.data as { code?: unknown; retry_after?: unknown; support_email?: unknown };
  const seconds = typeof data.retry_after === "number" ? data.retry_after : Number(data.retry_after);
  if (data.code !== "login_locked" || !Number.isFinite(seconds) || seconds <= 0) return null;
  const mail = typeof data.support_email === "string" && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.support_email) ? data.support_email : DEFAULT_SUPPORT_EMAIL;
  return { seconds: Math.ceil(seconds), supportEmail: mail };
}

/** 3330 → « 55:30 » (minutes:secondes ; une heure s'écrit « 60:00 »). Jamais négatif. */
export function formatCountdown(seconds: number): string {
  const s = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/** Secondes restantes jusqu'à `endMs` (horloge `nowMs`), arrondies au-dessus : « 00:01 » tant qu'il reste une fraction de seconde. */
export function secondsLeft(endMs: number, nowMs: number): number {
  return Math.max(0, Math.ceil((endMs - nowMs) / 1000));
}
