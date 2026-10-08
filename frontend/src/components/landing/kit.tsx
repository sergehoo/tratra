import Link from "next/link";
import type { ReactNode } from "react";
import { buttonClass, type ButtonSize, type ButtonVariant } from "@/components/ds/Button";

/**
 * Briques de mise en page de la landing — désormais portées par le Design System
 * (`@/components/ds`). Ce module reste le point d'import historique de la landing
 * (compatible Server Components : aucun hook, aucun "use client").
 */
export { CONTAINER, SECTION_Y, Eyebrow, SectionHeading } from "@/components/ds/layout";

type BtnVariant = Extract<ButtonVariant, "primary" | "accent" | "night" | "outline" | "outlineLight" | "outlineNight">;
type BtnSize = Extract<ButtonSize, "md" | "lg">;

export function btn(variant: BtnVariant = "primary", size: BtnSize = "md", extra = ""): string {
  return buttonClass(variant, size, extra);
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
