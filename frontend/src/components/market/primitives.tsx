"use client";
import { BadgeCheck, Star } from "lucide-react";
import { formatRating } from "@/lib/format";

// Briques génériques déplacées dans le Design System (ré-exportées pour compatibilité).
export { Avatar, useImageFallback } from "@/components/ds/Avatar";
export { EmptyState } from "@/components/ds/EmptyState";

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
        <Star key={i} aria-hidden className={`h-4 w-4 ${i < v ? "fill-accent text-accent" : "text-line"}`} />
      ))}
    </span>
  );
}

/** Indicateur « en ligne maintenant » (présence réelle de l'artisan). */
export function OnlineDot({ label = "En ligne", className = "" }: { label?: string; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-semibold text-successInk ${className}`}>
      <span aria-hidden className="h-2 w-2 animate-pulseDot rounded-full bg-success" />
      {label}
    </span>
  );
}
