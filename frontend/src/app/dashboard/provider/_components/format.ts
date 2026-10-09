import type { Booking } from "@/lib/types";

/** Utilitaires d'affichage de l'espace artisan (aucune règle métier : mise en forme uniquement). */

/** Prénom du client, à défaut son identifiant ; `null` si l'API n'en fournit aucun. */
export function clientName(b: Booking): string | null {
  const c = b.client_detail;
  return c?.first_name || c?.username || null;
}

/** Date lisible en français ; `null` si la date est absente ou invalide. */
export function formatWhen(iso: string | null | undefined, style: "short" | "long" = "short"): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString("fr-FR", { dateStyle: style === "long" ? "full" : "medium", timeStyle: "short" });
}

/** « Adresse, Ville » sans « undefined » ; `null` si rien n'est renseigné. */
export function formatPlace(b: Pick<Booking, "address" | "city">): string | null {
  const parts = [b.address, b.city].map((p) => p?.trim()).filter(Boolean);
  return parts.length ? parts.join(", ") : null;
}
