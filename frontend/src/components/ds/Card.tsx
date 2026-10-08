import type { ElementType, HTMLAttributes, ReactNode } from "react";
import { cx } from "./cx";

export type CardVariant = "default" | "flat" | "soft" | "accent" | "night";
export type CardPadding = "none" | "sm" | "md" | "lg";
export type CardRadius = "panel" | "card";

const VARIANTS: Record<CardVariant, string> = {
  default: "border border-lineSoft bg-white shadow-soft",
  flat: "border border-line bg-white",
  soft: "border border-primary/10 bg-primarySoft/60",
  accent: "border border-accent/40 bg-accentSoft",
  night: "tt-night border border-white/10 bg-night text-white shadow-strong",
};
const PADDING: Record<CardPadding, string> = {
  none: "",
  sm: "p-4",
  md: "p-5 sm:p-6",
  lg: "p-6 sm:p-8",
};
const RADIUS: Record<CardRadius, string> = { panel: "rounded-panel", card: "rounded-card" };

export type CardProps = HTMLAttributes<HTMLElement> & {
  variant?: CardVariant;
  padding?: CardPadding;
  /** `card` (24 px) pour les cartes éditoriales, `panel` (16 px) pour les lignes denses. */
  radius?: CardRadius;
  /** Effet de survol (lift + ombre) — pour les cartes cliquables. */
  interactive?: boolean;
  as?: ElementType;
};

export function Card({
  variant = "default",
  padding = "md",
  radius = "card",
  interactive,
  as: Tag = "div",
  className = "",
  children,
  ...props
}: CardProps) {
  return (
    <Tag
      className={cx(
        VARIANTS[variant],
        PADDING[padding],
        RADIUS[radius],
        interactive &&
          "transition duration-300 ease-emphasized hover:-translate-y-0.5 hover:border-primary/20 hover:shadow-strong",
        className,
      )}
      {...props}
    >
      {children}
    </Tag>
  );
}

/** En-tête de carte : titre, description et zone d'action alignée à droite. */
export function CardHeader({
  title,
  description,
  action,
  icon,
  className = "",
  as: Heading = "h2",
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
  as?: "h2" | "h3" | "h4";
}) {
  return (
    <div className={cx("mb-4 flex flex-wrap items-start justify-between gap-3", className)}>
      <div className="flex min-w-0 items-start gap-3">
        {icon ? (
          <span aria-hidden className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primarySoft text-primary">
            {icon}
          </span>
        ) : null}
        <div className="min-w-0">
          <Heading className="font-display text-lg font-bold leading-tight text-ink [.tt-night_&]:text-white">{title}</Heading>
          {description ? <p className="mt-1 text-sm text-ash [.tt-night_&]:text-white/70">{description}</p> : null}
        </div>
      </div>
      {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
    </div>
  );
}

/** Indicateur chiffré (tableaux de bord). Le libellé est sous la valeur. */
export function Stat({
  label,
  value,
  hint,
  icon,
  tone = "primary",
  className = "",
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  icon?: ReactNode;
  tone?: "primary" | "accent" | "night";
  className?: string;
}) {
  const tile = {
    primary: "bg-primarySoft text-primary",
    accent: "bg-accentSoft text-accentDark",
    night: "bg-night text-accent",
  }[tone];
  return (
    <Card padding="md" radius="card" className={cx("flex items-start gap-4", className)}>
      {icon ? (
        <span aria-hidden className={cx("grid h-12 w-12 shrink-0 place-items-center rounded-2xl", tile)}>
          {icon}
        </span>
      ) : null}
      <div className="min-w-0">
        <p className="font-display text-3xl font-extrabold leading-none tracking-tight text-ink">{value}</p>
        <p className="mt-1.5 text-sm font-medium text-ash">{label}</p>
        {hint ? <p className="mt-1 text-xs text-fog">{hint}</p> : null}
      </div>
    </Card>
  );
}
