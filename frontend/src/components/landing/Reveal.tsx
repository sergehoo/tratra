"use client";
import type { ReactNode } from "react";
import { m, type Variants } from "framer-motion";

/**
 * Animations d'apparition au défilement (transform + opacity uniquement).
 * Les préférences « mouvement réduit » sont gérées globalement par
 * <MotionConfig reducedMotion="user"> (Providers) : seules les opacités sont
 * alors animées, sans déplacement.
 */

const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

export function Reveal({
  children,
  className,
  delay = 0,
  y = 24,
  amount = 0.12,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
  y?: number;
  amount?: number;
}) {
  return (
    <m.div
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount }}
      transition={{ duration: 0.55, ease: EASE, delay }}
    >
      {children}
    </m.div>
  );
}

function groupVariants(stagger: number, delay: number): Variants {
  return { hidden: {}, show: { transition: { staggerChildren: stagger, delayChildren: delay } } };
}

const ITEM_VARIANTS: Variants = {
  hidden: { opacity: 0, y: 22 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: EASE } },
};

/** Conteneur qui déclenche l'apparition échelonnée de ses <RevealItem>. */
export function RevealGroup({
  children,
  className,
  as = "div",
  stagger = 0.06,
  delay = 0,
  amount = 0.08,
  ariaLabel,
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "ul" | "ol";
  stagger?: number;
  delay?: number;
  amount?: number;
  ariaLabel?: string;
}) {
  const props = {
    className,
    variants: groupVariants(stagger, delay),
    initial: "hidden",
    whileInView: "show",
    viewport: { once: true, amount },
    "aria-label": ariaLabel,
  } as const;
  if (as === "ul") return <m.ul {...props}>{children}</m.ul>;
  if (as === "ol") return <m.ol {...props}>{children}</m.ol>;
  return <m.div {...props}>{children}</m.div>;
}

export function RevealItem({
  children,
  className,
  as = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "li";
}) {
  if (as === "li") {
    return (
      <m.li className={className} variants={ITEM_VARIANTS}>
        {children}
      </m.li>
    );
  }
  return (
    <m.div className={className} variants={ITEM_VARIANTS}>
      {children}
    </m.div>
  );
}

/** Ligne de progression qui se « dessine » (scaleX / scaleY) à l'entrée dans la vue. */
export function GrowLine({
  className = "",
  axis = "x",
  delay = 0.2,
  duration = 1.4,
}: {
  className?: string;
  axis?: "x" | "y";
  delay?: number;
  duration?: number;
}) {
  const from = axis === "x" ? { scaleX: 0 } : { scaleY: 0 };
  const to = axis === "x" ? { scaleX: 1 } : { scaleY: 1 };
  return (
    <m.span
      aria-hidden
      className={`block ${className}`}
      style={{ originX: 0, originY: 0 }}
      initial={from}
      whileInView={to}
      viewport={{ once: true, amount: 0.3 }}
      transition={{ duration, ease: EASE, delay }}
    />
  );
}

/** Élément décoratif qui flotte doucement (boucle verticale). */
export function Float({
  children,
  className,
  distance = 12,
  duration = 7,
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  distance?: number;
  duration?: number;
  delay?: number;
}) {
  return (
    <m.div
      className={className}
      animate={{ y: [0, -distance, 0] }}
      transition={{ duration, delay, repeat: Infinity, ease: "easeInOut" }}
    >
      {children}
    </m.div>
  );
}
