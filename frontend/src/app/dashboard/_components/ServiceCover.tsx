"use client";
import { cx, useImageFallback } from "@/components/ds";
import { iconForCategory } from "@/lib/trades";
import type { Service } from "@/lib/types";

/** Première image réelle du service (galerie, bannière ou URL), sinon null. */
export function serviceImageUrl(service: Service): string | null {
  return service.images?.find((image) => image.image)?.image ?? service.banner ?? service.image_url ?? null;
}

/**
 * Visuel d'un service : photo réelle publiée par l'artisan, sinon tuile de marque
 * avec l'icône de la catégorie (jamais de photo de stock). Le conteneur prend la
 * taille donnée par `className` (ex. `aspect-[16/9]`).
 */
export function ServiceCover({
  service,
  alt = "",
  className = "",
}: {
  service: Service;
  /** Vide quand le titre du service est déjà lu à côté (image décorative). */
  alt?: string;
  className?: string;
}) {
  const url = serviceImageUrl(service);
  const image = useImageFallback(url);
  const Icon = iconForCategory(service.category_detail?.slug);

  return (
    <div className={cx("relative overflow-hidden bg-gradient-to-br from-primarySoft via-white to-accentSoft", className)}>
      {!image.failed ? (
        // Médias servis par l'API (origine autorisée par la CSP) : <img> natif, repli sur la tuile si l'URL a expiré.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          ref={image.ref}
          src={url ?? undefined}
          onError={image.onError}
          alt={alt}
          loading="lazy"
          decoding="async"
          className="h-full w-full object-cover transition duration-slow ease-emphasized group-hover:scale-105"
        />
      ) : (
        <div aria-hidden className="grid h-full w-full place-items-center">
          <Icon className="h-12 w-12 text-primary/70" strokeWidth={1.5} />
        </div>
      )}
    </div>
  );
}
