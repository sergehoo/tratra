/** Squelettes de chargement (aria-busy porté par le conteneur appelant). */

export function ServiceCardSkeleton() {
  return (
    <div aria-hidden className="overflow-hidden rounded-3xl border border-slate-100 bg-white shadow-soft">
      <div className="skeleton aspect-[4/3] !rounded-none" />
      <div className="space-y-3 p-5">
        <div className="skeleton h-4 w-4/5" />
        <div className="skeleton h-4 w-2/5" />
        <div className="flex items-center gap-3 pt-2">
          <div className="skeleton h-9 w-9 !rounded-full" />
          <div className="flex-1 space-y-2">
            <div className="skeleton h-3 w-3/5" />
            <div className="skeleton h-3 w-2/5" />
          </div>
        </div>
        <div className="skeleton h-11 w-full !rounded-2xl" />
      </div>
    </div>
  );
}

export function ArtisanCardSkeleton() {
  return (
    <div aria-hidden className="rounded-3xl border border-slate-100 bg-white p-5 shadow-soft">
      <div className="flex items-center gap-4">
        <div className="skeleton h-16 w-16 !rounded-full" />
        <div className="flex-1 space-y-2">
          <div className="skeleton h-4 w-3/5" />
          <div className="skeleton h-3 w-2/5" />
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <div className="skeleton h-12" />
        <div className="skeleton h-12" />
      </div>
      <div className="skeleton mt-5 h-11 w-full !rounded-2xl" />
    </div>
  );
}

export function CardGridSkeleton({
  count = 6,
  kind = "service",
  className = "grid gap-5 sm:grid-cols-2 lg:grid-cols-3",
}: {
  count?: number;
  kind?: "service" | "artisan";
  className?: string;
}) {
  const Item = kind === "artisan" ? ArtisanCardSkeleton : ServiceCardSkeleton;
  return (
    <div className={className} role="status" aria-label="Chargement en cours">
      {Array.from({ length: count }, (_, i) => (
        <Item key={i} />
      ))}
      <span className="sr-only">Chargement…</span>
    </div>
  );
}
