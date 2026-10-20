import {
  AsYouType,
  getCountries,
  getExampleNumber,
  getCountryCallingCode,
  parsePhoneNumberFromString,
  validatePhoneNumberLength,
  type CountryCode,
} from "libphonenumber-js/max";
import examples from "libphonenumber-js/mobile/examples";

/**
 * Téléphone : [drapeau ▼] + numéro NATIONAL. L'utilisateur ne saisit jamais l'indicatif ; le numéro est normalisé en E.164 avec
 * libphonenumber (même bibliothèque que Django `handy/phone.py`, qui revalide toujours).
 */

export type { CountryCode };

/** Pays de repli (Côte d'Ivoire). */
export const DEFAULT_COUNTRY: CountryCode = "CI";

export interface PhoneValue {
  country: CountryCode;
  /** Numéro national tel que saisi (espaces de mise en forme compris). */
  national: string;
}

export interface CountryInfo {
  code: CountryCode;
  name: string;
  dial: string;
  flag: string;
}

const NAMES = (() => {
  try {
    return new Intl.DisplayNames(["fr"], { type: "region" });
  } catch {
    return null;
  }
})();

/** Drapeau emoji d'un code pays (indicateurs régionaux Unicode). */
export function flagOf(code: string): string {
  return code.toUpperCase().replace(/./g, (c) => String.fromCodePoint(127397 + c.charCodeAt(0)));
}

export function countryName(code: CountryCode): string {
  return NAMES?.of(code) ?? code;
}

const fold = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9+ ]/g, " ").replace(/\s+/g, " ").trim();

let cache: CountryInfo[] | null = null;

/** Tous les pays (noms français, ordre alphabétique) avec drapeau et indicatif. */
export function allCountries(): CountryInfo[] {
  if (!cache) {
    const collator = new Intl.Collator("fr", { sensitivity: "base" });
    cache = getCountries()
      .map((code) => ({ code, name: countryName(code), dial: getCountryCallingCode(code), flag: flagOf(code) }))
      .sort((a, b) => collator.compare(a.name, b.name));
  }
  return cache;
}

export function isCountryCode(code: string | null | undefined): code is CountryCode {
  return Boolean(code) && (getCountries() as string[]).includes(String(code).toUpperCase());
}

/** Recherche par nom (sans accents), code ISO ou indicatif (« cote », « CI », « +225 », « 225 »). */
export function searchCountries(query: string, list: CountryInfo[] = allCountries()): CountryInfo[] {
  const q = fold(query);
  if (!q) return list;
  const digits = q.replace(/[^0-9]/g, "");
  const starts: CountryInfo[] = [];
  const contains: CountryInfo[] = [];
  for (const c of list) {
    const name = fold(c.name);
    if (digits && c.dial.startsWith(digits)) starts.push(c);
    else if (name.startsWith(q) || c.code.toLowerCase() === q || name.includes(` ${q}`)) starts.push(c);
    else if (name.includes(q)) contains.push(c);
  }
  return [...starts, ...contains];
}

/** Mise en forme du numéro national pendant la saisie (« 0700000000 » → « 07 00 00 00 00 »). */
export function formatNational(national: string, country: CountryCode): string {
  const digits = national.replace(/[^\d]/g, "");
  if (!digits) return "";
  if (country === "CI") return digits.slice(0, 10).replace(/(\d{2})(?=\d)/g, "$1 ");   // écriture usuelle : 07 00 00 00 00
  return new AsYouType(country).input(digits);
}

/** Exemple de numéro national affiché en indication (exemples officiels de libphonenumber ; écriture usuelle pour la Côte d'Ivoire). */
export function exampleNational(country: CountryCode): string {
  if (country === "CI") return "07 00 00 00 00";
  return getExampleNumber(country, examples)?.formatNational() ?? "";
}

/** E.164 d'un numéro VALIDE (« +2250700000000 »), sinon null. */
export function toE164(value: PhoneValue): string | null {
  const parsed = parsePhoneNumberFromString(value.national, value.country);
  return parsed && parsed.isValid() ? parsed.number : null;
}

/**
 * Numéro à RECHERCHER (connexion, récupération) : E.164 valide, sinon forme « +indicatif + chiffres » pour qu'un compte enregistré
 * avant libphonenumber (numéro hors norme) soit quand même retrouvé par le serveur. null si presque rien n'a été saisi.
 */
export function lookupE164(value: PhoneValue): string | null {
  const valid = toE164(value);
  if (valid) return valid;
  const digits = value.national.replace(/[^\d]/g, "");
  return digits.length >= 6 ? `+${getCountryCallingCode(value.country)}${digits}` : null;
}

/** Message d'erreur clair (ou null si le numéro est valide). Un champ vide renvoie `emptyMessage`. */
export function phoneError(value: PhoneValue, emptyMessage = "Saisissez votre numéro de téléphone."): string | null {
  const digits = value.national.replace(/[^\d]/g, "");
  if (!digits) return emptyMessage;
  if (toE164(value)) return null;
  const example = exampleNational(value.country);
  const tip = example ? ` Exemple : ${example}.` : "";
  const length = validatePhoneNumberLength(value.national, value.country);
  if (length === "TOO_SHORT") return `Numéro trop court pour ${countryName(value.country)}.${tip}`;
  if (length === "TOO_LONG") return `Numéro trop long pour ${countryName(value.country)}.${tip}`;
  return `Ce numéro n’est pas valide pour ${countryName(value.country)}. Vérifiez le pays et les chiffres.${tip}`;
}

/**
 * Numéro collé ou saisi avec son indicatif (« +33 6 12… », « 00225 07… ») : pays et numéro national correspondants, sinon null.
 * Permet de coller un numéro complet sans avoir à changer le pays à la main.
 */
export function splitInternational(raw: string): PhoneValue | null {
  const v = raw.trim().replace(/^00/, "+");
  if (!v.startsWith("+")) return null;
  const parsed = parsePhoneNumberFromString(v);
  if (!parsed?.country) return null;
  return { country: parsed.country, national: parsed.country === "CI" ? formatNational(parsed.nationalNumber, "CI") : parsed.formatNational() };
}

/** Valeur de départ d'un champ à partir d'un numéro enregistré (E.164). */
export function fromE164(e164: string | null | undefined, fallback: CountryCode = DEFAULT_COUNTRY): PhoneValue {
  return (e164 && splitInternational(e164)) || { country: fallback, national: "" };
}

/** « +225 07 00 00 00 00 » pour l'affichage (le numéro brut sinon). */
export function displayPhone(e164: string | null | undefined): string {
  if (!e164) return "";
  const parsed = parsePhoneNumberFromString(e164);
  if (!parsed) return e164;
  return parsed.country === "CI" ? `+225 ${formatNational(parsed.nationalNumber, "CI")}` : parsed.formatInternational();
}

/** « +2250700000002 » -> « +225 •• •• •• 02 » : le numéro complet n'est jamais ré-affiché. */
export function maskPhone(phone: string): string {
  const p = phone.replace(/\s+/g, "");
  if (p.length < 6) return p;
  const parsed = parsePhoneNumberFromString(p);
  const prefix = parsed ? `+${parsed.countryCallingCode} ` : p.startsWith("+") ? `${p.slice(0, 4)} ` : "";
  return `${prefix}•• •• •• ${p.slice(-2)}`;
}
