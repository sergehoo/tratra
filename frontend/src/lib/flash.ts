/**
 * Tratra Flash & Hybrid Matching (site) — même API que l'application : une seule commande, deux modes.
 *  - « Trouvez-moi un professionnel » (auto) : Smart Dispatch ;
 *  - « Choisir mon professionnel » (direct) : le client choisit sur profils, avis et badges.
 * Les écritures envoient une `Idempotency-Key` stable par intention : un double clic ne crée ni deux demandes, ni deux bascules.
 */
import { apiJson, get } from "./api";

export * from "./flashModel";
import type { FlashOffer, FlashRequest, Matching, ProCard, Suggestion } from "./flashModel";
import { query } from "./flashModel";

const post = <T>(path: string, body: unknown, key?: string) =>
  apiJson<T>(path, { method: "POST", body: JSON.stringify(body ?? {}), headers: key ? { "Idempotency-Key": key } : undefined });

// ── Client ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
export const listRequests = () => get<{ results: FlashRequest[] }>("/flash/requests/");
export const getRequest = (id: number) => get<FlashRequest>(`/flash/requests/${id}/`);
export const createRequest = (body: Record<string, unknown>, key: string) => post<FlashRequest>("/flash/requests/", body, key);
export const cancelRequest = (id: number) => post<FlashRequest>(`/flash/requests/${id}/cancel/`, {}, `flash-cancel-${id}`);
export const relaunchRequest = (id: number, key: string) => post<FlashRequest>(`/flash/requests/${id}/relaunch/`, {}, key);
export const chooseQuote = (id: number, offer: number) => post<FlashRequest>(`/flash/requests/${id}/quotes/${offer}/accept/`, {}, `flash-choose-${id}-${offer}`);
export const switchMode = (id: number, to: Matching, version: number, target?: number) =>
  post<FlashRequest>(`/flash/requests/${id}/switch/`, { to, confirm: true, expected_version: version, ...(target ? { target } : {}) },
    `flash-switch-${id}-${to}-${target ?? 0}-${version}`);
export const suggest = (p: { category: number; when?: string | null; quote?: boolean; lat?: number | null; lng?: number | null; commune?: string }) =>
  get<Suggestion>(`/flash/suggest/${query({ category: p.category, when: p.when, mode: p.quote ? "quote" : null, lat: p.lat, lng: p.lng, commune: p.commune })}`);
export const listPros = (p: { category: number; when?: string | null; lat?: number | null; lng?: number | null; commune?: string; sort?: string; minRating?: number | null; badge?: string; favorites?: boolean }) =>
  get<{ count: number; results: ProCard[] }>(`/flash/pros/${query({ category: p.category, when: p.when, lat: p.lat, lng: p.lng, commune: p.commune, sort: p.sort, min_rating: p.minRating, badge: p.badge, favorites: p.favorites })}`);
export const listFavorites = () => get<{ results: ProCard[] }>("/me/favorites/");
export const addFavorite = (handyman: number) => post<{ results: ProCard[] }>("/me/favorites/", { handyman }, `favorite-add-${handyman}`);
export const removeFavorite = (handyman: number) => apiJson<{ results: ProCard[] }>(`/me/favorites/${handyman}/`, { method: "DELETE" });

// ── Professionnel ──────────────────────────────────────────────────────────────────────────────────────────────────────
export const getOffer = (id: number) => get<FlashOffer>(`/flash/offers/${id}/`);
export const listOffers = () => get<{ results: FlashOffer[] }>("/flash/offers/");
export const acceptOffer = (id: number) => post<FlashOffer>(`/flash/offers/${id}/accept/`, {}, `flash-accept-${id}`);
export const declineOffer = (id: number, reason = "") => post<FlashOffer>(`/flash/offers/${id}/decline/`, { reason }, `flash-decline-${id}`);
export const quoteOffer = (id: number, amount: number, message: string) =>
  post<FlashOffer>(`/flash/offers/${id}/quote/`, { amount, message }, `flash-quote-${id}-${amount}`);
