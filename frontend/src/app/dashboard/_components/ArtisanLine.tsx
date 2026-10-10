import { BadgeCheck, Star } from "lucide-react";
import { Avatar, Badge, cx } from "@/components/ds";
import { formatRating } from "@/lib/format";
import type { Service } from "@/lib/types";
import { artisanDisplayName } from "@/lib/artisan";
import Link from "next/link";
import { TrustBadges } from "@/components/trust/TrustBadge";

/** Artisan d'un service : photo (ou initiales), nom, « Vérifié » et indicateurs réels uniquement. */
export function ArtisanLine({
  service,
  size = 40,
  className = "",
}: {
  service: Pick<Service, "artisan" | "handyman_detail">;
  size?: number;
  className?: string;
}) {
  const artisan = service.artisan;
  const name = artisanDisplayName(service);
  if (!name) return null;

  const rating = formatRating(artisan?.rating);
  const jobs = artisan?.completed_jobs ?? 0;

  return (
    <div className={cx("flex min-w-0 items-center gap-3", className)}>
      <Avatar name={name} photo={artisan?.photo} size={size} online={artisan?.online} />
      <div className="min-w-0">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-ink">
          {artisan?.id ? (
            <Link href={`/artisans/${artisan.id}`} className="truncate hover:text-primaryDark hover:underline" aria-label={`Passeport professionnel de ${name}`}>
              {name}
            </Link>
          ) : (
            <span className="truncate">{name}</span>
          )}
          {!artisan?.badges?.length && artisan?.is_verified ? (
            <Badge tone="primary" icon={<BadgeCheck />} className="shrink-0">
              Vérifié
            </Badge>
          ) : null}
        </p>
        {artisan?.badges?.length ? <TrustBadges badges={artisan.badges} className="my-1" /> : null}
        <p className="flex flex-wrap items-center gap-x-2.5 text-xs text-ash">
          {rating ? (
            <span className="inline-flex items-center gap-1 font-semibold text-ink" aria-label={`Note ${rating} sur 5`}>
              <Star aria-hidden className="h-3.5 w-3.5 fill-accent text-accent" />
              {rating}
            </span>
          ) : null}
          {jobs > 0 ? <span>{jobs} mission{jobs > 1 ? "s" : ""}</span> : null}
          {artisan?.commune ? <span className="truncate">{artisan.commune}</span> : null}
        </p>
      </div>
    </div>
  );
}
