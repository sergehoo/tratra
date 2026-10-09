"use client";
import { useEffect, useRef } from "react";
import { cx } from "./cx";

/**
 * Saisie d'un code à usage unique (6 chiffres par défaut) — miroir de `TratraOtpInput` (Flutter).
 * Un seul champ réel (clavier numérique, collage, saisie automatique du SMS) rendu en cases.
 */
export function OtpInput({
  value,
  onChange,
  onComplete,
  length = 6,
  disabled,
  invalid,
  autoFocus,
  label = "Code de vérification",
  describedBy,
  className = "",
}: {
  value: string;
  onChange: (value: string) => void;
  onComplete?: (value: string) => void;
  length?: number;
  disabled?: boolean;
  invalid?: boolean;
  autoFocus?: boolean;
  label?: string;
  describedBy?: string;
  className?: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const active = Math.min(value.length, length - 1);

  // Le champ est désactivé pendant une vérification : on rend le focus dès qu'il redevient actif.
  useEffect(() => {
    if (!disabled && autoFocus) ref.current?.focus();
  }, [disabled, autoFocus]);

  return (
    <div className={cx("relative", className)} onClick={() => ref.current?.focus()}>
      <div aria-hidden className="grid gap-2 sm:gap-3" style={{ gridTemplateColumns: `repeat(${length}, minmax(0, 1fr))` }}>
        {Array.from({ length }, (_, i) => {
          const focused = !disabled && i === active;
          return (
            <div
              key={i}
              className={cx(
                "grid h-14 place-items-center rounded-control border bg-white font-display text-2xl font-extrabold text-ink transition duration-200",
                disabled && "bg-canvas",
                invalid
                  ? "border-danger ring-2 ring-danger/20"
                  : focused
                    ? "border-primary ring-4 ring-primary/15"
                    : value[i]
                      ? "border-fog"
                      : "border-line",
              )}
            >
              {value[i] ?? ""}
            </div>
          );
        })}
      </div>
      <input
        ref={ref}
        value={value}
        disabled={disabled}
        autoFocus={autoFocus}
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]*"
        maxLength={length}
        aria-label={label}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        onChange={(e) => {
          const next = e.target.value.replace(/\D/g, "").slice(0, length);
          onChange(next);
          if (next.length === length) onComplete?.(next);
        }}
        className="absolute inset-0 h-full w-full cursor-text opacity-0 focus:outline-none"
      />
    </div>
  );
}
