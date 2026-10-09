import type { Variants } from "framer-motion";
import { DURATION } from "@/components/ds";
import { formatFCFA } from "@/lib/format";

/**
 * Aides d'affichage de l'espace entreprise (aucune règle métier).
 * Dossier privé (`_lib`) : non routé par Next.js.
 */

/** Périodicité d'une offre : même lecture qu'avant (`yearly` -> annuel, sinon mensuel). */
export function intervalView(interval: string | null | undefined): { label: string; per: string } | null {
  if (!interval) return null;
  return interval === "yearly" ? { label: "Annuel", per: "/ an" } : { label: "Mensuel", per: "/ mois" };
}

/** « 25 000 FCFA », « Gratuit » pour un prix nul, null si le prix est absent ou invalide. */
export function planPrice(price: string | number | null | undefined): string | null {
  const formatted = formatFCFA(price);
  if (formatted) return formatted;
  if (price === null || price === undefined || price === "") return null;
  return Number(price) === 0 ? "Gratuit" : null;
}

/** Date ISO -> « 8 octobre 2026 » ; null si absente ou illisible. */
export function longDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
}

/** Apparition échelonnée des cartes (jetons de mouvement du Design System). */
export const stagger: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: DURATION.fast / 2 } },
};
