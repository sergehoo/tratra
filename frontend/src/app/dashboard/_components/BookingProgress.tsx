import { Check, CircleX } from "lucide-react";
import { cx } from "@/components/ds";
import { statusView } from "@/lib/status";

/** Étapes du parcours d'une réservation (lecture seule : le statut vient de l'API). */
const FLOW = ["pending", "confirmed", "in_progress", "completed"] as const;

/**
 * Suivi visuel du statut réel d'une réservation. Une réservation annulée sort
 * du parcours : on l'indique plutôt que de simuler une progression.
 */
export function BookingProgress({ status }: { status: string }) {
  if (status === "cancelled") {
    return (
      <p className="flex items-center gap-3 text-sm font-medium text-inkSoft">
        <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-lineSoft text-ash">
          <CircleX className="h-[18px] w-[18px]" />
        </span>
        Cette réservation a été annulée.
      </p>
    );
  }

  const current = FLOW.indexOf(status as (typeof FLOW)[number]);
  if (current < 0) return null;
  const finished = status === "completed";

  return (
    <ol className="grid grid-cols-4" aria-label="Avancement de la réservation">
      {FLOW.map((step, index) => {
        const state = finished || index < current ? "done" : index === current ? "current" : "todo";
        const label = statusView("booking", step).label;
        return (
          <li key={step} aria-current={state === "current" ? "step" : undefined} className="flex flex-col items-center gap-2 text-center">
            <div className="flex w-full items-center">
              <span aria-hidden className={cx("h-0.5 flex-1 rounded-full", index === 0 ? "bg-transparent" : index <= current ? "bg-primary" : "bg-line")} />
              <span
                aria-hidden
                className={cx(
                  "grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-bold transition-colors duration-base",
                  state === "done" && "bg-primaryDark text-white",
                  state === "current" && "bg-accent text-ink shadow-glowAccent ring-4 ring-accentSoft",
                  state === "todo" && "bg-lineSoft text-ash",
                )}
              >
                {state === "done" ? <Check className="h-4 w-4" strokeWidth={3} /> : index + 1}
              </span>
              <span
                aria-hidden
                className={cx("h-0.5 flex-1 rounded-full", index === FLOW.length - 1 ? "bg-transparent" : index < current ? "bg-primary" : "bg-line")}
              />
            </div>
            <span className={cx("text-xs font-semibold leading-tight", state === "todo" ? "text-ash" : "text-ink")}>
              {label}
              <span className="sr-only">{state === "done" ? " (terminée)" : state === "current" ? " (étape actuelle)" : " (à venir)"}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
