"use client";
import type { ReactNode } from "react";
import { m } from "framer-motion";
import { ChevronDown, Loader2, RotateCcw } from "lucide-react";
import ServiceCard from "@/components/market/ServiceCard";
import { CardGridSkeleton } from "@/components/market/Skeletons";
import { formatCount } from "@/lib/format";
import { FOCUS_RING } from "./controls";
import { RESULTS_GRID } from "./SearchSkeleton";
import { PAGE_SIZE } from "./useSearchState";
import type { ServiceSearch } from "./useServiceSearch";

/**
 * Grille de résultats réels (ServiceCard) + pagination « Charger plus ».
 * Les états vide et erreur sont fournis par l'appelant (actions contextuelles).
 */
export default function SearchResults({
  search,
  emptyState,
  errorState,
}: {
  search: ServiceSearch;
  emptyState: ReactNode;
  errorState: ReactNode;
}) {
  const { items, count, status, more, hasMore, loadMore } = search;
  const pending = status === "loading" || status === "waiting";

  if (status === "error") return <>{errorState}</>;
  if (pending && items.length === 0) return <CardGridSkeleton count={6} className={RESULTS_GRID} />;
  if (status === "ready" && items.length === 0) return <>{emptyState}</>;

  const total = count ?? items.length;
  const progress = total > 0 ? Math.min(100, Math.round((items.length / total) * 100)) : 100;

  return (
    <div>
      <div
        aria-busy={pending || undefined}
        className={`${RESULTS_GRID} transition-opacity duration-300 ${pending ? "pointer-events-none opacity-50" : ""}`}
      >
        {items.map((service, i) => (
          <m.div
            key={service.id}
            className="h-full"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1], delay: Math.min(i % PAGE_SIZE, 8) * 0.04 }}
          >
            <ServiceCard service={service} />
          </m.div>
        ))}
      </div>

      {more === "loading" ? <CardGridSkeleton count={3} className={`mt-5 ${RESULTS_GRID}`} /> : null}

      <div className="mt-10 flex flex-col items-center gap-4">
        {total > 0 ? (
          <div className="w-full max-w-xs text-center">
            <p className="text-sm text-ash">
              <strong className="font-semibold text-ink">{formatCount(items.length)}</strong> sur{" "}
              {formatCount(total)} prestation{total > 1 ? "s" : ""}
            </p>
            <div aria-hidden className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200">
              <div
                className="h-full rounded-full bg-gradient-to-r from-primary to-accent transition-all duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        ) : null}

        {more === "error" ? (
          <p role="alert" className="text-sm font-medium text-red-700">
            Impossible de charger la suite des résultats. Vérifiez votre connexion.
          </p>
        ) : null}

        {hasMore ? (
          <button
            type="button"
            onClick={loadMore}
            disabled={more === "loading" || pending}
            className={`inline-flex min-h-[48px] items-center gap-2 rounded-2xl border-2 border-primary bg-white px-6 text-sm font-bold text-primaryDark transition hover:bg-primary hover:text-white disabled:cursor-wait disabled:opacity-60 ${FOCUS_RING}`}
          >
            {more === "loading" ? (
              <>
                <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
                Chargement…
              </>
            ) : more === "error" ? (
              <>
                <RotateCcw aria-hidden className="h-4 w-4" />
                Réessayer
              </>
            ) : (
              <>
                Charger plus
                <ChevronDown aria-hidden className="h-4 w-4" />
              </>
            )}
          </button>
        ) : null}
      </div>
    </div>
  );
}
