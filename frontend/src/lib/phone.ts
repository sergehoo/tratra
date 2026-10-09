/** Indicatif proposé par défaut (Côte d'Ivoire). */
export const DEFAULT_COUNTRY_PREFIX = "+225";

/**
 * Numéro au format E.164 (« +2250700000010 »), ou null s'il est invalide.
 * « 07 00 00 00 10 » (10 chiffres) reçoit +225 ; « 00… » devient « +… » ; sans « + » ni 10 chiffres,
 * le numéro est supposé commencer par son indicatif. Même règle que l'API (handy/sms.py).
 */
export function normalizePhone(raw: string): string | null {
  let v = raw.replace(/[\s.\-()]/g, "");
  if (v.startsWith("00")) v = `+${v.slice(2)}`;
  if (!v.startsWith("+")) v = `${v.length === 10 ? DEFAULT_COUNTRY_PREFIX : "+"}${v}`;
  return /^\+[1-9]\d{7,14}$/.test(v) ? v : null;
}

/** « +2250700000002 » -> « +225 •• •• •• 02 » : le numéro complet n'est jamais ré-affiché. */
export function maskPhone(phone: string): string {
  const p = phone.replace(/\s+/g, "");
  if (p.length < 6) return p;
  const prefix = p.startsWith("+") ? `${p.slice(0, 4)} ` : "";
  return `${prefix}•• •• •• ${p.slice(-2)}`;
}
