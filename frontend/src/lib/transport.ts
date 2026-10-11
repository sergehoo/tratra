import { ApiError, post } from "./api";

export interface TransportQuote {
  version: number;
  amount: number;
  currency: string;
  applicable: boolean;
  reason: "no_travel" | "disabled" | "within_threshold" | "fallback_flat" | "rate" | null;
  fallback: boolean;
  fallback_reason: "distance_unavailable" | "no_applicable_rate" | null;
  distance_km: number | null;
  distance_unavailable: boolean;
  threshold_km: number;
  multiplier: number | null;
  billable_km: number | null;
  band: { name: string; rate_per_km: number; start: string; end: string } | null;
  slot: string;
}

export interface TransportSlot {
  key: string;
  label: string;
  starts_at: string;
  amount: number;
  fallback: boolean;
  distance_unavailable: boolean;
  band: string | null;
}

export interface TransportEstimateInput {
  service: number;
  lat?: number;
  lng?: number;
  address_id?: number;
  commune?: string;
  city?: string;
  when?: string;
}

export const estimateTransport = (input: TransportEstimateInput) =>
  post<{ quote: TransportQuote; suggestions: TransportSlot[]; needs_travel: boolean }>("/transport/quote/", input);

/** 409 `transport_changed` : le serveur a recalculé un autre montant ; le client doit le confirmer. */
export function changedTransportQuote(error: unknown): TransportQuote | null {
  if (error instanceof ApiError && error.status === 409 && error.data && typeof error.data === "object") {
    const d = error.data as { code?: string; quote?: TransportQuote };
    if (d.code === "transport_changed" && d.quote) return d.quote;
  }
  return null;
}

export const fcfa = (n: number) => `${new Intl.NumberFormat("fr-FR").format(n)} FCFA`;

/** Phrase claire décrivant UN devis (jamais de montant sans explication). */
export function describeQuote(q: TransportQuote): string {
  if (!q.applicable) return q.reason === "no_travel" ? "Cette prestation ne nécessite pas de déplacement." : "Aucun frais de déplacement n’est appliqué.";
  if (q.reason === "within_threshold") return `Lieu proche (moins de ${q.threshold_km} km) : déplacement offert.`;
  if (q.fallback) return q.fallback_reason === "distance_unavailable" ? "Distance indisponible : forfait de déplacement appliqué." : "Aucun tarif horaire pour ce créneau : forfait de déplacement appliqué.";
  return `${q.distance_km} km${q.multiplier === 2 ? " (aller-retour)" : ""} · tranche « ${q.band?.name} » ${q.band?.rate_per_km} FCFA/km`;
}
