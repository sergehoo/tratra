/**
 * Indice de session du site (« Se souvenir de moi ») : un cookie LISIBLE sans aucun secret, qui dit seulement qu'une session peut
 * être restaurée par le cookie HttpOnly de l'API (jeton de rafraîchissement, handy/auth_tokens.py). Persistant 30 jours si la case
 * est cochée, sinon cookie de session (effacé à la fermeture du navigateur).
 */
const HINT = "tratra_session";

export function sessionHintCookie(remember: boolean, secure: boolean): string {
  return `${HINT}=1; path=/; SameSite=Lax${remember ? `; max-age=${30 * 24 * 3600}` : ""}${secure ? "; Secure" : ""}`;
}

export function setSessionHint(remember: boolean): void {
  if (typeof document === "undefined") return;
  document.cookie = sessionHintCookie(remember, location.protocol === "https:");
}

export function clearSessionHint(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${HINT}=; path=/; max-age=0; SameSite=Lax`;
}

export function hasSessionHint(): boolean {
  return typeof document !== "undefined" && document.cookie.split("; ").some((c) => c === `${HINT}=1`);
}
