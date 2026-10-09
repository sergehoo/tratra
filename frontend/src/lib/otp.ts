import { post } from "./api";

/** Longueur du code de vérification (aligné sur OTPCode côté API et sur l'app Flutter). */
export const OTP_LENGTH = 6;
/** Délai minimal entre deux envois (secondes) — identique à l'app Flutter. */
export const OTP_RESEND_SECONDS = 60;

/** POST /auth/otp/request/ — envoie un code au téléphone du compte connecté. Le code éventuellement
 *  renvoyé en développement n'est jamais lu ni affiché. */
export async function requestOtp(): Promise<void> {
  await post<unknown>("/auth/otp/request/");
}

/** POST /auth/otp/verify/ — marque le compte comme vérifié (400 « Code invalide ou expiré. »). */
export async function verifyOtp(code: string): Promise<void> {
  await post<{ verified: boolean }>("/auth/otp/verify/", { code });
}

/** « +2250700000002 » -> « +225 •• •• •• 02 » : le numéro complet n'est jamais affiché. */
export function maskPhone(phone: string): string {
  const p = phone.replace(/\s+/g, "");
  if (p.length < 6) return p;
  const prefix = p.startsWith("+") ? `${p.slice(0, 4)} ` : "";
  return `${prefix}•• •• •• ${p.slice(-2)}`;
}
