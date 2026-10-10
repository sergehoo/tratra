import { ApiError } from "./api";
import { deleteLocal, readLocal, writeLocal } from "./localVault";

/** Activité en cours telle que le serveur la décrit (GET /me/activities/) : jamais de coordonnées ni d'adresse complète. */
export interface Activity {
  kind: "booking" | "mission" | "business_request";
  id: number;
  role: "client" | "handyman" | "requester";
  status: string;
  status_label: string;
  version: number | null;
  title: string;
  counterpart: string;
  booking_date: string | null;
  city: string | null;
  updated_at: string | null;
  active: boolean;
  deeplink: string;
  resume_label: string;
}

export interface ActivitiesResponse {
  server_time: string;
  has_active: boolean;
  primary: Activity | null;
  activities: Activity[];
  changes?: Activity[];
}

/** Page du site pour une activité (lien profond `tratra://mission/12` → `/dashboard/provider/missions/12`). */
export function activityHref(a: Pick<Activity, "kind" | "id">): string {
  switch (a.kind) {
    case "mission":
      return `/dashboard/provider/missions/${a.id}`;
    case "business_request":
      return `/dashboard/business/requests/${a.id}`;
    default:
      return `/dashboard/bookings/${a.id}`;
  }
}

// ── Erreurs typées du serveur ───────────────────────────────────────────────────────────────────────────────────────

function code(e: unknown): string | null {
  const data = e instanceof ApiError ? (e.data as { code?: unknown } | null) : null;
  return data && typeof data.code === "string" ? data.code : null;
}

/** Écriture concurrente : l'objet a été modifié ailleurs (autre appareil, autre acteur) depuis le dernier chargement. */
export const isVersionConflict = (e: unknown): boolean => e instanceof ApiError && e.status === 409 && code(e) === "version_conflict";

/** Réservation identique déjà créée (double clic, renvoi) : identifiant de la réservation existante. */
export function duplicateBookingId(e: unknown): number | null {
  if (!(e instanceof ApiError) || e.status !== 409 || code(e) !== "duplicate_booking") return null;
  const id = (e.data as { existing_id?: unknown }).existing_id;
  return typeof id === "number" ? id : null;
}

/** Panne réseau ou serveur injoignable : RIEN n'a été confirmé (jamais présenté comme réussi). */
export const isNetworkFailure = (e: unknown): boolean => !(e instanceof ApiError) || e.status >= 502;

// ── Clés d'idempotence et brouillons ────────────────────────────────────────────────────────────────────────────────

export function randomHex(bytes = 12): string {
  const a = new Uint8Array(bytes);
  (typeof crypto !== "undefined" ? crypto : undefined)?.getRandomValues?.(a);
  return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Empreinte stable (FNV-1a 32 bits) : identique d'un chargement à l'autre. */
export function fingerprint(input: string): string {
  let h = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(input)) {
    h = Math.imul(h ^ byte, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}

export interface BookingDraft {
  base: string; // identifiant du brouillon (une intention)
  booking_date: string;
  address: string;
  city: string;
  postal_code: string;
  description: string;
  updated_at: string;
}

const DRAFT_MAX_AGE_MS = 7 * 24 * 3600 * 1000;
const draftName = (serviceId: number | string) => `draft.${serviceId}`;

export const draftIsEmpty = (d: Pick<BookingDraft, "address" | "city" | "postal_code" | "description">): boolean =>
  !(d.address.trim() || d.city.trim() || d.postal_code.trim() || d.description.trim());

/**
 * Clé d'idempotence = identifiant du brouillon + empreinte du CONTENU : renvoyer la même demande (double clic, après un
 * plantage) réutilise la même clé → le serveur retrouve la réservation déjà créée ; modifier un champ change l'empreinte
 * (nouvelle intention, nouvelle clé). Aucun doublon dans les deux cas. Format accepté par le serveur : [A-Za-z0-9_-:.]{8,80}.
 */
export function bookingIdempotencyKey(serviceId: number | string, d: BookingDraft): string {
  const content = [serviceId, d.booking_date, d.address.trim(), d.city.trim(), d.postal_code.trim(), d.description.trim()].join("\u0001");
  return `bk-${d.base}-${fingerprint(content)}`;
}

export function loadDraft(userId: number | string, serviceId: number | string): BookingDraft | null {
  const d = readLocal<BookingDraft>(userId, draftName(serviceId));
  if (!d) return null;
  if (Date.now() - Date.parse(d.updated_at) > DRAFT_MAX_AGE_MS) {
    deleteLocal(userId, draftName(serviceId));
    return null;
  }
  return d;
}

/** Un brouillon vide n'est pas conservé. */
export function saveDraft(userId: number | string, serviceId: number | string, d: BookingDraft): void {
  if (draftIsEmpty(d)) deleteLocal(userId, draftName(serviceId));
  else writeLocal(userId, draftName(serviceId), d);
}

export const discardDraft = (userId: number | string, serviceId: number | string): void => deleteLocal(userId, draftName(serviceId));
