"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";

/**
 * État de la recherche publique, entièrement porté par l'URL (lien partageable,
 * retour/avance du navigateur cohérents). Toute valeur invalide est ignorée.
 */

export type SortKey = "recent" | "price_asc" | "price_desc" | "rating" | "trust";
export type BadgeKey = "" | "EXPERT" | "SUR";
export type PriceTypeKey = "hourly" | "fixed" | "quote";

export const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: "recent", label: "Plus récents" },
  { value: "price_asc", label: "Prix croissant" },
  { value: "price_desc", label: "Prix décroissant" },
  { value: "rating", label: "Mieux notés" },
  { value: "trust", label: "Score de confiance" },
];

/** Badge Tratra Trust filtrable (le badge « Vérifié » est déjà couvert par « Profils vérifiés »). */
export const BADGE_OPTIONS: { value: BadgeKey; label: string }[] = [
  { value: "", label: "Tous" },
  { value: "EXPERT", label: "Expert" },
  { value: "SUR", label: "Sûr" },
];

export const PRICE_TYPE_OPTIONS: { value: PriceTypeKey; label: string }[] = [
  { value: "hourly", label: "À l'heure" },
  { value: "fixed", label: "Forfait" },
  { value: "quote", label: "Sur devis" },
];

export const RADIUS_OPTIONS = [5, 10, 15, 25, 50] as const;
export const DEFAULT_RADIUS = 15;
export const MAX_RADIUS = 50;
export const PAGE_SIZE = 12;

export interface SearchState {
  q: string;
  /** Slugs de catégories réelles (paramètre `metier`, séparés par des virgules). */
  metier: string[];
  commune: string;
  online: boolean;
  verified: boolean;
  badge: BadgeKey;
  sort: SortKey;
  priceType: PriceTypeKey | "";
  minPrice: string;
  maxPrice: string;
  lat: number | null;
  lng: number | null;
  radius: number;
  /** Identifiant utilisateur de l'artisan (prestations d'un seul artisan). */
  handyman: string;
}

export const EMPTY_SEARCH: SearchState = {
  q: "",
  metier: [],
  commune: "",
  online: false,
  verified: false,
  badge: "",
  sort: "recent",
  priceType: "",
  minPrice: "",
  maxPrice: "",
  lat: null,
  lng: null,
  radius: DEFAULT_RADIUS,
  handyman: "",
};

const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function positiveInt(value: string | null, maxLength = 9): string {
  const v = (value ?? "").trim();
  if (!/^\d+$/.test(v) || v.length > maxLength) return "";
  const n = Number(v);
  return n > 0 ? String(n) : "";
}

function coordinate(value: string | null, limit: number): number | null {
  if (value === null || value.trim() === "") return null;
  const n = Number(value);
  return Number.isFinite(n) && Math.abs(n) <= limit ? n : null;
}

/** Arrondi à ~100 m : suffisant pour la recherche, plus respectueux de la vie privée. */
export function roundCoord(n: number): number {
  return Math.round(n * 1000) / 1000;
}

export function parseSearch(sp: { get(name: string): string | null }): SearchState {
  const sort = sp.get("sort");
  const priceType = sp.get("price_type");
  const radius = Number(sp.get("radius"));
  let lat = coordinate(sp.get("lat"), 90);
  let lng = coordinate(sp.get("lng"), 180);
  if (lat === null || lng === null) {
    lat = null;
    lng = null;
  }
  const metier = Array.from(
    new Set(
      (sp.get("metier") ?? "")
        .split(",")
        .map((s) => s.trim().toLowerCase())
        .filter((s) => SLUG_RE.test(s)),
    ),
  ).slice(0, 30);

  return {
    q: (sp.get("q") ?? "").trim().slice(0, 100),
    metier,
    commune: (sp.get("commune") ?? "").trim().slice(0, 60),
    online: sp.get("online") === "1",
    verified: sp.get("verified") === "1",
    badge: sp.get("badge") === "EXPERT" || sp.get("badge") === "SUR" ? (sp.get("badge") as BadgeKey) : "",
    sort: SORT_OPTIONS.some((o) => o.value === sort) ? (sort as SortKey) : "recent",
    priceType: PRICE_TYPE_OPTIONS.some((o) => o.value === priceType) ? (priceType as PriceTypeKey) : "",
    minPrice: positiveInt(sp.get("min_price")),
    maxPrice: positiveInt(sp.get("max_price")),
    lat,
    lng,
    radius: (RADIUS_OPTIONS as readonly number[]).includes(radius) ? radius : DEFAULT_RADIUS,
    handyman: positiveInt(sp.get("handyman"), 12),
  };
}

