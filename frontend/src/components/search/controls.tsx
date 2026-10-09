"use client";
import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

/** Petits contrôles partagés par le panneau de filtres (bureau + mobile). */

export const FOCUS_RING =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2";

export function FilterSection({
  title,
  titleId,
  hint,
  children,
}: {
  title: string;
  titleId?: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="space-y-3" aria-labelledby={titleId}>
      <div>
        <h3 id={titleId} className="font-display text-sm font-bold uppercase tracking-[0.08em] text-ink">
          {title}
        </h3>
        {hint ? <p className="mt-1 text-xs leading-relaxed text-ash">{hint}</p> : null}
      </div>
      {children}
    </section>
  );
}

/** Interrupteur accessible (bouton à bascule, aria-pressed). */
export function SwitchButton({
  pressed,
  onToggle,
  icon: Icon,
  label,
  description,
  disabled,
}: {
  pressed: boolean;
  onToggle: () => void;
  icon: LucideIcon;
  label: string;
  description?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onToggle}
      disabled={disabled}
      className={`group flex min-h-[56px] w-full items-center gap-3 rounded-panel border px-3.5 py-3 text-left transition duration-base ease-emphasized disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS_RING} ${
        pressed ? "border-primary/40 bg-primarySoft" : "border-line bg-white hover:border-primary/30 hover:bg-canvas"
      }`}
    >
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5 text-sm font-semibold leading-snug text-ink">
          <Icon aria-hidden className={`h-4 w-4 shrink-0 ${pressed ? "text-primaryDark" : "text-primary"}`} />
          {label}
        </span>
        {description ? <span className="mt-0.5 block text-xs leading-snug text-ash">{description}</span> : null}
      </span>
      <span
        aria-hidden
        className={`relative h-6 w-11 shrink-0 rounded-full transition-colors duration-base ease-emphasized ${
          pressed ? "bg-primary" : "bg-fog"
        }`}
      >
        <span
          className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow-hair transition-transform duration-base ease-emphasized ${
            pressed ? "translate-x-5" : "translate-x-0"
          }`}
        />
      </span>
    </button>
  );
}

/** Groupe de boutons à choix unique (aria-pressed), ex. type de tarif, rayon. */
export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  labelledBy,
  columns = 2,
  disabled,
}: {
  options: { value: T; label: string; ariaLabel?: string }[];
  value: T;
  onChange: (value: T) => void;
  labelledBy?: string;
  columns?: 2 | 3 | 4 | 5;
  disabled?: boolean;
}) {
  const cols = { 2: "grid-cols-2", 3: "grid-cols-3", 4: "grid-cols-4", 5: "grid-cols-5" }[columns];
  return (
    <div role="group" aria-labelledby={labelledBy} className={`grid gap-2 ${cols}`}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={String(o.value)}
            type="button"
            aria-pressed={active}
            aria-label={o.ariaLabel}
            disabled={disabled}
            onClick={() => onChange(o.value)}
            className={`min-h-[44px] rounded-control border px-2 text-sm font-semibold transition duration-base ease-emphasized disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS_RING} ${
              active
                ? "border-primaryDark bg-primaryDark text-white shadow-hair"
                : "border-line bg-white text-ink hover:border-primary/40 hover:bg-primarySoft/60"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
