import { Card } from "@/components/ds/Card";
import { Skeleton } from "@/components/ds/Skeleton";

/** Squelettes de chargement (aria-busy porté par le conteneur appelant). */

export function ServiceCardSkeleton() {
  return (
    <Card aria-hidden padding="none" className="overflow-hidden">
      <Skeleton className="aspect-[4/3] !rounded-none" />
      <div className="space-y-3 p-5">
        <Skeleton className="h-4 w-4/5" />
        <Skeleton className="h-4 w-2/5" />
        <div className="flex items-center gap-3 pt-2">
          <Skeleton className="h-9 w-9 !rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3 w-3/5" />
            <Skeleton className="h-3 w-2/5" />
          </div>
        </div>
        <Skeleton className="h-11 w-full !rounded-full" />
      </div>
    </Card>
  );
}

export function ArtisanCardSkeleton() {
  return (
    <Card aria-hidden padding="md">
      <div className="flex items-center gap-4">
        <Skeleton className="h-16 w-16 !rounded-full" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-3/5" />
          <Skeleton className="h-3 w-2/5" />
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <Skeleton className="h-12 !rounded-panel" />
        <Skeleton className="h-12 !rounded-panel" />
      </div>
      <Skeleton className="mt-5 h-11 w-full !rounded-full" />
    </Card>
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
