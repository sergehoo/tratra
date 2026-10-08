"use client";
import type { ReactNode } from "react";
import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from "lucide-react";
import { cx } from "./cx";

export type AlertTone = "info" | "success" | "warning" | "danger" | "brand";

const TONES: Record<AlertTone, { box: string; icon: string; Icon: typeof Info }> = {
  info: { box: "border-info/25 bg-infoSoft text-infoInk", icon: "text-info", Icon: Info },
  success: { box: "border-success/25 bg-successSoft text-successInk", icon: "text-success", Icon: CircleCheck },
  warning: { box: "border-warning/30 bg-warningSoft text-warningInk", icon: "text-warning", Icon: TriangleAlert },
  danger: { box: "border-danger/25 bg-dangerSoft text-dangerInk", icon: "text-danger", Icon: CircleAlert },
  brand: { box: "border-primary/15 bg-primarySoft text-primaryDark", icon: "text-primary", Icon: Info },
};

/**
 * Message contextuel. `danger`/`warning` sont annoncés immédiatement (role="alert"),
 * les autres poliment (role="status").
 */
export function Alert({
  tone = "info",
  title,
  children,
  action,
  icon,
  onDismiss,
  className = "",
}: {
  tone?: AlertTone;
  title?: ReactNode;
  children?: ReactNode;
  /** Bouton/lien d'action sous le message. */
  action?: ReactNode;
  /** Remplace l'icône par défaut. */
  icon?: ReactNode;
  onDismiss?: () => void;
  className?: string;
}) {
  const t = TONES[tone];
  const assertive = tone === "danger" || tone === "warning";
  return (
    <div
      role={assertive ? "alert" : "status"}
      className={cx("flex items-start gap-3 rounded-panel border p-4 text-sm", t.box, className)}
    >
      <span aria-hidden className={cx("mt-0.5 shrink-0 [&>svg]:h-5 [&>svg]:w-5", t.icon)}>
        {icon ?? <t.Icon />}
      </span>
      <div className="min-w-0 flex-1 leading-relaxed">
        {title ? <p className="font-semibold">{title}</p> : null}
        {children ? <div className={cx(title && "mt-0.5", "[&_a]:font-semibold [&_a]:underline")}>{children}</div> : null}
        {action ? <div className="mt-2.5">{action}</div> : null}
      </div>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Fermer le message"
          className="-m-1 grid h-8 w-8 shrink-0 place-items-center rounded-lg opacity-70 transition hover:bg-black/5 hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current"
        >
          <X aria-hidden className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}
