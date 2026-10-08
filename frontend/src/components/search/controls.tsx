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
      className={`group flex min-h-[56px] w-full items-center gap-3 rounded-2xl border px-3.5 py-3 text-left transition disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS_RING} ${
        pressed
          ? "border-primary/40 bg-primarySoft"
          : "border-slate-200 bg-white hover:border-primary/30 hover:bg-slate-50"
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
        className={`relative h-6 w-11 shrink-0 rounded-full transition ${pressed ? "bg-primary" : "bg-slate-300"}`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${
            pressed ? "left-[22px]" : "left-0.5"
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
            className={`min-h-[44px] rounded-xl border px-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS_RING} ${
              active
                ? "border-primary bg-primary text-white shadow-[0_6px_18px_rgba(46,139,87,0.28)]"
                : "border-slate-200 bg-white text-ink hover:border-primary/40 hover:bg-primarySoft/60"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
