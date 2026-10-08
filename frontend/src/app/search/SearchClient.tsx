"use client";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  ArrowRight,
  CalendarClock,
  LocateFixed,
  MapPinOff,
  RotateCcw,
  SearchX,
  SlidersHorizontal,
  Sparkles,
  UserRound,
  WifiOff,
} from "lucide-react";
import { Avatar, EmptyState } from "@/components/market/primitives";
import ActiveFilters, { type ActiveChip } from "@/components/search/ActiveFilters";
import { FOCUS_RING } from "@/components/search/controls";
import FilterSheet from "@/components/search/FilterSheet";
import FiltersPanel, { type CategoriesStatus } from "@/components/search/FiltersPanel";
import ResultsToolbar from "@/components/search/ResultsToolbar";
import SearchHero from "@/components/search/SearchHero";
import SearchResults from "@/components/search/SearchResults";
import {
  DEFAULT_RADIUS,
  MAX_RADIUS,
  PAGE_SIZE,
  PRICE_TYPE_OPTIONS,
  isLocated,
  useSearchState,
  type SearchState,
} from "@/components/search/useSearchState";
import { useServiceSearch } from "@/components/search/useServiceSearch";
import { formatCount, formatFCFA } from "@/lib/format";
import { registerHref } from "@/lib/links";
import { qs, resultsOf } from "@/lib/public";
import { resolveTrades } from "@/lib/trades";
import type { Category, Paginated } from "@/lib/types";
import { usePublicData } from "@/lib/usePublic";

/*
 * /services/nearby/ classe par distance et applique catégories, commune, en
 * ligne, vérifiés, budget (min/max) et rayon. Le mot-clé, le type de tarif, le
 * tri et l'artisan ne s'appliquent qu'à /services/ : en mode « Autour de moi »,
 * ils ne sont pas envoyés et l'interface le signale honnêtement.
 */

/** Valeurs neutres des filtres du panneau (hors mot-clé, commune et localisation). */
const FILTER_DEFAULTS: Partial<SearchState> = {
  metier: [],
  online: false,
  verified: false,
  priceType: "",
  minPrice: "",
  maxPrice: "",
  radius: DEFAULT_RADIUS,
};

const CATEGORIES_PATH = `/categories/${qs({ page_size: 100, ordering: "name" })}`;

const BTN_PRIMARY = `inline-flex min-h-[48px] items-center justify-center gap-2 rounded-2xl bg-primary px-5 text-sm font-bold text-white shadow-glow transition hover:bg-primaryDark ${FOCUS_RING}`;
const BTN_SECONDARY = `inline-flex min-h-[48px] items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-5 text-sm font-semibold text-ink transition hover:border-primary/40 hover:bg-slate-50 ${FOCUS_RING}`;

function joinFr(parts: string[]): string {
  if (parts.length <= 1) return parts.join("");
  return `${parts.slice(0, -1).join(", ")} et ${parts[parts.length - 1]}`;
}

