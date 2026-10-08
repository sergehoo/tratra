import tokens from "../../../design-system/tokens.json";

/** Courbes et durées du Design System (source : design-system/tokens.json). */
export const EASE = tokens.motion.easing.emphasized as [number, number, number, number];
export const EASE_STANDARD = tokens.motion.easing.standard as [number, number, number, number];

const ms = tokens.motion.duration;
export const DURATION = {
  fast: ms.fast / 1000,
  base: ms.base / 1000,
  slow: ms.slow / 1000,
  hero: ms.hero / 1000,
} as const;

/** Variantes framer-motion réutilisables (avec `m.*`, LazyMotion est fourni par <Providers>). */
export const fadeUp = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: DURATION.slow, ease: EASE } },
};
export const scaleIn = {
  hidden: { opacity: 0, scale: 0.96 },
  show: { opacity: 1, scale: 1, transition: { duration: DURATION.base, ease: EASE } },
};
export const sheetUp = {
  hidden: { opacity: 0, y: 32 },
  show: { opacity: 1, y: 0, transition: { duration: DURATION.slow, ease: EASE } },
};
