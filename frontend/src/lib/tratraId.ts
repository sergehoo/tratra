/** Tratra ID : types de l'API (badge, vérification publique, QR de mission) — mêmes charges utiles que le mobile. */
import type { PublicBadge } from "./trust";

export interface IdHolder {
  display_name: string;
  photo: string | null;
  trades: string[];
  commune: string;
  badges: PublicBadge[];
  kyc_verified_on: string | null;
}

export interface MyTratraId {
  tratra_id: string;
  issued_at: string;
  status: "active" | "suspended";
  valid: boolean;
  message: string;
  verify_url: string;
  /** Image PNG du QR permanent (data URL). */
  qr: string;
  holder: IdHolder;
  pdf_available: boolean;
}

export interface PublicVerification {
  valid: boolean;
  status: "active" | "revoked" | "unknown";
  tratra_id: string;
  message: string;
  holder?: IdHolder;
  checked_at?: string;
}

export interface MissionPass {
  token: string;
  url: string;
  qr: string;
  expires_at: string;
  ttl_seconds: number;
  booking_id: number;
}

export interface PassResult {
  valid: true;
  matches_booking: true;
  booking_id: number;
  service: string;
  booking_date: string;
  verified_at: string;
  tratra_id: string;
  holder: IdHolder;
  message: string;
}

export interface BookingIdentity {
  booking_id: number;
  verified: boolean;
  verified_at: string | null;
  tratra_id: string | null;
}

/** Extrait le jeton d'un QR de mission collé (URL complète ou jeton seul). */
export function tokenFromInput(raw: string): string {
  const v = raw.trim();
  return v.includes("/") ? v.replace(/\/+$/, "").split("/").pop() ?? "" : v;
}
