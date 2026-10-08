import { cx } from "./cx";

/** Bloc squelette (le shimmer est défini dans globals.css, neutralisé en « mouvement réduit »). */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden className={cx("skeleton", className)} />;
}

/** Quelques lignes de texte ; la dernière est plus courte. */
export function SkeletonText({ lines = 3, className = "" }: { lines?: number; className?: string }) {
  return (
    <div aria-hidden className={cx("space-y-2.5", className)}>
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className={cx("skeleton h-3.5", i === lines - 1 && lines > 1 ? "w-3/5" : "w-full")} />
      ))}
    </div>
  );
}

/** Carte de liste en chargement (icône, deux lignes, badge). */
export function SkeletonCard({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cx("flex items-center gap-4 rounded-card border border-lineSoft bg-white p-5 shadow-soft", className)}
    >
      <div className="skeleton h-12 w-12 shrink-0 !rounded-2xl" />
      <div className="flex-1 space-y-2.5">
        <div className="skeleton h-4 w-2/5" />
        <div className="skeleton h-3 w-3/5" />
      </div>
      <div className="skeleton h-7 w-20 !rounded-full" />
    </div>
  );
}

/** Liste de cartes en chargement, annoncée une seule fois aux lecteurs d'écran. */
export function SkeletonList({ count = 3, className = "" }: { count?: number; className?: string }) {
  return (
    <div role="status" aria-label="Chargement en cours" className={cx("grid gap-3", className)}>
      {Array.from({ length: count }, (_, i) => (
        <SkeletonCard key={i} />
      ))}
      <span className="sr-only">Chargement…</span>
    </div>
  );
}

/** Rangée d'indicateurs en chargement. */
export function SkeletonStats({ count = 3, className = "" }: { count?: number; className?: string }) {
  return (
    <div role="status" aria-label="Chargement en cours" className={cx("grid gap-4 sm:grid-cols-3", className)}>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} aria-hidden className="flex items-start gap-4 rounded-card border border-lineSoft bg-white p-5 shadow-soft">
          <div className="skeleton h-12 w-12 shrink-0 !rounded-2xl" />
          <div className="flex-1 space-y-2.5 pt-1">
            <div className="skeleton h-6 w-1/2" />
            <div className="skeleton h-3 w-3/4" />
          </div>
        </div>
      ))}
      <span className="sr-only">Chargement…</span>
    </div>
  );
}

/** Tableau en chargement (en-tête + lignes). */
export function SkeletonTable({ rows = 5, cols = 4, className = "" }: { rows?: number; cols?: number; className?: string }) {
  return (
    <div
      role="status"
      aria-label="Chargement en cours"
      className={cx("overflow-hidden rounded-card border border-lineSoft bg-white shadow-soft", className)}
    >
      <div aria-hidden className="flex gap-6 border-b border-lineSoft bg-canvas px-5 py-3.5">
        {Array.from({ length: cols }, (_, i) => (
          <div key={i} className="skeleton h-3 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} aria-hidden className="flex gap-6 border-t border-lineSoft px-5 py-4 first:border-t-0">
          {Array.from({ length: cols }, (_, c) => (
            <div key={c} className="skeleton h-4 flex-1" />
          ))}
        </div>
      ))}
      <span className="sr-only">Chargement…</span>
    </div>
  );
}

/** Page de détail en chargement (titre + carte principale + carte latérale). */
export function SkeletonPage({ className = "" }: { className?: string }) {
  return (
    <div role="status" aria-label="Chargement en cours" className={cx("space-y-6", className)}>
      <div aria-hidden className="space-y-3">
        <div className="skeleton h-8 w-1/3" />
        <div className="skeleton h-4 w-1/2" />
      </div>
      <div aria-hidden className="grid gap-6 lg:grid-cols-3">
        <div className="skeleton h-72 !rounded-card lg:col-span-2" />
        <div className="skeleton h-72 !rounded-card" />
      </div>
      <span className="sr-only">Chargement…</span>
    </div>
  );
}
