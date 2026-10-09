import { post } from "./api";
import { maskPhone } from "./phone";

export { maskPhone };

/** Longueur du code de vérification (aligné sur OTPCode côté API et sur l'app Flutter). */
export const OTP_LENGTH = 6;
/** Délai minimal entre deux envois (secondes) — repli ; l'API renvoie la valeur réelle (`resend_in`). */
export const OTP_RESEND_SECONDS = 60;

/** Réponse d'un envoi de code : jamais le code lui-même. */
export interface OtpSent {
  sent: boolean;
  phone?: string;
  /** Durée de validité du code (secondes). */
  expires_in?: number;
  /** Délai avant de pouvoir demander un nouveau code (secondes). */
  resend_in?: number;
}

/** POST /auth/otp/request/ — envoie un code SMS au téléphone du compte connecté. En cas d'échec
 *  d'envoi l'API répond 502/503 avec un message clair (jamais de faux succès). */
export function requestOtp(): Promise<OtpSent> {
  return post<OtpSent>("/auth/otp/request/");
}

/** POST /auth/otp/verify/ — marque le compte comme vérifié (400 : code invalide/expiré, essais restants ;
 *  429 : essais épuisés). */
export async function verifyOtp(code: string): Promise<void> {
  await post<{ verified: boolean }>("/auth/otp/verify/", { code });
}

/** POST /auth/password-reset/request/ — code de récupération par SMS (202 identique que le numéro soit inscrit ou non). */
export function requestPasswordReset(phone: string): Promise<OtpSent> {
  return post<OtpSent>("/auth/password-reset/request/", { phone });
}

/** POST /auth/password-reset/confirm/ — nouveau mot de passe si le code est valide. */
export async function confirmPasswordReset(payload: { phone: string; code: string; password: string }): Promise<void> {
  await post<{ reset: boolean }>("/auth/password-reset/confirm/", payload);
}
