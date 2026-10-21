/**
 * Modèle Hybrid Matching (site) SANS dépendance : types, libellés et règles pures, testables par `node --test`.
 * Les appels réseau sont dans `flash.ts`.
 */
export type Matching = "auto" | "direct";
export type RequestStatus = "searching" | "quoting" | "awaiting" | "assigned" | "unfulfilled" | "cancelled";

export interface ProCard {
  id: number;
  name: string;
  photo: string | null;
  commune: string | null;
  trust_score: number | null;
  badges: string[];
  rating: number | null;
  reviews: number;
  completed?: number;
  experience?: string;
  distance_km: number | null;
  favorite: boolean;
  offers: { id: number; title: string; price: number | null; price_type: string; category: number }[];
  price_from: number | null;
  why: { label: string; detail: string }[];
  score?: number | null;
  bookable?: boolean;
  available_now?: boolean;
  trades?: string[];
}

export interface FlashRequest {
  id: number;
  status: RequestStatus;
  status_label: string;
  mode: "firm" | "quote";
  matching: Matching;
  matching_label: string;
  switches: number;
  category: { id: number; name: string };
  description: string;
  address: string;
  commune: string;
  scheduled_for: string;
  when_label: string;
  immediate: boolean;
  amount: number | null;
  amount_label: string;
  progress: { contacted: number; waiting: number; declined: number; no_answer: number; quotes: number };
  quotes?: { offer: number; amount: number; amount_label: string; message: string; status: string; distance_km: number | null; pro: { id: number; name: string; rating: number | null; reviews: number; trust_score: number | null } }[];
  target: { id: number; name: string } | null;
  assigned_to: { id: number; name: string; trust_score: number | null } | null;
  awaiting_reason: string | null;
  booking: number | null;
  close_reason: string;
  version: number;
  can_cancel: boolean;
  can_relaunch: boolean;
  can_switch: boolean;
}

export interface Suggestion {
  suggested: Matching;
  preselected: Matching;
  reason: string;
  note: string;
  remembered: boolean;
  immediate: boolean;
  available_pros: number;
}

export interface FlashOffer {
  id: number;
  request: number;
  mode: "firm" | "quote";
  direct: string;
  category: string;
  zone: string;
  when_label: string;
  amount_label: string;
  status: string;
  status_label: string;
  seconds_left: number;
  description: string;
  distance_km: string;
  client_reputation: { count: number; average: number | null };
  decline_reasons: { code: string; label: string }[];
  why: { label: string; detail: string }[];
  address?: string;
  client_name?: string;
  booking?: number;
  quote_amount: number | null;
}

/** Clé d'idempotence d'une intention (une par formulaire ouvert, ou déterministe pour une action précise). */
export function intentKey(prefix: string): string {
  const rand = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${rand}`.slice(0, 80);
}

/** Paramètres de requête sans valeurs vides. */
export function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const kept = Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== "" && v !== false);
  if (!kept.length) return "";
  return "?" + new URLSearchParams(kept.map(([k, v]) => [k, v === true ? "1" : String(v)])).toString();
}

/** Libellés et ton d'affichage d'un statut de demande. */
export const STATUS_TONE: Record<RequestStatus, "accent" | "warning" | "success" | "danger" | "gray"> = {
  searching: "accent", quoting: "warning", awaiting: "warning", assigned: "success", unfulfilled: "danger", cancelled: "gray",
};

export const MATCHING_LABEL: Record<Matching, string> = { auto: "Trouvez-moi un professionnel", direct: "Choisir mon professionnel" };

/** Le choix explicite du client l'emporte toujours sur le conseil du serveur. */
export function effectiveMatching(touched: Matching | null, suggestion: Suggestion | null): Matching {
  return touched ?? suggestion?.preselected ?? "auto";
}

/** Prix repris d'une offre choisie : fixe → montant ; sur devis → mode devis ; à l'heure → au client de proposer. */
export function priceFromOffer(offer: ProCard["offers"][number] | null | undefined): { amount: number | null; quote: boolean } {
  if (!offer) return { amount: null, quote: false };
  if (offer.price_type === "quote") return { amount: null, quote: true };
  return { amount: offer.price_type === "fixed" && offer.price != null ? offer.price : null, quote: false };
}
