import { Card } from "@/components/ds/Card";
import { CONTAINER, Eyebrow } from "@/components/ds/layout";
import { Skeleton } from "@/components/ds/Skeleton";
import { CardGridSkeleton } from "@/components/market/Skeletons";

/**
 * Éléments statiques de la page de recherche, utilisables côté serveur :
 * le squelette (fallback Suspense) contient déjà le vrai titre H1 pour le SEO.
 * Les gabarits ci-dessous sont partagés avec la page réelle (SearchHero,
 * SearchClient) pour que le passage squelette -> contenu ne déplace rien.
 */

export const RESULTS_GRID = "grid gap-5 sm:grid-cols-2 xl:grid-cols-3";

/** Conteneur du bandeau : mêmes gouttières que l'en-tête du site. */
export const HERO_SHELL = `${CONTAINER} relative pb-7 pt-8 sm:pt-12 lg:pb-9`;

/** Carte blanche de recherche posée sur le bandeau vert. */
export const SEARCH_CARD = "mt-5 rounded-card bg-white p-2 shadow-strong ring-1 ring-white/20 sm:mt-8";

/** Zone des résultats sous le bandeau (filtres + grille). */
export const RESULTS_SHELL = `${CONTAINER} pb-20 pt-8 lg:pt-10`;
export const RESULTS_LAYOUT = "lg:grid lg:grid-cols-[288px_minmax(0,1fr)] lg:gap-8";

/**
 * Fond décoratif du bandeau (vert de marque, halo jaune, trame de points).
 * Vert foncé au centre et halo jaune discret : le titre jaune garde ≥ 3:1 et
 * l'étiquette en 11 px ≥ 4,5:1 (WCAG AA), y compris sur mobile où le halo
 * passe derrière le titre.
 */
export function HeroBackdrop() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
      <div className="absolute inset-0 bg-gradient-to-br from-primaryDark via-primaryDeep to-primaryDark" />
      <div className="absolute -right-32 -top-44 h-[440px] w-[440px] rounded-full bg-accent/10 blur-3xl" />
      <div className="absolute -bottom-48 -left-32 h-[420px] w-[420px] rounded-full bg-night/45 blur-3xl" />
      <div className="absolute inset-0 opacity-[0.16] [background-image:radial-gradient(rgba(255,255,255,0.7)_1px,transparent_1px)] [background-size:22px_22px] [mask-image:linear-gradient(to_bottom,#000,transparent_85%)]" />
    </div>
  );
}

export function SearchIntro() {
  return (
    <div className="max-w-3xl">
      {/* Texte blanc (et non jaune) : le jaune sur le vert du bandeau reste sous 4,5:1 en 11 px. */}
      <Eyebrow tone="dark" className="!text-white backdrop-blur">
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-accent" />
        Prestations à domicile
      </Eyebrow>
      <h1 className="mt-4 font-display text-[2rem] font-extrabold leading-[1.08] tracking-tight text-white [text-wrap:balance] sm:text-4xl lg:text-5xl">
        Trouver un artisan <span className="text-accent">près de chez vous</span>
      </h1>
      <p className="mt-3 hidden max-w-2xl text-base leading-relaxed text-white/80 sm:block sm:text-lg">
        Plomberie, électricité, climatisation, ménage… Comparez les prestations publiées, leurs tarifs et les
        profils des artisans, puis réservez en quelques minutes.
      </p>
    </div>
  );
}

/** Pastilles de métiers en chargement (sur le fond vert du bandeau). */
export function TradeChipsSkeleton() {
  return (
    <div aria-hidden className="mt-5 flex gap-2 overflow-hidden">
      {Array.from({ length: 6 }, (_, i) => (
        <span key={i} className="h-11 w-32 shrink-0 animate-pulse rounded-full bg-white/10" />
      ))}
    </div>
  );
}

/** Panneau de filtres (bureau) en chargement. */
function FiltersSkeleton() {
  return (
    <Card aria-hidden padding="none" className="space-y-6 p-5">
      <Skeleton className="h-6 w-24" />
      <div className="space-y-3">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-12 w-full" />
      </div>
      <div className="space-y-3">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="h-14 w-full !rounded-panel" />
        <Skeleton className="h-14 w-full !rounded-panel" />
      </div>
      <div className="space-y-3">
        <Skeleton className="h-3 w-24" />
        <div className="grid grid-cols-3 gap-2">
          <Skeleton className="h-11" />
          <Skeleton className="h-11" />
          <Skeleton className="h-11" />
        </div>
      </div>
      <div className="space-y-3">
        <Skeleton className="h-3 w-16" />
        <div className="grid grid-cols-2 gap-2">
          <Skeleton className="h-11" />
          <Skeleton className="h-11" />
        </div>
      </div>
    </Card>
  );
}

export function SearchPageSkeleton() {
  return (
    <div aria-busy="true">
      <section className="relative isolate overflow-hidden">
        <HeroBackdrop />
        <div className={HERO_SHELL}>
          <SearchIntro />
          <div className={SEARCH_CARD}>
            <div className="flex flex-col gap-2 lg:flex-row">
              <div className="flex flex-col gap-2 sm:flex-row lg:flex-1">
                <Skeleton className="h-[60px] !rounded-panel !bg-lineSoft sm:flex-[1.4]" />
                <Skeleton className="h-[60px] !rounded-panel !bg-lineSoft sm:flex-1" />
              </div>
              <Skeleton className="h-[52px] !rounded-full !bg-lineSoft lg:h-[60px] lg:w-80" />
            </div>
          </div>
          <TradeChipsSkeleton />
        </div>
      </section>
      <div className={RESULTS_SHELL}>
        <div className={RESULTS_LAYOUT}>
          <div className="hidden lg:block">
            <FiltersSkeleton />
          </div>
          <div className="min-w-0">
            <div className="mb-6 space-y-2">
              <Skeleton className="h-7 w-48" />
              <Skeleton className="h-4 w-64" />
            </div>
            <CardGridSkeleton count={6} className={RESULTS_GRID} />
          </div>
        </div>
      </div>
    </div>
  );
}
