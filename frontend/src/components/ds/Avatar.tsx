"use client";
import { useCallback, useState } from "react";
import { cx } from "./cx";

/**
 * Repli d'une image distante (URL signée expirée, origine bloquée…) : `failed`
 * passe à vrai si l'image échoue, y compris quand l'échec a eu lieu sur le HTML
 * serveur avant l'hydratation (événement que React ne voit pas). Réarmé dès que
 * l'URL change (ex. URL fraîchement signée après rechargement des données).
 */
export function useImageFallback(src: string | null | undefined) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const onError = useCallback(() => {
    if (src) setFailedSrc(src);
  }, [src]);
  const ref = useCallback(
    (img: HTMLImageElement | null) => {
      if (img && src && img.complete && img.naturalWidth === 0) setFailedSrc(src);
    },
    [src],
  );
  return { failed: !src || failedSrc === src, ref, onError };
}

export function initials(name: string): string {
  const parts = name.replace(/\./g, "").split(/\s+/).filter(Boolean);
  return (parts[0]?.[0] ?? "T").toUpperCase() + (parts[1]?.[0] ?? "").toUpperCase();
}

/** Photo réelle, sinon initiales sur dégradé de marque (jamais de photo de stock), y compris si la photo ne charge pas. */
export function Avatar({
  name,
  photo,
  size = 48,
  online,
  className = "",
}: {
  name: string;
  photo?: string | null;
  size?: number;
  online?: boolean;
  className?: string;
}) {
  const img = useImageFallback(photo);
  return (
    <span className={cx("relative inline-block shrink-0", className)} style={{ width: size, height: size }}>
      {!img.failed ? (
        // Médias servis par l'API (origine autorisée par la CSP) : <img> natif.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          ref={img.ref}
          src={photo ?? undefined}
          onError={img.onError}
          alt={`Photo de ${name}`}
          width={size}
          height={size}
          loading="lazy"
          decoding="async"
          className="h-full w-full rounded-full object-cover ring-2 ring-white"
        />
      ) : (
        <span
          aria-hidden
          className="grid h-full w-full place-items-center rounded-full bg-gradient-to-br from-primary to-primaryDark font-display font-bold text-white ring-2 ring-white"
          style={{ fontSize: Math.max(12, size / 2.8) }}
        >
          {initials(name)}
        </span>
      )}
      {online ? (
        <span className="absolute bottom-0 right-0 block h-3 w-3 rounded-full bg-success ring-2 ring-white" aria-label="En ligne" />
      ) : null}
    </span>
  );
}
