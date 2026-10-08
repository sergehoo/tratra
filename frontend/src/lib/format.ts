import type { Service } from "./types";

const fcfa = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });

/** 12500 -> « 12 500 FCFA » ; valeur absente/invalide -> null. */
export function formatFCFA(value: string | number | null | undefined): string | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n) || n <= 0) return null;
  return `${fcfa.format(n)} FCFA`;
}

/** Libellé de prix selon le type de tarification réel du service. */
export function priceLabel(service: Pick<Service, "price" | "price_type">): string {
  const amount = formatFCFA(service.price);
  if (service.price_type === "quote" || !amount) return "Sur devis";
  if (service.price_type === "hourly") return `${amount} / h`;
  return amount;
}

/** Note sur 5 avec une décimale, ou null si aucune note réelle. */
export function formatRating(rating: number | null | undefined): string | null {
  if (rating === null || rating === undefined || !Number.isFinite(rating) || rating <= 0) return null;
  return rating.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

export function formatCount(n: number): string {
  return fcfa.format(n);
}

export function formatDistance(km: number | null | undefined): string | null {
  if (km === null || km === undefined || !Number.isFinite(km)) return null;
  return km < 1 ? `${Math.round(km * 1000)} m` : `${km.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} km`;
}

/** Durée en minutes -> « 1 h 30 ». */
export function formatDuration(minutes: number | null | undefined): string | null {
  if (!minutes || minutes <= 0) return null;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m} min`;
  return m ? `${h} h ${String(m).padStart(2, "0")}` : `${h} h`;
}
