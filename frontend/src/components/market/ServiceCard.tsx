"use client";
import Link from "next/link";
import { ArrowRight, Clock, MapPin } from "lucide-react";
import { Badge } from "@/components/ds/Badge";
import { ButtonLink } from "@/components/ds/Button";
import { Card } from "@/components/ds/Card";
import { useAuth } from "@/lib/auth";
import { bookingHref } from "@/lib/links";
import { formatDistance, formatDuration, priceLabel } from "@/lib/format";
import { iconForCategory } from "@/lib/trades";
import type { Service } from "@/lib/types";
import { Avatar, RatingStars, VerifiedBadge, useImageFallback } from "./primitives";
import { artisanDisplayName } from "@/lib/artisan";
import { TrustBadges } from "@/components/trust/TrustBadge";

/** Première image réelle du service (galerie, bannière ou URL), sinon null. */
export function serviceImage(service: Service): string | null {
  return service.images?.find((i) => i.image)?.image ?? service.banner ?? service.image_url ?? null;
}

export default function ServiceCard({ service }: { service: Service }) {
  const { user } = useAuth();
  const href = bookingHref(service.id, user);
  const image = serviceImage(service);
  const img = useImageFallback(image);
  const Icon = iconForCategory(service.category_detail?.slug);
  const artisan = service.artisan;
  const name = artisanDisplayName(service) ?? "Artisan";
  const duration = formatDuration(service.duration);
  const distance = formatDistance(service.distance_km);
  const isQuote = service.price_type === "quote" || !service.price;

  return (
    <Card as="article" padding="none" interactive className="group flex h-full flex-col overflow-hidden">
      <div className="relative aspect-[4/3] overflow-hidden">
        {!img.failed ? (
          // Repli sur la tuile catégorie si l'image ne charge pas (URL expirée…).
          // eslint-disable-next-line @next/next/no-img-element
          <img
            ref={img.ref}
            src={image ?? undefined}
            onError={img.onError}
            alt={service.images?.[0]?.alt_text || service.title}
            loading="lazy"
            decoding="async"
            className="h-full w-full object-cover transition duration-slow ease-emphasized group-hover:scale-105"
          />
        ) : (
          <div aria-hidden className="grid h-full w-full place-items-center bg-gradient-to-br from-primarySoft via-white to-accentSoft">
            <Icon className="h-14 w-14 text-primary/70" strokeWidth={1.5} />
          </div>
        )}
        {service.category_detail ? (
          <span className="absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-full bg-white/90 px-3 py-1 text-xs font-semibold text-ink shadow-hair backdrop-blur">
            <Icon aria-hidden className="h-3.5 w-3.5 text-primary" />
            {service.category_detail.name}
          </span>
        ) : null}
        {distance ? (
          <Badge tone="night" icon={<MapPin className="text-accent" />} className="absolute right-3 top-3">
            {distance}
          </Badge>
        ) : null}
      </div>

      <div className="flex flex-1 flex-col gap-3 p-5">
        <h3 className="line-clamp-2 font-display text-base font-bold leading-snug text-ink">{service.title}</h3>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          <span className="font-bold text-primaryDark">{priceLabel(service)}</span>
          {duration ? (
            <span className="inline-flex items-center gap-1 text-ash">
              <Clock aria-hidden className="h-3.5 w-3.5" />
              {duration}
            </span>
          ) : null}
        </div>

        <div className="mt-auto flex items-center gap-3 border-t border-lineSoft pt-3">
          <Avatar name={name} photo={artisan?.photo} size={36} online={artisan?.online} />
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-1.5 truncate text-sm font-semibold text-ink">
              {artisan?.id ? (
                <Link href={`/artisans/${artisan.id}`} className="truncate hover:text-primaryDark hover:underline" aria-label={`Passeport professionnel de ${name}`}>
                  {name}
                </Link>
              ) : (
                <span className="truncate">{name}</span>
              )}
              {artisan && !artisan.badges?.length && artisan.is_verified ? (
                <VerifiedBadge className="!px-1.5" label="Vérifié" />
              ) : artisan && !artisan.is_verified ? (
                <Badge tone="gray" className="shrink-0 !px-1.5 !py-0.5 !text-[11px] !font-medium">
                  Vérification en cours
                </Badge>
              ) : null}
            </p>
            {artisan?.badges?.length ? <TrustBadges badges={artisan.badges} className="mt-1" /> : null}
            <p className="flex flex-wrap items-center gap-x-2 text-xs text-ash">
              <RatingStars rating={artisan?.rating} />
              {artisan && artisan.completed_jobs > 0 ? <span>{artisan.completed_jobs} missions</span> : null}
              {artisan?.commune ? <span className="truncate">{artisan.commune}</span> : null}
              {artisan?.online ? (
                <Badge tone="success" pulse>
                  En ligne
                </Badge>
              ) : null}
            </p>
          </div>
        </div>

        {href ? (
          <ButtonLink
            href={href}
            block
            className="!shadow-hair"
            aria-label={`${isQuote ? "Demander un devis" : "Réserver"} : ${service.title}`}
            rightIcon={<ArrowRight aria-hidden className="h-4 w-4" />}
          >
            {isQuote ? "Demander un devis" : "Réserver"}
          </ButtonLink>
        ) : (
          <p className="rounded-control bg-canvas px-4 py-2.5 text-center text-xs text-ash">
            Réservation ouverte aux comptes client et entreprise.
          </p>
        )}
      </div>
    </Card>
  );
}