export default function SearchClient() {
  const { state, update, reset } = useSearchState();
  const located = isLocated(state);
  /** Mot-clé, type de tarif, tri et artisan : appliqués hors mode « Autour de moi ». */
  const listMode = !located;
  const resultsTitleId = useId();
  const asideTitleId = useId();

  // ---- Catégories réelles (actives) -> slug -> id, familles de métiers ----
  const cats = usePublicData<Paginated<Category> | Category[]>(CATEGORIES_PATH);
  const categories = useMemo(() => resultsOf(cats.data).filter((c) => c.is_active !== false), [cats.data]);
  const categoriesStatus: CategoriesStatus = cats.loading ? "loading" : cats.data ? "ready" : "error";
  const bySlug = useMemo(() => new Map(categories.map((c) => [c.slug, c])), [categories]);
  const trades = useMemo(() => resolveTrades(categories), [categories]);
  const categoriesComplete =
    cats.data !== null && (Array.isArray(cats.data) || cats.data.count <= resultsOf(cats.data).length);

  // Un lien partagé peut contenir un métier qui n'existe plus : on le retire de
  // l'URL plutôt que d'afficher un filtre fantôme.
  useEffect(() => {
    if (categoriesStatus !== "ready" || !categoriesComplete || !state.metier.length) return;
    const known = state.metier.filter((slug) => bySlug.has(slug));
    if (known.length !== state.metier.length) update({ metier: known });
  }, [categoriesStatus, categoriesComplete, state.metier, bySlug, update]);

  const categoryIds = useMemo(
    () => state.metier.map((slug) => bySlug.get(slug)?.id).filter((id): id is number => typeof id === "number"),
    [state.metier, bySlug],
  );
  const categoriesBlocking = state.metier.length > 0 && categoriesStatus === "error";

  // ---- Requête de services (liste ou « autour de moi ») ----
  const query = useMemo(() => {
    if (state.metier.length > 0 && categoriesStatus !== "ready") return null;
    const common = {
      categories: categoryIds.length ? categoryIds.join(",") : undefined,
      commune: state.commune,
      online: state.online,
      verified: state.verified,
      min_price: state.minPrice,
      max_price: state.maxPrice,
      page_size: PAGE_SIZE,
    };
    if (state.lat !== null && state.lng !== null) {
      return `/services/nearby/${qs({ lat: state.lat, lng: state.lng, radius_km: state.radius, ...common })}`;
    }
    return `/services/${qs({
      is_active: "true",
      search: state.q,
      price_type: state.priceType,
      sort: state.sort,
      handyman: state.handyman,
      ...common,
    })}`;
  }, [state, categoriesStatus, categoryIds]);

  const search = useServiceSearch(query);

  // ---- Panneau de filtres mobile ----
  const [sheetOpen, setSheetOpen] = useState(false);
  const filterButtonRef = useRef<HTMLButtonElement>(null);
  const closeSheet = useCallback(() => setSheetOpen(false), []);

  const filterCount =
    (state.metier.length ? 1 : 0) +
    (state.online ? 1 : 0) +
    (state.verified ? 1 : 0) +
    (located && state.radius !== DEFAULT_RADIUS ? 1 : 0) +
    (state.minPrice ? 1 : 0) +
    (state.maxPrice ? 1 : 0) +
    (listMode && state.priceType ? 1 : 0);

  const resetFilters = useCallback(() => update(FILTER_DEFAULTS), [update]);
  // Le panneau mobile contient aussi le tri : sa réinitialisation l'inclut.
  const resetSheet = useCallback(() => update({ ...FILTER_DEFAULTS, sort: "recent" }), [update]);
  const clearLocation = useCallback(() => update({ lat: null, lng: null, radius: DEFAULT_RADIUS }), [update]);

  // ---- Filtres actifs (uniquement ceux réellement appliqués) ----
  const chips = useMemo<ActiveChip[]>(() => {
    const list: ActiveChip[] = [];
    if (state.q && listMode) list.push({ key: "q", label: `« ${state.q} »`, onRemove: () => update({ q: "" }) });
    if (state.metier.length) {
      const remaining = new Set(state.metier.filter((slug) => bySlug.has(slug)));
      for (const t of trades) {
        const slugs = t.categories.map((c) => c.slug);
        if (slugs.length > 1 && slugs.every((slug) => remaining.has(slug))) {
          slugs.forEach((slug) => remaining.delete(slug));
          list.push({
            key: `family-${t.key}`,
            label: t.label,
            onRemove: () => update({ metier: state.metier.filter((slug) => !slugs.includes(slug)) }),
          });
        }
      }
      Array.from(remaining).forEach((slug) => {
        list.push({
          key: `cat-${slug}`,
          label: bySlug.get(slug)?.name ?? slug,
          onRemove: () => update({ metier: state.metier.filter((s) => s !== slug) }),
        });
      });
    }
    if (state.commune) {
      list.push({ key: "commune", label: `Commune : ${state.commune}`, onRemove: () => update({ commune: "" }) });
    }
    if (located) list.push({ key: "near", label: `Autour de moi · ${state.radius} km`, onRemove: clearLocation });
    if (state.online) list.push({ key: "online", label: "En ligne maintenant", onRemove: () => update({ online: false }) });
    if (state.verified) {
      list.push({ key: "verified", label: "Profils vérifiés", onRemove: () => update({ verified: false }) });
    }
    const priceType = listMode ? PRICE_TYPE_OPTIONS.find((o) => o.value === state.priceType) : undefined;
    if (priceType) {
      list.push({ key: "price_type", label: `Tarif : ${priceType.label}`, onRemove: () => update({ priceType: "" }) });
    }
    const min = formatFCFA(state.minPrice);
    const max = formatFCFA(state.maxPrice);
    if (min) list.push({ key: "min", label: `Dès ${min}`, onRemove: () => update({ minPrice: "" }) });
    if (max) list.push({ key: "max", label: `Jusqu'à ${max}`, onRemove: () => update({ maxPrice: "" }) });
    return list;
  }, [state, listMode, located, bySlug, trades, update, clearLocation]);

  // Critères présents dans l'URL mais non appliqués en mode « Autour de moi ».
  const ignored: string[] = [];
  if (!listMode) {
    if (state.q) ignored.push(`le mot-clé « ${state.q} »`);
    if (state.priceType) ignored.push("le type de tarif");
    if (state.sort !== "recent") ignored.push("le tri");
    if (state.handyman) ignored.push("l'artisan sélectionné");
  }

  // ---- En-tête de résultats ----
  const pending = search.status === "loading" || search.status === "waiting";
  const total = search.count ?? 0;
  const headline =
    categoriesBlocking || search.status === "error"
      ? "Résultats indisponibles"
      : pending && search.count === null
        ? "Recherche en cours…"
        : total === 0
          ? "Aucune prestation"
          : `${formatCount(total)} prestation${total > 1 ? "s" : ""}`;
  const where: string[] = [];
  if (state.q && listMode) where.push(`pour « ${state.q} »`);
  if (located) where.push(`dans un rayon de ${state.radius} km autour de vous`);
  if (state.commune) where.push(`à ${state.commune}`);
  const handymanArtisan =
    state.handyman && search.status === "ready" ? (search.items.find((s) => s.artisan)?.artisan ?? null) : null;

  const subline = where.length
    ? `Prestations ${where.join(" ")}`
    : state.handyman && listMode
      ? `Prestations publiées par ${handymanArtisan?.display_name ?? "cet artisan"}`
      : filterCount > 0
        ? "Prestations correspondant à vos filtres"
        : "Toutes les prestations publiées sur Tratra";

  const applyLabel =
    search.status === "ready" && total > 0
      ? `Afficher ${formatCount(total)} prestation${total > 1 ? "s" : ""}`
      : "Voir les résultats";

  // ---- États vides honnêtes (actions réelles) ----
  const hasAnyCriteria =
    Boolean(state.q || state.commune || state.handyman) || state.metier.length > 0 || filterCount > 0 || located;

  let emptyState: ReactNode;
  if (!hasAnyCriteria) {
    emptyState = (
      <EmptyState
        icon={<Sparkles aria-hidden className="h-7 w-7" />}
        title="Les premières prestations arrivent"
        description="Les artisans Tratra publient actuellement leurs prestations. Revenez très vite : elles apparaîtront ici dès leur mise en ligne."
        actions={
          <>
            <Link href={registerHref("handyman")} className={BTN_PRIMARY}>
              Vous êtes artisan ? Proposez vos services
              <ArrowRight aria-hidden className="h-4 w-4" />
            </Link>
            <Link href="/" className={BTN_SECONDARY}>
              Retour à l&apos;accueil
            </Link>
          </>
        }
      />
    );
  } else if (state.handyman && listMode) {
    emptyState = (
      <EmptyState
        icon={<UserRound aria-hidden className="h-7 w-7" />}
        title="Aucune prestation de cet artisan pour ces critères"
        description="Cet artisan n'a pas de prestation publiée correspondant à votre recherche."
        actions={
          <button type="button" onClick={() => update({ handyman: "" })} className={BTN_PRIMARY}>
            Voir tous les artisans
          </button>
        }
      />
    );
  } else if (state.online) {
    emptyState = (
      <EmptyState
        icon={<CalendarClock aria-hidden className="h-7 w-7" />}
        title="Aucun artisan en ligne pour ces critères pour le moment"
        description="Les artisans hors ligne peuvent intervenir à la date de votre choix : planifiez votre intervention."
        actions={
          <button type="button" onClick={() => update({ online: false })} className={BTN_PRIMARY}>
            Planifier une intervention
            <ArrowRight aria-hidden className="h-4 w-4" />
          </button>
        }
      />
    );
  } else if (located) {
    emptyState = (
      <EmptyState
        icon={<MapPinOff aria-hidden className="h-7 w-7" />}
        title={`Aucune prestation dans un rayon de ${state.radius} km`}
        description="Élargissez la zone de recherche ou recherchez sans localisation."
        actions={
          <>
            {state.radius < MAX_RADIUS ? (
              <button type="button" onClick={() => update({ radius: MAX_RADIUS })} className={BTN_PRIMARY}>
                <LocateFixed aria-hidden className="h-4 w-4" />
                Élargir à {MAX_RADIUS} km
              </button>
            ) : null}
            <button
              type="button"
              onClick={clearLocation}
              className={state.radius < MAX_RADIUS ? BTN_SECONDARY : BTN_PRIMARY}
            >
              Rechercher partout
            </button>
          </>
        }
      />
    );
  } else {
    emptyState = (
      <EmptyState
        icon={<SearchX aria-hidden className="h-7 w-7" />}
        title="Aucun résultat"
        description={
          state.q ? (
            <span className="[overflow-wrap:anywhere]">
              Aucune prestation ne correspond à « {state.q} » avec ces critères. Essayez un autre mot-clé ou retirez
              des filtres.
            </span>
          ) : (
            "Aucune prestation ne correspond à ces critères pour le moment."
          )
        }
        actions={
          <button type="button" onClick={() => reset()} className={BTN_PRIMARY}>
            <RotateCcw aria-hidden className="h-4 w-4" />
            Retirer les filtres
          </button>
        }
      />
    );
  }

  const errorState = (
    <EmptyState
      icon={<WifiOff aria-hidden className="h-7 w-7" />}
      title="Impossible de charger les prestations"
      description="Le service n'a pas pu répondre à cette recherche. Vérifiez votre connexion puis réessayez."
      actions={
        <>
          <button type="button" onClick={search.retry} className={BTN_PRIMARY}>
            <RotateCcw aria-hidden className="h-4 w-4" />
            Réessayer
          </button>
          {/* Un lien partagé peut viser un artisan ou un critère qui n'existe plus. */}
          {state.handyman ? (
            <button type="button" onClick={() => update({ handyman: "" })} className={BTN_SECONDARY}>
              Voir tous les artisans
            </button>
          ) : hasAnyCriteria ? (
            <button type="button" onClick={() => reset()} className={BTN_SECONDARY}>
              Retirer les filtres
            </button>
          ) : null}
        </>
      }
    />
  );

  const panelProps = {
    state,
    update,
    categories,
    trades,
    categoriesStatus,
    onRetryCategories: cats.reload,
    distanceSorted: !listMode,
  };

  return (
    <>
      <SearchHero state={state} update={update} trades={trades} categoriesStatus={categoriesStatus} />

      <div className="mx-auto max-w-7xl px-4 pb-20 pt-8 sm:px-6 lg:px-8 lg:pt-10">
        <div className="lg:grid lg:grid-cols-[288px_minmax(0,1fr)] lg:gap-8">
          <aside className="hidden lg:block" aria-labelledby={asideTitleId}>
            <div className="sticky top-28 max-h-[calc(100vh-8rem)] overflow-y-auto rounded-3xl border border-slate-100 bg-white p-5 shadow-soft [scrollbar-width:thin]">
              <div className="mb-6 flex items-center justify-between gap-2">
                <h2 id={asideTitleId} className="flex items-center gap-2 font-display text-lg font-extrabold text-ink">
                  <SlidersHorizontal aria-hidden className="h-5 w-5 text-primary" />
                  Filtres
                </h2>
                {filterCount > 0 ? (
                  <button
                    type="button"
                    onClick={resetFilters}
                    className={`-mr-2 inline-flex min-h-[44px] items-center rounded-xl px-2 text-sm font-semibold text-primaryDark hover:underline ${FOCUS_RING}`}
                  >
                    Effacer
                  </button>
                ) : null}
              </div>
              <FiltersPanel {...panelProps} />
            </div>
          </aside>

          <section aria-labelledby={resultsTitleId} className="min-w-0">
            {state.handyman && listMode ? (
              <div className="relative mb-6 flex flex-col gap-4 overflow-hidden rounded-3xl bg-night p-5 text-white shadow-strong sm:flex-row sm:items-center">
                <div
                  aria-hidden
                  className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-primary/40 blur-3xl"
                />
                {handymanArtisan ? (
                  <Avatar
                    name={handymanArtisan.display_name}
                    photo={handymanArtisan.photo}
                    size={56}
                    online={handymanArtisan.online}
                    className="relative"
                  />
                ) : (
                  <span className="relative grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-white/10 text-accent">
                    <UserRound aria-hidden className="h-6 w-6" />
                  </span>
                )}
                <div className="relative min-w-0 flex-1">
                  <p className="text-xs font-bold uppercase tracking-[0.14em] text-accent">Prestations d&apos;un artisan</p>
                  <p className="mt-0.5 truncate font-display text-lg font-bold">
                    {handymanArtisan?.display_name ?? "Artisan sélectionné"}
                  </p>
                  {handymanArtisan?.commune ? <p className="text-sm text-white/70">{handymanArtisan.commune}</p> : null}
                </div>
                <button
                  type="button"
                  onClick={() => update({ handyman: "" })}
                  className="relative inline-flex min-h-[44px] items-center justify-center gap-2 rounded-xl bg-white px-4 text-sm font-bold text-night transition hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-night"
                >
                  Voir tous les artisans
                  <ArrowRight aria-hidden className="h-4 w-4" />
                </button>
              </div>
            ) : null}

            <ResultsToolbar
              titleId={resultsTitleId}
              headline={headline}
              subline={subline}
              busy={pending && search.count !== null && !categoriesBlocking}
              sort={state.sort}
              onSort={(sort) => update({ sort })}
              sortLocked={!listMode}
              filterCount={filterCount}
              onOpenFilters={() => setSheetOpen(true)}
              filtersOpen={sheetOpen}
              filterButtonRef={filterButtonRef}
            />

            <ActiveFilters chips={chips} onResetAll={() => reset()} />

            {ignored.length ? (
              <div
                role="note"
                className="mt-5 flex flex-col gap-3 rounded-2xl border border-accent/50 bg-accentSoft p-4 sm:flex-row sm:items-center"
              >
                <LocateFixed aria-hidden className="h-5 w-5 shrink-0 text-night" />
                <p className="min-w-0 flex-1 text-sm text-ink [overflow-wrap:anywhere]">
                  Autour de vous, les résultats sont classés par distance : {joinFr(ignored)}{" "}
                  {ignored.length > 1 ? "ne s'appliquent" : "ne s'applique"} pas.
                </p>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={clearLocation}
                    className={`inline-flex min-h-[44px] items-center rounded-xl bg-night px-4 text-sm font-semibold text-white transition hover:bg-nightSoft ${FOCUS_RING}`}
                  >
                    Rechercher partout
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      update({ q: "", priceType: "", sort: "recent", handyman: "" })
                    }
                    className={`inline-flex min-h-[44px] items-center rounded-xl border border-night/15 bg-white px-4 text-sm font-semibold text-ink transition hover:bg-slate-50 ${FOCUS_RING}`}
                  >
                    Retirer ces critères
                  </button>
                </div>
              </div>
            ) : null}

            <div className="mt-6">
              {categoriesBlocking ? (
                <EmptyState
                  icon={<WifiOff aria-hidden className="h-7 w-7" />}
                  title="Impossible de charger les métiers"
                  description="La liste des métiers est nécessaire pour appliquer votre filtre. Vérifiez votre connexion puis réessayez."
                  actions={
                    <>
                      <button type="button" onClick={cats.reload} className={BTN_PRIMARY}>
                        <RotateCcw aria-hidden className="h-4 w-4" />
                        Réessayer
                      </button>
                      <button type="button" onClick={() => update({ metier: [] })} className={BTN_SECONDARY}>
                        Voir tous les métiers
                      </button>
                    </>
                  }
                />
              ) : (
                <SearchResults search={search} emptyState={emptyState} errorState={errorState} />
              )}
            </div>
          </section>
        </div>
      </div>

      <FilterSheet
        open={sheetOpen}
        onClose={closeSheet}
        onReset={resetSheet}
        resetDisabled={filterCount === 0 && state.sort === "recent"}
        applyLabel={applyLabel}
        returnFocusRef={filterButtonRef}
      >
        <FiltersPanel {...panelProps} showSort />
      </FilterSheet>
    </>
  );
}
