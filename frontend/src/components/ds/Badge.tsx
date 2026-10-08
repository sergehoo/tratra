import type { ReactNode } from "react";
import { cx } from "./cx";

export type BadgeTone =
  | "primary"
  | "accent"
  | "night"
  | "gray"
  | "success"
  | "warning"
  | "danger"
  | "info";

const TONES: Record<BadgeTone, { box: string; dot: string }> = {
  primary: { box: "bg-primarySoft text-primaryDark", dot: "bg-primary" },
  accent: { box: "bg-accentSoft text-ink ring-1 ring-inset ring-accent/50", dot: "bg-accentDark" },
  night: { box: "bg-night text-white", dot: "bg-accent" },
  gray: { box: "bg-lineSoft text-inkSoft", dot: "bg-fog" },
  success: { box: "bg-successSoft text-successInk", dot: "bg-success" },
  warning: { box: "bg-warningSoft text-warningInk", dot: "bg-warning" },
  danger: { box: "bg-dangerSoft text-dangerInk", dot: "bg-danger" },
  info: { box: "bg-infoSoft text-infoInk", dot: "bg-info" },
};

export function Badge({
  children,
  tone = "primary",
  dot,
  pulse,
  icon,
  className = "",
}: {
  children: ReactNode;
  tone?: BadgeTone;
  /** Pastille colorée devant le libellé. */
  dot?: boolean;
  /** Pastille animée (statut « en direct » : en cours, en ligne). */
  pulse?: boolean;
  icon?: ReactNode;
  className?: string;
}) {
  const t = TONES[tone];
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold leading-none",
        t.box,
        className,
      )}
    >
      {dot || pulse ? (
        <span aria-hidden className={cx("h-1.5 w-1.5 rounded-full", t.dot, pulse && "animate-pulseDot")} />
      ) : null}
      {icon ? <span aria-hidden className="-ml-0.5 [&>svg]:h-3.5 [&>svg]:w-3.5">{icon}</span> : null}
      {children}
    </span>
  );
}