/** Sérialisation canonique (ordre stable, valeurs par défaut omises). */
export function serializeSearch(s: SearchState): string {
  const sp = new URLSearchParams();
  if (s.q) sp.set("q", s.q);
  if (s.metier.length) sp.set("metier", s.metier.join(","));
  if (s.commune) sp.set("commune", s.commune);
  if (s.online) sp.set("online", "1");
  if (s.verified) sp.set("verified", "1");
  if (s.badge) sp.set("badge", s.badge);
  if (s.priceType) sp.set("price_type", s.priceType);
  if (s.minPrice) sp.set("min_price", s.minPrice);
  if (s.maxPrice) sp.set("max_price", s.maxPrice);
  if (s.lat !== null && s.lng !== null) {
    sp.set("lat", String(roundCoord(s.lat)));
    sp.set("lng", String(roundCoord(s.lng)));
    if (s.radius !== DEFAULT_RADIUS) sp.set("radius", String(s.radius));
  }
  if (s.sort !== "recent") sp.set("sort", s.sort);
  if (s.handyman) sp.set("handyman", s.handyman);
  // Virgules lisibles dans l'URL (« metier=plomberie,electricite »).
  return sp.toString().replace(/%2C/gi, ",");
}

export function isLocated(s: SearchState): s is SearchState & { lat: number; lng: number } {
  return s.lat !== null && s.lng !== null;
}

export function useSearchState() {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const current = searchParams.toString();
  const state = useMemo(() => parseSearch(new URLSearchParams(current)), [current]);

  // Dernière URL demandée : deux mises à jour rapprochées (avant que le routeur
  // n'ait validé la première) se cumulent au lieu de s'écraser.
  const latest = useRef(current);
  useEffect(() => {
    latest.current = current;
  }, [current]);

  const navigate = useCallback(
    (next: SearchState) => {
      const target = serializeSearch(next);
      if (target === serializeSearch(parseSearch(new URLSearchParams(latest.current)))) return;
      latest.current = target;
      // history.replaceState natif : Next 14.2 le synchronise avec
      // useSearchParams (comme router.replace avec scroll: false) mais SANS
      // aller-retour serveur (payload RSC) à chaque filtre : réponse immédiate,
      // y compris sur réseau mobile lent. Retour/avance du navigateur inchangés.
      window.history.replaceState(null, "", target ? `${pathname}?${target}` : pathname);
    },
    [pathname],
  );

  const update = useCallback(
    (patch: Partial<SearchState>) => {
      navigate({ ...parseSearch(new URLSearchParams(latest.current)), ...patch });
    },
    [navigate],
  );

  const reset = useCallback((keep?: Partial<SearchState>) => navigate({ ...EMPTY_SEARCH, ...keep }), [navigate]);

  return { state, update, reset };
}

/**
 * Champ texte « brouillon » synchronisé avec l'URL : la saisie est appliquée
 * après `delay` ms d'inactivité (ou immédiatement via `flush`), et toute
 * modification externe de l'URL (retour arrière, réinitialisation) est reflétée.
 */
export function useDebouncedDraft(value: string, commit: (v: string) => void, delay = 350) {
  const [draft, setDraft] = useState(value);
  const committed = useRef(value);
  const commitRef = useRef(commit);
  useEffect(() => {
    commitRef.current = commit;
  }, [commit]);

  useEffect(() => {
    if (value !== committed.current) {
      committed.current = value;
      setDraft(value);
    }
  }, [value]);

  useEffect(() => {
    const normalized = draft.trim();
    if (normalized === committed.current) return;
    const timer = setTimeout(() => {
      committed.current = normalized;
      commitRef.current(normalized);
    }, delay);
    return () => clearTimeout(timer);
  }, [draft, delay]);

  const flush = useCallback(() => {
    const normalized = draft.trim();
    if (normalized === committed.current) return;
    committed.current = normalized;
    commitRef.current(normalized);
  }, [draft]);

  return [draft, setDraft, flush] as const;
}
