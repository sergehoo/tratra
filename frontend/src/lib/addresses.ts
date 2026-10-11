import { ApiError, del, get, patch, post } from "./api";

export interface Address {
  id: number;
  label: string;
  country: string;
  city: string;
  commune: string;
  street: string;
  complement: string;
  latitude: number | null;
  longitude: number | null;
  coords_source: "" | "manual" | "geocoder" | "map" | "device";
  is_primary: boolean;
  is_favorite: boolean;
}

export interface AddressForm {
  label: string;
  country: string;
  city: string;
  commune: string;
  street: string;
  complement: string;
  latitude: number | null;
  longitude: number | null;
  coords_source: Address["coords_source"];
  location_consent?: boolean;
}

export interface Suggestion {
  label: string;
  street: string;
  commune: string;
  city: string;
  country: string;
  latitude: number;
  longitude: number;
}

export const EMPTY_ADDRESS: AddressForm = { label: "", country: "Côte d’Ivoire", city: "", commune: "", street: "", complement: "", latitude: null, longitude: null, coords_source: "" };

export const listAddresses = () => get<{ results: Address[]; complete: boolean; max: number }>("/me/addresses/");
export const createAddress = (body: AddressForm & { is_primary?: boolean }) => post<Address>("/me/addresses/", body);
export const updateAddress = (id: number, body: Partial<AddressForm> & { is_favorite?: boolean }) => patch<Address>(`/me/addresses/${id}/`, body);
export const deleteAddress = (id: number) => del(`/me/addresses/${id}/`);
export const makePrimary = (id: number) => post<Address>(`/me/addresses/${id}/primary/`);

/** Recherche d'adresse (fournisseur côté serveur, mis en cache). `manual: true` = fournisseur indisponible → saisie manuelle. */
export async function searchAddress(q: string): Promise<{ results: Suggestion[]; manual: boolean }> {
  try {
    return { results: (await get<{ results: Suggestion[] }>(`/geo/search/?q=${encodeURIComponent(q)}`)).results, manual: false };
  } catch (e) {
    if (e instanceof ApiError && (e.status === 503 || e.status === 429)) return { results: [], manual: true };
    throw e;
  }
}

/** Géocodage inverse d'un point : n'est appelé qu'après une action explicite de l'utilisateur (`consent=true`). */
export async function reverseAddress(lat: number, lng: number): Promise<Suggestion | null> {
  try {
    const r = await get<{ result: Suggestion | null }>(`/geo/reverse/?lat=${lat}&lng=${lng}&consent=true`);
    return r.result;
  } catch (e) {
    if (e instanceof ApiError && (e.status === 503 || e.status === 429)) return null;
    throw e;
  }
}

/** Position de l'appareil : UNE lecture ponctuelle après consentement (jamais de suivi continu). */
export function currentPosition(): Promise<{ lat: number; lng: number }> {
  return new Promise((resolve, reject) => {
    if (typeof navigator === "undefined" || !navigator.geolocation) return reject(new Error("La géolocalisation n’est pas disponible sur cet appareil."));
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
      (err) => reject(new Error(err.code === err.PERMISSION_DENIED ? "Position refusée : saisissez l’adresse manuellement." : "Position indisponible : saisissez l’adresse manuellement.")),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
    );
  });
}
