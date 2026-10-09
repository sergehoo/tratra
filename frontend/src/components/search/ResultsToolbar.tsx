"use client";
import { useId, type RefObject } from "react";
import { ArrowUpDown, ChevronDown, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ds/Button";
import { CONTROL } from "@/components/ds/Field";
import { Spinner } from "@/components/ds/Spinner";
import { SORT_OPTIONS, type SortKey } from "./useSearchState";

/**
 * En-tête des résultats : compteur (région aria-live), bouton « Filtres »
 * (mobile) et tri. En mode « Autour de moi », le tri est fixé sur la distance.
 */
export default function ResultsToolbar({
  titleId,
  headline,
  subline,
  busy,
  sort,
  onSort,
  sortLocked,
  filterCount,
  onOpenFilters,
  filtersOpen,
  filterButtonRef,
}: {
  titleId: string;
  headline: string;
  subline: string;
  busy: boolean;
  sort: SortKey;
  onSort: (sort: SortKey) => void;
  sortLocked: boolean;
  filterCount: number;
  onOpenFilters: () => void;
  filtersOpen: boolean;
  filterButtonRef: RefObject<HTMLButtonElement>;
}) {
  const sortId = useId();
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div aria-live="polite" aria-atomic="true" className="min-w-0">
        <h2 id={titleId} className="flex items-center gap-2 font-display text-h2 text-ink">
          {headline}
          {busy ? <Spinner className="h-5 w-5 text-primary" /> : null}
        </h2>
        <p className="mt-1 text-sm text-ash [overflow-wrap:anywhere]">{subline}</p>
      </div>

      <div className="flex items-center gap-2">
        <Button
          ref={filterButtonRef}
          type="button"
          variant="outline"
          onClick={onOpenFilters}
          aria-haspopup="dialog"
          aria-expanded={filtersOpen}
          className="shrink-0 lg:hidden"
          leftIcon={<SlidersHorizontal aria-hidden className="h-4 w-4 text-primary" />}
        >
          Filtres
          {filterCount > 0 ? (
            <span className="grid h-5 min-w-[20px] place-items-center rounded-full bg-primaryDark px-1.5 text-[11px] font-bold text-white">
              <span className="sr-only">(</span>
              {filterCount}
              <span className="sr-only"> actif{filterCount > 1 ? "s" : ""})</span>
            </span>
          ) : null}
        </Button>

        <div className="relative min-w-0 flex-1 sm:flex-none">
          <label htmlFor={sortId} className="sr-only">
            Trier les résultats
          </label>
          <ArrowUpDown
            aria-hidden
            className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-primary"
          />
          <select
            id={sortId}
            value={sortLocked ? "distance" : sort}
            disabled={sortLocked}
            onChange={(e) => onSort(e.target.value as SortKey)}
            className={`${CONTROL} min-h-[44px] appearance-none pl-10 pr-10 font-semibold shadow-hair sm:w-auto`}
          >
            {sortLocked ? (
              <option value="distance">Les plus proches</option>
            ) : (
              SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))
            )}
          </select>
          <ChevronDown
            aria-hidden
            className="pointer-events-none absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ash"
          />
        </div>
      </div>
    </div>
  );
}
