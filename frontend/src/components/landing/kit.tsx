import Link from "next/link";
import type { ReactNode } from "react";

/**
 * Petites briques de mise en page de la landing (compatibles Server Components :
 * aucun hook, aucun "use client").
 */

export const CONTAINER = "mx-auto w-full max-w-7xl px-4 sm:px-6";

/** Espacement vertical commun des sections. */
export const SECTION_Y = "py-20 md:py-28";

type BtnVariant = "primary" | "accent" | "night" | "outline" | "outlineLight" | "outlineNight";
type BtnSize = "md" | "lg";

const BASE =
  "inline-flex min-h-[44px] items-center justify-center gap-2 rounded-full font-semibold transition duration-200 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 active:scale-[0.98] " +
  "disabled:cursor-not-allowed disabled:opacity-60";

/**
 * Variantes de boutons. Le texte blanc est posé sur `primaryDark` (contraste
 * AA ≥ 4.5:1) ; le vert de marque `primary` reste réservé aux grands titres,
 * icônes et surfaces décoratives.
 */
const VARIANTS: Record<BtnVariant, string> = {
  primary:
    "bg-primaryDark text-white shadow-glow hover:-translate-y-0.5 hover:bg-[#185736] focus-visible:ring-accent focus-visible:ring-offset-white",
  accent:
    "bg-accent text-ink shadow-[0_12px_32px_-8px_rgba(246,201,14,.55)] hover:-translate-y-0.5 hover:bg-[#ffd42e] focus-visible:ring-white focus-visible:ring-offset-night",
  night:
    "bg-night text-white shadow-strong hover:-translate-y-0.5 hover:bg-nightSoft focus-visible:ring-night focus-visible:ring-offset-accent",
  outline:
    "border border-slate-200 bg-white text-ink hover:border-primary/50 hover:text-primaryDark focus-visible:ring-accent focus-visible:ring-offset-white",
  outlineLight:
    "border border-white/25 bg-white/5 text-white backdrop-blur hover:border-white/50 hover:bg-white/10 focus-visible:ring-accent focus-visible:ring-offset-night",
  outlineNight:
    "border-2 border-night/80 text-night hover:bg-night hover:text-white focus-visible:ring-night focus-visible:ring-offset-accent",
};

const SIZES: Record<BtnSize, string> = {
  md: "px-5 py-2.5 text-sm",
  lg: "min-h-[52px] px-6 py-3.5 text-[15px] sm:text-base",
};

export function btn(variant: BtnVariant = "primary", size: BtnSize = "md", extra = ""): string {
  return `${BASE} ${VARIANTS[variant]} ${SIZES[size]} ${extra}`.trim();
}

/** Lien-bouton vers une route RÉELLE de l'application. */
export function CtaLink({
  href,
  children,
  variant = "primary",
  size = "md",
  className = "",
  ariaLabel,
}: {
  href: string;
  children: ReactNode;
  variant?: BtnVariant;
  size?: BtnSize;
  className?: string;
  ariaLabel?: string;
}) {
  return (
    <Link href={href} className={btn(variant, size, className)} aria-label={ariaLabel}>
      {children}
    </Link>
  );
}

/** Sur-titre de section (pastille). */
export function Eyebrow({
  children,
  tone = "light",
  className = "",
}: {
  children: ReactNode;
  tone?: "light" | "dark" | "accent";
  className?: string;
}) {
  const tones = {
    light: "bg-primarySoft text-primaryDark",
    dark: "bg-white/10 text-accent ring-1 ring-inset ring-white/10",
    accent: "bg-night/10 text-night",
  } as const;
  return (
    <p
      className={`inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-[11px] font-bold uppercase tracking-[0.16em] ${tones[tone]} ${className}`}
    >
      {children}
    </p>
  );
}

/** En-tête de section : sur-titre, <h2> (cible d'aria-labelledby) et chapô. */
export function SectionHeading({
  id,
  eyebrow,
  title,
  description,
  tone = "light",
  align = "left",
  className = "",
}: {
  id: string;
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  tone?: "light" | "dark";
  align?: "left" | "center";
  className?: string;
}) {
  const dark = tone === "dark";
  return (
    <div className={`max-w-2xl ${align === "center" ? "mx-auto text-center" : ""} ${className}`}>
      {eyebrow ? <Eyebrow tone={dark ? "dark" : "light"}>{eyebrow}</Eyebrow> : null}
      <h2
        id={id}
        className={`mt-4 font-display text-[1.85rem] font-extrabold leading-[1.12] tracking-tight [text-wrap:balance] sm:text-4xl lg:text-[2.75rem] ${
          dark ? "text-white" : "text-ink"
        }`}
      >
        {title}
      </h2>
      {description ? (
        <p className={`mt-4 text-base leading-relaxed sm:text-lg ${dark ? "text-white/75" : "text-ash"}`}>
          {description}
        </p>
      ) : null}
    </div>
  );
}
