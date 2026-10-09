"use client";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { CircleAlert, LayoutGrid, LocateFixed, MapPin, Search, X } from "lucide-react";
import { buttonClass } from "@/components/ds/Button";
import { cx } from "@/components/ds/cx";
import { Spinner } from "@/components/ds/Spinner";
import type { ResolvedTrade } from "@/lib/trades";
import { HERO_SHELL, HeroBackdrop, SEARCH_CARD, SearchIntro, TradeChipsSkeleton } from "./SearchSkeleton";
import type { CategoriesStatus } from "./FiltersPanel";
import {
  DEFAULT_RADIUS,
  isLocated,
  roundCoord,
  useDebouncedDraft,
  type SearchState,
} from "./useSearchState";

const GEO_MESSAGES = {
  unsupported:
    "La géolocalisation n'est pas disponible sur cet appareil ou ce navigateur. Indiquez votre commune pour affiner la recherche.",
  denied:
    "Accès à votre position refusé. Autorisez la localisation dans les réglages de votre navigateur, ou indiquez votre commune.",
  unavailable:
    "Position introuvable pour le moment. Vérifiez que la localisation de l'appareil est activée, ou indiquez votre commune.",
  timeout: "La localisation prend trop de temps. Réessayez, ou indiquez votre commune.",
} as const;

const RING_ON_GREEN =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-primaryDark";

function TradeChip({
  pressed,
  onClick,
  icon: Icon,
  label,
  count,
}: {
  pressed: boolean | "mixed";
  onClick: () => void;
  icon: ResolvedTrade["icon"];
  label: string;
  count?: number | null;
}) {
  const on = pressed === true;
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={`inline-flex min-h-[44px] shrink-0 items-center gap-2 whitespace-nowrap rounded-full border px-4 text-sm font-semibold transition duration-base ease-emphasized ${RING_ON_GREEN} ${
        on
          ? "border-accent bg-accent text-ink shadow-glowAccent"
          : pressed === "mixed"
            ? "border-accent/70 bg-white/15 text-white"
            : "border-white/15 bg-white/10 text-white hover:border-white/30 hover:bg-white/20"
      }`}
    >
      <Icon aria-hidden className={`h-4 w-4 ${on ? "text-ink" : "text-accent"}`} />
      {label}
      {typeof count === "number" && count > 0 ? (
        <span
          className={`rounded-full px-1.5 py-0.5 text-[11px] font-bold leading-none ${
            on ? "bg-night/10 text-ink" : "bg-white/15 text-white"
          }`}
        >
          <span className="sr-only">, </span>
          {count}
          <span className="sr-only"> prestation{count > 1 ? "s" : ""}</span>
        </span>
      ) : null}
      {pressed === "mixed" ? <span className="sr-only"> (en partie sélectionné)</span> : null}
    </button>
  );
}

