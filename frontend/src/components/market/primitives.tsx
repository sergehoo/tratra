"use client";
import { useCallback, useState, type ReactNode } from "react";
import { BadgeCheck, Star } from "lucide-react";
import { formatRating } from "@/lib/format";

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

/** Badge « Vérifié » : affiché uniquement si le profil a passé le KYC. */
export function VerifiedBadge({ className = "", label = "Vérifié" }: { className?: string; label?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full bg-primarySoft px-2 py-0.5 text-xs font-semibold text-primaryDark ${className}`}
    >
      <BadgeCheck aria-hidden className="h-3.5 w-3.5" />
      {label}
    </span>
  );
}

/**
 * Note réelle sur 5. N'affiche RIEN si aucune note (pas de « 5,0 » par défaut).
 */
export function RatingStars({
  rating,
  count,
  size = "sm",
  className = "",
}: {
  rating: number | null | undefined;
  count?: number | null;
  size?: "sm" | "md";
  className?: string;
}) {
  const label = formatRating(rating);
  if (!label) return null;
  const icon = size === "md" ? "h-4 w-4" : "h-3.5 w-3.5";
  return (
    <span
      className={`inline-flex items-center gap-1 font-semibold text-ink ${size === "md" ? "text-sm" : "text-xs"} ${className}`}
      aria-label={`Note ${label} sur 5${count ? `, ${count} avis` : ""}`}
    >
      <Star aria-hidden className={`${icon} fill-accent text-accent`} />
      {label}
      {count ? <span className="font-normal text-ash">({count})</span> : null}
    </span>
  );
}

/** Étoiles pleines/vides pour un avis (valeur entière 1–5). */
export function StarRow({ value, className = "" }: { value: number; className?: string }) {
  const v = Math.max(0, Math.min(5, Math.round(value)));
  return (
    <span className={`inline-flex gap-0.5 ${className}`} role="img" aria-label={`${v} étoiles sur 5`}>
      {Array.from({ length: 5 }, (_, i) => (
        <Star key={i} aria-hidden className={`h-4 w-4 ${i < v ? "fill-accent text-accent" : "text-slate-300"}`} />
      ))}
    </span>
  );
}

function initials(name: string): string {
  const parts = name.replace(/\./g, "").split(/\s+/).filter(Boolean);
  return (parts[0]?.[0] ?? "T").toUpperCase() + (parts[1]?.[0] ?? "").toUpperCase();
}

/** Photo réelle de l'artisan, sinon initiales (jamais de photo de stock), y compris si la photo ne charge pas. */
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
    <span className={`relative inline-block shrink-0 ${className}`} style={{ width: size, height: size }}>
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
        <span className="absolute bottom-0 right-0 block h-3 w-3 rounded-full bg-emerald-500 ring-2 ring-white" aria-label="En ligne" />
      ) : null}
    </span>
  );
}

/** Indicateur « en ligne maintenant » (présence réelle de l'artisan). */
export function OnlineDot({ label = "En ligne", className = "" }: { label?: string; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700 ${className}`}>
      <span aria-hidden className="h-2 w-2 animate-pulseDot rounded-full bg-emerald-500" />
      {label}
    </span>
  );
}

/** État vide honnête : explique la situation réelle et propose une action utile. */
export function EmptyState({
  icon,
  title,
  description,
  actions,
  className = "",
  tone = "light",
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
  tone?: "light" | "dark";
}) {
  const dark = tone === "dark";
  return (
    <div
      className={`flex flex-col items-center rounded-3xl border px-6 py-10 text-center ${
        dark ? "border-white/10 bg-white/5 text-white" : "border-dashed border-slate-200 bg-white"
      } ${className}`}
    >
      {icon ? (
        <span className={`mb-4 grid h-14 w-14 place-items-center rounded-2xl ${dark ? "bg-white/10 text-accent" : "bg-primarySoft text-primary"}`}>
          {icon}
        </span>
      ) : null}
      <h3 className={`font-display text-lg font-bold ${dark ? "text-white" : "text-ink"}`}>{title}</h3>
      {description ? (
        <p className={`mt-2 max-w-md text-sm ${dark ? "text-white/70" : "text-ash"}`}>{description}</p>
      ) : null}
      {actions ? <div className="mt-5 flex flex-wrap justify-center gap-3">{actions}</div> : null}
    </div>
  );
}
