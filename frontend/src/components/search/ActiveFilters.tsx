"use client";
import { X } from "lucide-react";
import { FOCUS_RING } from "./controls";

export interface ActiveChip {
  key: string;
  label: string;
  onRemove: () => void;
}

/** Filtres appliqués, chacun retirable, + « Tout réinitialiser ». */
export default function ActiveFilters({ chips, onResetAll }: { chips: ActiveChip[]; onResetAll: () => void }) {
  if (!chips.length) return null;
  return (
    <div className="mt-5 flex flex-wrap items-center gap-2">
      <h3 className="sr-only">Filtres actifs</h3>
      <ul className="flex min-w-0 flex-wrap gap-2">
        {chips.map((chip) => (
          <li key={chip.key} className="min-w-0 max-w-full">
            <button
              type="button"
              onClick={chip.onRemove}
              aria-label={`Retirer le filtre : ${chip.label}`}
              className={`group inline-flex min-h-[44px] max-w-full items-center gap-2 rounded-full border border-primary/20 bg-white pl-4 pr-1.5 text-sm font-semibold text-primaryDark shadow-sm transition hover:border-primary/50 ${FOCUS_RING}`}
            >
              <span className="truncate">{chip.label}</span>
              <span
                aria-hidden
                className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primarySoft transition group-hover:bg-primary group-hover:text-white"
              >
                <X className="h-3.5 w-3.5" />
              </span>
            </button>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={onResetAll}
        className={`inline-flex min-h-[44px] items-center rounded-full px-3 text-sm font-semibold text-ink underline decoration-accent decoration-2 underline-offset-4 transition hover:text-primaryDark ${FOCUS_RING}`}
      >
        Tout réinitialiser
      </button>
    </div>
  );
}
