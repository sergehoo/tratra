// Paiement en ESPÈCES d'une réservation : déclaré par une partie, confirmé par l'AUTRE, historique, justificatif facultatif.
// Ce n'est jamais un encaissement vérifié par un prestataire de paiement (`verification` vaut toujours « manual » ici) — voir
// docs/paiements.md. Les règles restent côté serveur ; cet écran affiche ce que le serveur renvoie.
import { apiJson, get, upload } from "@/lib/api";
import { randomHex } from "@/lib/continuity";

export interface CashDeclaration {
  id: number; amount: string; paid_on: string; note: string; status: "declared" | "confirmed" | "rejected";
  declared_by_role: "client" | "artisan"; mine: boolean; can_respond: boolean; rejection_reason: string;
  declared_at: string; responded_at: string | null; receipt: { url: string } | null;
}
export type CashState = "none" | "awaiting_confirmation" | "partial" | "paid" | "contested";
export interface CashSummary {
  method: "cash"; currency: string; state: CashState; verification: "manual";
  due: string | null; confirmed: string; declared: string; remaining: string | null;
  my_role: "client" | "artisan" | null; can_declare: boolean; note: string; history: CashDeclaration[];
}
export interface BookingPayment {
  booking_id: number; booking_status: string;
  payment: { id: number; method: string; status: string; amount: string; currency: string; verification: string; provider_verified_at: string | null } | null;
  cash: CashSummary | null;
}

export const CASH_STATE_FR: Record<CashState, string> = {
  none: "Aucun paiement déclaré", awaiting_confirmation: "À confirmer", partial: "Réglé en partie", paid: "Réglé en espèces", contested: "Contesté",
};
export const CASH_STATUS_FR: Record<CashDeclaration["status"], string> = { declared: "À confirmer", confirmed: "Confirmé", rejected: "Contesté" };

export const cashApi = {
  get: (bookingId: number | string) => get<BookingPayment>(`/bookings/${bookingId}/payment/`),
  /** Déclaration (justificatif facultatif) : `key` identique = même intention rejouée sans doublon. */
  declare: (bookingId: number | string, fields: Record<string, string>, receipt: File | null, key: string) => {
    const f = new FormData();
    for (const [k, v] of Object.entries(fields)) if (v !== "") f.set(k, v);
    if (receipt) f.set("receipt", receipt);
    return upload<{ declaration: CashDeclaration; cash: CashSummary }>(`/bookings/${bookingId}/payment/cash/`, f, true, { "Idempotency-Key": key });
  },
  respond: (declarationId: number, confirm: boolean, reason = "") =>
    apiJson<{ declaration: CashDeclaration; cash: CashSummary }>(`/payments/cash/${declarationId}/respond/`, { method: "POST", body: JSON.stringify({ confirm, reason }) }),
  newKey: () => `cash-${randomHex(10)}`,
};
