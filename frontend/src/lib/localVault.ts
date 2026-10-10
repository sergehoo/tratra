/**
 * Données locales de continuité (dernier état des activités, brouillons, file hors ligne) : CLOISONNÉES par compte
 * (`tratra:cont:<compte>:<nom>`) pour qu'un second compte sur le même navigateur ne voie jamais celles du premier, et
 * effacées à la déconnexion VOLONTAIRE. Best-effort : un stockage bloqué (navigation privée) se comporte comme vide.
 */
const PREFIX = "tratra:cont:";

function store(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function readLocal<T>(userId: number | string, name: string): T | null {
  try {
    const raw = store()?.getItem(`${PREFIX}${userId}:${name}`);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export function writeLocal(userId: number | string, name: string, value: unknown): void {
  try {
    store()?.setItem(`${PREFIX}${userId}:${name}`, JSON.stringify(value));
  } catch {
    /* quota ou stockage bloqué : la continuité se dégrade, jamais l'application */
  }
}

export function deleteLocal(userId: number | string, name: string): void {
  try {
    store()?.removeItem(`${PREFIX}${userId}:${name}`);
  } catch {
    /* ignoré */
  }
}

/** Déconnexion volontaire : efface TOUTES les données de continuité, de tous les comptes. */
export function wipeContinuity(): void {
  const s = store();
  if (!s) return;
  try {
    const keys: string[] = [];
    for (let i = 0; i < s.length; i++) {
      const key = s.key(i);
      if (key?.startsWith(PREFIX)) keys.push(key); // collecte AVANT de supprimer : on ne modifie pas ce qu'on parcourt
    }
    keys.forEach((key) => s.removeItem(key));
  } catch {
    /* ignoré */
  }
}
