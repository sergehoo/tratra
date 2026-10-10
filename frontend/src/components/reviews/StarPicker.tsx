"use client";
import { Star } from "lucide-react";
import { cx } from "@/components/ds";

/** Note de 1 à 5 (radiogroup natif au clavier ; cliquer deux fois sur la même note l'efface si `clearable`). */
export function StarPicker({
  label,
  value,
  onChange,
  clearable = false,
  size = "md",
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  clearable?: boolean;
  size?: "sm" | "md";
}) {
  const box = size === "sm" ? "h-9 w-9" : "h-11 w-11";
  const icon = size === "sm" ? "h-5 w-5" : "h-7 w-7";
  return (
    <div role="radiogroup" aria-label={label} className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={value === n}
          aria-label={`${n} sur 5`}
          onClick={() => onChange(clearable && value === n ? 0 : n)}
          className={cx(box, "grid place-items-center rounded-xl transition hover:bg-lineSoft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary")}
        >
          <Star aria-hidden className={cx(icon, n <= value ? "fill-accent text-accent" : "text-fog")} />
        </button>
      ))}
    </div>
  );
}
