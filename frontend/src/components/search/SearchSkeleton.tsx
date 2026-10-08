import { CardGridSkeleton } from "@/components/market/Skeletons";

/**
 * Éléments statiques de la page de recherche, utilisables côté serveur :
 * le squelette (fallback Suspense) contient déjà le vrai titre H1 pour le SEO.
 */

export const RESULTS_GRID = "grid gap-5 sm:grid-cols-2 xl:grid-cols-3";

/**
 * Fond décoratif du bandeau (vert de marque, halo jaune, trame de points).
 * Vert foncé au centre et halo jaune discret : le titre jaune garde ≥ 3:1 et
 * l'étiquette en text-xs ≥ 4,5:1 (WCAG AA), y compris sur mobile où le halo
 * passe derrière le titre.
 */
export function HeroBackdrop() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
      <div className="absolute inset-0 bg-gradient-to-br from-primaryDark via-[#1a5c38] to-primaryDark" />
      <div className="absolute -right-32 -top-44 h-[440px] w-[440px] rounded-full bg-accent/10 blur-3xl" />
      <div className="absolute -bottom-48 -left-32 h-[420px] w-[420px] rounded-full bg-night/45 blur-3xl" />
      <div className="absolute inset-0 opacity-[0.16] [background-image:radial-gradient(rgba(255,255,255,0.7)_1px,transparent_1px)] [background-size:22px_22px] [mask-image:linear-gradient(to_bottom,#000,transparent_85%)]" />
    </div>
  );
}

export function SearchIntro() {
  return (
    <div className="max-w-3xl">
      <span className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-white backdrop-blur">
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-accent" />
        Prestations à domicile
      </span>
      <h1 className="mt-4 font-display text-[2rem] font-extrabold leading-[1.08] tracking-tight text-white sm:text-4xl lg:text-5xl">
        Trouver un artisan <span className="text-accent">près de chez vous</span>
      </h1>
      <p className="mt-3 hidden max-w-2xl text-base leading-relaxed text-white/80 sm:block sm:text-lg">
        Plomberie, électricité, climatisation, ménage… Comparez les prestations publiées, leurs tarifs et les
        profils des artisans, puis réservez en quelques minutes.
      </p>
    </div>
  );
}

export function SearchPageSkeleton() {
  return (
    <div aria-busy="true">
      <section className="relative isolate overflow-hidden">
        <HeroBackdrop />
        <div className="relative mx-auto max-w-7xl px-4 pb-7 pt-8 sm:px-6 sm:pt-12 lg:px-8 lg:pb-9">
          <SearchIntro />
          <div className="mt-5 rounded-3xl bg-white/95 p-2 shadow-strong sm:mt-8">
            <div className="flex flex-col gap-2 lg:flex-row">
              <div className="flex flex-col gap-2 sm:flex-row lg:flex-1">
                <div className="skeleton h-[60px] !rounded-2xl !bg-slate-100 sm:flex-[1.4]" />
                <div className="skeleton h-[60px] !rounded-2xl !bg-slate-100 sm:flex-1" />
              </div>
              <div className="skeleton h-[52px] !rounded-2xl !bg-slate-100 lg:h-[60px] lg:w-80" />
            </div>
          </div>
          <div className="mt-5 flex gap-2 overflow-hidden">
            {Array.from({ length: 6 }, (_, i) => (
              <span key={i} className="h-11 w-32 shrink-0 animate-pulse rounded-full bg-white/10" />
            ))}
          </div>
        </div>
      </section>
      <div className="mx-auto max-w-7xl px-4 pb-16 pt-8 sm:px-6 lg:px-8">
        <div className="lg:grid lg:grid-cols-[288px_minmax(0,1fr)] lg:gap-8">
          <div className="hidden lg:block">
            <div className="skeleton h-[520px] !rounded-3xl !bg-white" />
          </div>
          <div className="min-w-0">
            <div className="mb-6 space-y-2">
              <div className="skeleton h-7 w-48" />
              <div className="skeleton h-4 w-64" />
            </div>
            <CardGridSkeleton count={6} className={RESULTS_GRID} />
          </div>
        </div>
      </div>
    </div>
  );
}
