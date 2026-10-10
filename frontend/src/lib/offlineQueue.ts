import { apiFetch } from "./api";
import { deleteLocal, readLocal, writeLocal } from "./localVault";

/**
 * File d'attente hors ligne PERSISTANTE, limitée aux actions SÛRES : sans effet financier ni métier, idempotentes ou
 * sans conséquence si elles sont rejouées (marquer une notification lue, signaler la vue / l'ouverture d'une annonce).
 *
 *  - Les actions CRITIQUES (créer ou annuler une réservation, démarrer / terminer une mission, payer) ne passent JAMAIS
 *    par cette file : `enqueueSafe` les refuse. Elles ne sont affichées comme réussies qu'après confirmation du serveur ;
 *    hors ligne, l'écran dit « non envoyée » et conserve un brouillon.
 *  - Envoi dans l'ordre, arrêt à la première panne réseau (reprise automatique au retour du réseau) ; erreur définitive
 *    (400/403/404/410/422) : abandonnée ; conflit (409/412) : abandonnée et signalée.
 *  - Doublons exacts fusionnés ; 200 actions et 7 jours au maximum ; cloisonnée par compte, effacée au logout.
 */
export interface QueuedAction {
  method: "POST" | "PATCH";
  path: string;
  body?: Record<string, unknown>;
  created_at: string;
  attempts: number;
}

const NAME = "queue";
const MAX_ENTRIES = 200;
const MAX_AGE_MS = 7 * 24 * 3600 * 1000;

const SAFE: Array<[QueuedAction["method"], RegExp]> = [
  ["POST", /^\/notifications\/mark-read\/$/],
  ["PATCH", /^\/notifications\/\d+\/$/],
  ["POST", /^\/me\/announcements\/\d+\/(seen|open)\/$/],
];

export function isSafeAction(method: string, path: string, body?: Record<string, unknown>): boolean {
  if (!SAFE.some(([m, re]) => m === method && re.test(path))) return false;
  // Une notification ne se « dé-lit » pas : seul {is_read: true} est une action sûre.
  if (method === "PATCH") return !!body && Object.keys(body).length === 1 && body.is_read === true;
  return true;
}

function load(userId: number | string): QueuedAction[] {
  const raw = readLocal<QueuedAction[]>(userId, NAME);
  if (!Array.isArray(raw)) return [];
  const cutoff = Date.now() - MAX_AGE_MS;
  return raw.filter((a) => Date.parse(a.created_at) > cutoff);
}

function save(userId: number | string, items: QueuedAction[]): void {
  if (items.length) writeLocal(userId, NAME, items);
  else deleteLocal(userId, NAME);
}

export const pendingCount = (userId: number | string): number => load(userId).length;

let flushing = false;
/** Message d'une action abandonnée sur conflit (affichable une fois). */
export let lastQueueProblem: string | null = null;

/** Envoie dans l'ordre ; s'arrête à la première panne réseau (reprise au prochain appel). */
export async function flushQueue(userId: number | string): Promise<void> {
  if (flushing) return;
  flushing = true;
  try {
    let items = load(userId);
    while (items.length) {
      const action = items[0];
      let status: number;
      try {
        const res = await apiFetch(action.path, { method: action.method, body: JSON.stringify(action.body ?? {}) });
        status = res.status;
      } catch {
        action.attempts += 1;
        save(userId, items);
        return; // réseau indisponible : tout est conservé, dans l'ordre
      }
      if (status === 401 || status === 408 || status === 429 || status >= 500) {
        action.attempts += 1; // session à renouveler ou serveur occupé : réessai plus tard, rien n'est perdu
        save(userId, items);
        return;
      }
      if (status === 409 || status === 412) lastQueueProblem = "Une action a été abandonnée : l’élément a été modifié entre-temps.";
      items = items.slice(1); // succès, erreur définitive ou conflit : plus rien à rejouer
      save(userId, items);
    }
  } finally {
    flushing = false;
  }
}

/** Met l'action en file (persistée) puis tente de l'envoyer. Refuse toute action non « sûre ». */
export async function enqueueSafe(userId: number | string, method: QueuedAction["method"], path: string, body?: Record<string, unknown>): Promise<void> {
  if (!isSafeAction(method, path, body)) throw new Error(`Action non éligible à la file hors ligne : ${method} ${path}`);
  const items = load(userId);
  const same = (a: QueuedAction) => a.method === method && a.path === path && JSON.stringify(a.body ?? {}) === JSON.stringify(body ?? {});
  if (!items.some(same)) {
    items.push({ method, path, body, created_at: new Date().toISOString(), attempts: 0 });
    save(userId, items.slice(-MAX_ENTRIES));
  }
  await flushQueue(userId);
}

export function clearQueueProblem(): void {
  lastQueueProblem = null;
}
