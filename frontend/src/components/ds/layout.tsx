import type { ReactNode } from "react";
import { cx } from "./cx";

/** Conteneur de page : 1280 px max, gouttières 16 px (mobile) / 24 px (≥ sm). */
export const CONTAINER = "mx-auto w-full max-w-7xl px-4 sm:px-6";

/** Espacement vertical commun des sections marketing. */
export const SECTION_Y = "py-20 md:py-28";

export function Container({
  children,
  className = "",
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "main" | "section" | "header" | "footer";
}) {
  return <Tag className={cx(CONTAINER, className)}>{children}</Tag>;
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
      className={cx(
        "inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-[11px] font-bold uppercase tracking-[0.16em]",
        tones[tone],
        className,
      )}
    >
      {children}
    </p>
  );
}

/** En-tête de section marketing : sur-titre, <h2> (cible d'aria-labelledby) et chapô. */
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
    <div className={cx("max-w-2xl", align === "center" && "mx-auto text-center", className)}>
      {eyebrow ? <Eyebrow tone={dark ? "dark" : "light"}>{eyebrow}</Eyebrow> : null}
      <h2
        id={id}
        className={cx(
          "mt-4 font-display text-[1.85rem] font-extrabold leading-[1.12] tracking-tight [text-wrap:balance] sm:text-4xl lg:text-[2.75rem]",
          dark ? "text-white" : "text-ink",
        )}
      >
        {title}
      </h2>
      {description ? (
        <p className={cx("mt-4 text-base leading-relaxed sm:text-lg", dark ? "text-white/75" : "text-ash")}>
          {description}
        </p>
      ) : null}
    </div>
  );
}
