import { API_BASE } from "./config";
import { DEFAULT_COUNTRY, isCountryCode, type CountryCode } from "./phone";

/**
 * Pays présélectionné pour la saisie du téléphone, dans cet ordre :
 *   1. préférence enregistrée (dernier pays choisi sur cet appareil) ;
 *   2. région de l'appareil (langue du navigateur, ex. « fr-CI ») — un navigateur n'expose pas la carte SIM ;
 *   3. pays de l'adresse IP, SEULEMENT si le serveur le connaît déjà (en-tête du proxy) — Tratra ne géolocalise pas ;
 *   4. Côte d'Ivoire.
 */
const KEY = "tratra.phone.country";

export function savedCountry(): CountryCode | null {
  try {
    const v = window.localStorage.getItem(KEY);
    return isCountryCode(v) ? (v.toUpperCase() as CountryCode) : null;
  } catch {
    return null;
  }
}

export function rememberCountry(code: CountryCode): void {
  try {
    window.localStorage.setItem(KEY, code);
  } catch {
    /* stockage indisponible (navigation privée) : sans conséquence */
  }
}

export function deviceCountry(languages: readonly string[] = typeof navigator === "undefined" ? [] : navigator.languages ?? [navigator.language]): CountryCode | null {
  for (const lang of languages) {
    const region = lang?.split(/[-_]/)[1];
    if (region && region.length === 2 && isCountryCode(region)) return region.toUpperCase() as CountryCode;
  }
  return null;
}

let serverGuess: Promise<CountryCode | null> | null = null;

async function ipCountry(): Promise<CountryCode | null> {
  serverGuess ??= fetch(`${API_BASE}/phone/defaults/`, { headers: { Accept: "application/json" } })
    .then((r) => (r.ok ? r.json() : null))
    .then((d: { ip_region?: string | null; default_region?: string } | null) => {
      if (isCountryCode(d?.ip_region)) return d!.ip_region!.toUpperCase() as CountryCode;
      return isCountryCode(d?.default_region) ? (d!.default_region!.toUpperCase() as CountryCode) : null;
    })
    .catch(() => null);
  return serverGuess;
}

export async function resolveDefaultCountry(): Promise<CountryCode> {
  return savedCountry() ?? deviceCountry() ?? (await ipCountry()) ?? DEFAULT_COUNTRY;
}
