"use client";
import Link from "next/link";
import { ArrowRight, Clock, MapPin } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { bookingHref } from "@/lib/links";
import { formatDistance, formatDuration, priceLabel } from "@/lib/format";
import { iconForCategory } from "@/lib/trades";
import type { Service } from "@/lib/types";
import { Avatar, OnlineDot, RatingStars, VerifiedBadge, useImageFallback } from "./primitives";

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
  const name = artisan?.display_name ?? service.handyman_detail?.first_name ?? "Artisan";
  const duration = formatDuration(service.duration);
  const distance = formatDistance(service.distance_km);
  const isQuote = service.price_type === "quote" || !service.price;

  return (
    <article className="group flex h-full flex-col overflow-hidden rounded-3xl border border-slate-100 bg-white shadow-soft transition duration-300 hover:-translate-y-1 hover:shadow-strong">
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
            className="h-full w-full object-cover transition duration-500 group-hover:scale-105"
          />
        ) : (
          <div aria-hidden className="grid h-full w-full place-items-center bg-gradient-to-br from-primarySoft via-white to-accentSoft">
            <Icon className="h-14 w-14 text-primary/70" strokeWidth={1.5} />
          </div>
        )}
        {service.category_detail ? (
          <span className="absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-full bg-white/90 px-3 py-1 text-xs font-semibold text-ink shadow-sm backdrop-blur">
            <Icon aria-hidden className="h-3.5 w-3.5 text-primary" />
            {service.category_detail.name}
          </span>
        ) : null}
        {distance ? (
          <span className="absolute right-3 top-3 inline-flex items-center gap-1 rounded-full bg-night/80 px-2.5 py-1 text-xs font-semibold text-white backdrop-blur">
            <MapPin aria-hidden className="h-3.5 w-3.5 text-accent" />
            {distance}
          </span>
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

        <div className="mt-auto flex items-center gap-3 border-t border-slate-100 pt-3">
          <Avatar name={name} photo={artisan?.photo} size={36} online={artisan?.online} />
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-1.5 truncate text-sm font-semibold text-ink">
              <span className="truncate">{name}</span>
              {artisan?.is_verified ? (
                <VerifiedBadge className="!px-1.5" label="Vérifié" />
              ) : artisan ? (
                <span className="shrink-0 rounded-full bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-ash">
                  Vérification en cours
                </span>
              ) : null}
            </p>
            <p className="flex flex-wrap items-center gap-x-2 text-xs text-ash">
              <RatingStars rating={artisan?.rating} />
              {artisan && artisan.completed_jobs > 0 ? <span>{artisan.completed_jobs} missions</span> : null}
              {artisan?.commune ? <span className="truncate">{artisan.commune}</span> : null}
              {artisan?.online ? <OnlineDot /> : null}
            </p>
          </div>
        </div>

        {href ? (
          <Link
            href={href}
            className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-2xl bg-primary px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-primaryDark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
            aria-label={`${isQuote ? "Demander un devis" : "Réserver"} : ${service.title}`}
          >
            {isQuote ? "Demander un devis" : "Réserver"}
            <ArrowRight aria-hidden className="h-4 w-4" />
          </Link>
        ) : (
          <p className="rounded-2xl bg-slate-50 px-4 py-2.5 text-center text-xs text-ash">
            Réservation ouverte aux comptes client et entreprise.
          </p>
        )}
      </div>
    </article>
  );
}
