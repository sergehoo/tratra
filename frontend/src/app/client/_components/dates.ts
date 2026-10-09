/** Formatage des dates de réservation (affichage uniquement, fuseau de l'appareil). */

const DAY = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
const DAY_LONG = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const TIME = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });

/** Date valide, ou null (valeur absente, vide ou illisible). */
export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** « mer. 14 oct. 2026 · 09:30 » — format compact des listes. */
export function formatDateTimeShort(value: string | null | undefined): string | null {
  const date = parseDate(value);
  return date ? `${DAY.format(date)} · ${TIME.format(date)}` : null;
}

/** « mercredi 14 octobre 2026 à 09:30 » — format complet des fiches. */
export function formatDateTimeLong(value: string | null | undefined): string | null {
  const date = parseDate(value);
  return date ? `${DAY_LONG.format(date)} à ${TIME.format(date)}` : null;
}