export default function SearchHero({
  state,
  update,
  trades,
  categoriesStatus,
}: {
  state: SearchState;
  update: (patch: Partial<SearchState>) => void;
  trades: ResolvedTrade[];
  categoriesStatus: CategoriesStatus;
}) {
  const uid = useId();
  const qId = `${uid}-q`;
  const communeId = `${uid}-commune`;
  const familiesLabelId = `${uid}-families`;
  const located = isLocated(state);

  const [q, setQ, flushQ] = useDebouncedDraft(state.q, (value) => update({ q: value }));
  const [commune, setCommune, flushCommune] = useDebouncedDraft(state.commune, (value) => update({ commune: value }));

  const [locating, setLocating] = useState(false);
  const [geoError, setGeoError] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  function submit(e: FormEvent) {
    e.preventDefault();
    flushQ();
    flushCommune();
  }

  function toggleLocation() {
    setGeoError(null);
    if (located) {
      update({ lat: null, lng: null, radius: DEFAULT_RADIUS });
      return;
    }
    if (typeof navigator === "undefined" || !("geolocation" in navigator) || !window.isSecureContext) {
      setGeoError(GEO_MESSAGES.unsupported);
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        if (!mounted.current) return;
        setLocating(false);
        update({ lat: roundCoord(pos.coords.latitude), lng: roundCoord(pos.coords.longitude) });
      },
      (err) => {
        if (!mounted.current) return;
        setLocating(false);
        setGeoError(
          err.code === err.PERMISSION_DENIED
            ? GEO_MESSAGES.denied
            : err.code === err.TIMEOUT
              ? GEO_MESSAGES.timeout
              : GEO_MESSAGES.unavailable,
        );
      },
      { enableHighAccuracy: false, timeout: 12000, maximumAge: 5 * 60 * 1000 },
    );
  }

  function familyState(t: ResolvedTrade): boolean | "mixed" {
    const selected = new Set(state.metier);
    const hits = t.categories.filter((c) => selected.has(c.slug)).length;
    if (!hits) return false;
    return hits === t.categories.length ? true : "mixed";
  }

  function toggleFamily(t: ResolvedTrade) {
    const slugs = t.categories.map((c) => c.slug);
    const next = new Set(state.metier);
    if (familyState(t) === true) slugs.forEach((s) => next.delete(s));
    else slugs.forEach((s) => next.add(s));
    update({ metier: Array.from(next) });
  }

  const fieldShell =
    "relative flex min-h-[60px] min-w-0 items-center gap-3 rounded-panel px-4 transition duration-base hover:bg-canvas focus-within:bg-canvas focus-within:ring-2 focus-within:ring-primary/40";
  const fieldLabel = "block text-eyebrow uppercase text-primaryDark";
  const fieldInput =
    "w-full min-w-0 bg-transparent text-[15px] font-medium text-ink outline-none placeholder:font-normal placeholder:text-fog [&::-webkit-search-cancel-button]:appearance-none";
  const clearBtn =
    "-mr-2 grid h-11 w-11 shrink-0 place-items-center rounded-full text-ash transition duration-base hover:bg-line hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary";

  return (
    <section className="relative isolate overflow-hidden">
      <HeroBackdrop />
      <div className={HERO_SHELL}>
        <SearchIntro />

        <form
          role="search"
          aria-label="Rechercher une prestation"
          onSubmit={submit}
          className={SEARCH_CARD}
        >
          <div className="flex flex-col gap-2 lg:flex-row lg:items-stretch">
            <div className="flex min-w-0 flex-col gap-2 sm:flex-row lg:flex-1">
              <div className={`${fieldShell} sm:flex-[1.4]`}>
                <Search aria-hidden className="h-5 w-5 shrink-0 text-primary" />
                <div className="min-w-0 flex-1">
                  <label htmlFor={qId} className={fieldLabel}>
                    Service ou métier
                  </label>
                  <input
                    id={qId}
                    type="search"
                    enterKeyHint="search"
                    autoComplete="off"
                    maxLength={100}
                    placeholder="Plomberie, climatisation, ménage…"
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    className={fieldInput}
                  />
                </div>
                {q ? (
                  <button type="button" aria-label="Effacer le service recherché" onClick={() => setQ("")} className={clearBtn}>
                    <X aria-hidden className="h-4 w-4" />
                  </button>
                ) : null}
              </div>

              <span aria-hidden className="hidden w-px self-stretch bg-line sm:my-3 sm:block" />

              <div className={`${fieldShell} sm:flex-1`}>
                <MapPin aria-hidden className="h-5 w-5 shrink-0 text-primary" />
                <div className="min-w-0 flex-1">
                  <label htmlFor={communeId} className={fieldLabel}>
                    Commune
                  </label>
                  <input
                    id={communeId}
                    type="text"
                    enterKeyHint="search"
                    autoComplete="address-level2"
                    maxLength={60}
                    placeholder="Cocody, Yopougon, Marcory…"
                    value={commune}
                    onChange={(e) => setCommune(e.target.value)}
                    className={fieldInput}
                  />
                </div>
                {commune ? (
                  <button type="button" aria-label="Effacer la commune" onClick={() => setCommune("")} className={clearBtn}>
                    <X aria-hidden className="h-4 w-4" />
                  </button>
                ) : null}
              </div>
            </div>

            <div className="flex gap-2 lg:shrink-0">
              <button
                type="button"
                onClick={toggleLocation}
                disabled={locating}
                aria-pressed={located}
                aria-busy={locating || undefined}
                className={buttonClass(
                  located ? "night" : "soft",
                  "lg",
                  cx(
                    "min-w-0 flex-1 disabled:!cursor-wait disabled:!opacity-100 lg:min-h-[60px] lg:flex-none",
                    // `night` prévoit un liseré jaune : sur la carte blanche on garde un liseré blanc.
                    located && "focus-visible:!ring-offset-white",
                  ),
                )}
              >
                {locating ? (
                  <Spinner />
                ) : (
                  <LocateFixed aria-hidden className={`h-4 w-4 ${located ? "text-accent" : ""}`} />
                )}
                <span className="truncate">{locating ? "Localisation…" : "Autour de moi"}</span>
                {located && !locating ? (
                  <span className="rounded-full bg-accent px-2 py-0.5 text-[11px] font-bold text-ink">
                    {state.radius} km
                  </span>
                ) : null}
                {located && !locating ? <X aria-hidden className="h-3.5 w-3.5 text-white/60" /> : null}
              </button>
              <button type="submit" className={buttonClass("primary", "lg", "min-w-[52px] lg:min-h-[60px]")}>
                <Search aria-hidden className="h-5 w-5" />
                <span className="sr-only sm:not-sr-only">Rechercher</span>
              </button>
            </div>
          </div>
        </form>

        {geoError ? (
          <div
            role="alert"
            className="mt-3 flex items-start gap-3 rounded-panel border border-white/15 bg-night/35 px-4 py-3 text-sm text-white backdrop-blur"
          >
            <CircleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
            <p className="flex-1">{geoError}</p>
            <button
              type="button"
              onClick={() => setGeoError(null)}
              aria-label="Fermer le message"
              className={`-my-2 -mr-2 grid h-11 w-11 shrink-0 place-items-center rounded-full text-white/80 hover:bg-white/10 hover:text-white ${RING_ON_GREEN}`}
            >
              <X aria-hidden className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        {categoriesStatus === "loading" ? (
          <TradeChipsSkeleton />
        ) : trades.length ? (
          <div className="mt-5">
            <p id={familiesLabelId} className="sr-only">
              Filtrer par métier
            </p>
            <div
              role="group"
              aria-labelledby={familiesLabelId}
              className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [mask-image:linear-gradient(to_right,transparent,#000_16px,#000_calc(100%_-_16px),transparent)] [scrollbar-width:none] sm:-mx-6 sm:px-6 lg:mx-0 lg:flex-wrap lg:overflow-visible lg:px-0 lg:[mask-image:none] [&::-webkit-scrollbar]:hidden"
            >
              <TradeChip
                pressed={state.metier.length === 0}
                onClick={() => update({ metier: [] })}
                icon={LayoutGrid}
                label="Tous les métiers"
              />
              {trades.map((t) => (
                <TradeChip
                  key={t.key}
                  pressed={familyState(t)}
                  onClick={() => toggleFamily(t)}
                  icon={t.icon}
                  label={t.label}
                  count={t.servicesCount}
                />
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
