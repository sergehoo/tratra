"use client";
import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { cx } from "./cx";

export interface TabItem<T extends string = string> {
  id: T;
  label: ReactNode;
  /** Compteur réel (ex. nombre d'éléments) — affiché seulement s'il est fourni. */
  count?: number;
}

/**
 * Onglets en pastille (filtre de liste / sections). Sémantique ARIA tablist,
 * navigation clavier ← → Début Fin. Reliez le panneau avec
 * `id="panel-{id}"` + `aria-labelledby="tab-{id}"` si vous affichez des panneaux.
 */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  ariaLabel,
  className = "",
  idPrefix = "tab",
}: {
  items: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  ariaLabel: string;
  className?: string;
  idPrefix?: string;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const i = items.findIndex((t) => t.id === value);
    let next = i;
    if (e.key === "ArrowRight") next = (i + 1) % items.length;
    else if (e.key === "ArrowLeft") next = (i - 1 + items.length) % items.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = items.length - 1;
    else return;
    e.preventDefault();
    const target = items[next];
    onChange(target.id);
    refs.current[target.id]?.focus();
  }

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={cx("scrollbar-none inline-flex max-w-full gap-1 overflow-x-auto rounded-full bg-lineSoft p-1", className)}
    >
      {items.map((t) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[t.id] = el;
            }}
            id={`${idPrefix}-${t.id}`}
            role="tab"
            type="button"
            aria-selected={active}
            aria-controls={`panel-${t.id}`}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(t.id)}
            className={cx(
              "inline-flex min-h-[40px] shrink-0 items-center gap-2 whitespace-nowrap rounded-full px-4 text-sm font-semibold transition duration-200",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
              active ? "bg-white text-ink shadow-soft" : "text-ash hover:text-ink",
            )}
          >
            {t.label}
            {typeof t.count === "number" ? (
              <span
                className={cx(
                  "rounded-full px-2 py-0.5 text-[11px] font-bold leading-none",
                  active ? "bg-primarySoft text-primaryDark" : "bg-white/70 text-ash",
                )}
              >
                {t.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
