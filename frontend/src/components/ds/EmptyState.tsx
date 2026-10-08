import type { ReactNode } from "react";
import { cx } from "./cx";

/** État vide honnête : explique la situation réelle et propose une action utile. */
export function EmptyState({
  icon,
  title,
  description,
  actions,
  className = "",
  tone = "light",
  compact,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
  tone?: "light" | "dark";
  /** Version réduite pour l'intérieur d'une carte ou d'un tableau. */
  compact?: boolean;
}) {
  const dark = tone === "dark";
  return (
    <div
      className={cx(
        "flex flex-col items-center rounded-card border text-center",
        compact ? "px-5 py-8" : "px-6 py-10 sm:py-12",
        dark ? "border-white/10 bg-white/5 text-white" : "border-dashed border-line bg-white",
        className,
      )}
    >
      {icon ? (
        <span
          className={cx(
            "mb-4 grid h-14 w-14 place-items-center rounded-2xl [&>svg]:h-6 [&>svg]:w-6",
            dark ? "bg-white/10 text-accent" : "bg-primarySoft text-primary",
          )}
        >
          {icon}
        </span>
      ) : null}
      <h3 className={cx("font-display text-lg font-bold", dark ? "text-white" : "text-ink")}>{title}</h3>
      {description ? (
        <p className={cx("mt-2 max-w-md text-sm leading-relaxed", dark ? "text-white/70" : "text-ash")}>{description}</p>
      ) : null}
      {actions ? <div className="mt-5 flex flex-wrap justify-center gap-3">{actions}</div> : null}
    </div>
  );
}
