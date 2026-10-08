"use client";
import { createContext, useContext, useMemo, type ReactNode } from "react";
import { resultsOf } from "@/lib/public";
import { resolveTrades, type ResolvedTrade } from "@/lib/trades";
import { usePublicData } from "@/lib/usePublic";
import type {
  Category,
  FeaturedArtisansResponse,
  Paginated,
  PublicReviewsResponse,
  PublicStats,
  Service,
  SubscriptionPlan,
} from "@/lib/types";

/**
 * Données publiques de la landing.
 * Le Server Component (app/page.tsx) les pré-charge en parallèle (ISR) et les
 * transmet ici ; toute ressource arrivée `null` (API lente/indisponible au
 * rendu serveur) est rechargée UNE seule fois côté client et partagée par
 * toutes les sections (Hero, Métiers, Urgences… lisent les mêmes catégories).
 * `services`, `featured` et `stats` sont en plus rafraîchis au montage : le HTML
 * ISR peut être ancien (URLs média signées expirées, compteur « en ligne »
 * figé) ; la donnée serveur reste affichée d'ici là et est conservée en cas
 * d'échec.
 */
export interface LandingInitial {
  stats: PublicStats | null;
  categories: Paginated<Category> | Category[] | null;
  featured: FeaturedArtisansResponse | null;
  reviews: PublicReviewsResponse | null;
  services: Paginated<Service> | Service[] | null;
  plans: Paginated<SubscriptionPlan> | SubscriptionPlan[] | null;
}

export type LandingKey = keyof LandingInitial;
export type LandingEndpoints = Record<LandingKey, string>;

export interface Resource<T> {
  /** Donnée réelle (serveur ou client) ; null tant qu'indisponible. */
  data: T | null;
  /** Vrai uniquement quand aucune donnée n'est encore affichable (squelette). */
  loading: boolean;
  /** Vrai quand le chargement a échoué et qu'aucune donnée n'est affichable. */
  error: boolean;
  reload: () => void;
}

type LandingValue = { [K in LandingKey]: Resource<NonNullable<LandingInitial[K]>> };

const Ctx = createContext<LandingValue | null>(null);

function useResource<T>(path: string, initial: T | null, refreshOnMount = false): Resource<T> {
  const state = usePublicData<T>(path, initial, { refreshOnMount });
  // Si un rafraîchissement client échoue, on conserve la donnée serveur réelle
  // plutôt que de l'effacer.
  const data = state.data ?? initial ?? null;
  return {
    data,
    loading: data === null && state.loading,
    error: data === null && !state.loading && state.error,
    reload: state.reload,
  };
}

export function LandingDataProvider({
  endpoints,
  initial,
  children,
}: {
  endpoints: LandingEndpoints;
  initial: LandingInitial;
  children: ReactNode;
}) {
  const stats = useResource(endpoints.stats, initial.stats, true);
  const categories = useResource(endpoints.categories, initial.categories);
  const featured = useResource(endpoints.featured, initial.featured, true);
  const reviews = useResource(endpoints.reviews, initial.reviews);
  const services = useResource(endpoints.services, initial.services, true);
  const plans = useResource(endpoints.plans, initial.plans);

  return <Ctx.Provider value={{ stats, categories, featured, reviews, services, plans }}>{children}</Ctx.Provider>;
}

export function useLanding<K extends LandingKey>(key: K): LandingValue[K] {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useLanding doit être utilisé dans <LandingDataProvider>");
  return ctx[key];
}

/** Familles de métiers réellement présentes (adossées aux catégories actives). */
export function useTrades(): Omit<Resource<Category[]>, "data"> & { trades: ResolvedTrade[] } {
  const { data, loading, error, reload } = useLanding("categories");
  const trades = useMemo(() => (data ? resolveTrades(resultsOf(data)) : []), [data]);
  return { trades, loading, error, reload };
}

/** Familles triées par nombre de prestations (ordre éditorial conservé à égalité). */
export function byServicesCount(trades: ResolvedTrade[]): ResolvedTrade[] {
  return [...trades].sort((a, b) => (b.servicesCount ?? -1) - (a.servicesCount ?? -1));
}
