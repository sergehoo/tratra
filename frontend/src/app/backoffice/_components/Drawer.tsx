"use client";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cx } from "@/components/ds";

const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';
const WIDTH = { md: "sm:max-w-md", lg: "sm:max-w-xl", xl: "sm:max-w-3xl" } as const;

/**
 * Tiroir latéral pour les formulaires longs (création / modification) : le contexte de la liste reste visible derrière.
 * Même accessibilité qu'une boîte de dialogue : focus piégé puis restitué, Échap, défilement de la page verrouillé, voile cliquable.
 * Plein écran en mobile ; en-tête et pied fixes, seul le contenu défile.
 */
export function Drawer({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  dismissible = true,
  width = "lg",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  /** false : Échap, voile et croix inactifs (enregistrement en cours). */
  dismissible?: boolean;
  width?: keyof typeof WIDTH;
}) {
  const uid = useId();
  const panel = useRef<HTMLDivElement>(null);
  const lastFocus = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const dismissibleRef = useRef(dismissible);
  dismissibleRef.current = dismissible;
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    lastFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusables = () => Array.from(panel.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    const t = setTimeout(() => (focusables()[1] ?? focusables()[0] ?? panel.current)?.focus(), 30);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && dismissibleRef.current) {
        e.stopPropagation();
        onCloseRef.current();
      } else if (e.key === "Tab") {
        const items = focusables();
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(t);
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
      lastFocus.current?.focus?.();
    };
  }, [open]);

  if (!open || !mounted) return null;
  return createPortal(
    <div className="fixed inset-0 z-modal" role="presentation">
      <div className="absolute inset-0 bg-night/55 backdrop-blur-[2px]" onClick={() => dismissible && onClose()} aria-hidden />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${uid}-title`}
        aria-describedby={description ? `${uid}-desc` : undefined}
        tabIndex={-1}
        className={cx("absolute inset-y-0 right-0 flex w-full animate-slideInRight flex-col bg-white shadow-strong focus:outline-none", WIDTH[width])}
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-lineSoft px-5 py-4 sm:px-6">
          <div className="min-w-0">
            <h2 id={`${uid}-title`} className="font-display text-xl font-bold leading-tight text-ink">{title}</h2>
            {description ? <p id={`${uid}-desc`} className="mt-1 text-sm text-ash">{description}</p> : null}
          </div>
          <button type="button" onClick={onClose} disabled={!dismissible} aria-label="Fermer" className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-ash transition hover:bg-lineSoft hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50">
            <X aria-hidden className="h-5 w-5" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5 sm:px-6">{children}</div>
        {footer ? <footer className="flex shrink-0 flex-wrap justify-end gap-3 border-t border-lineSoft bg-canvas px-5 py-4 sm:px-6">{footer}</footer> : null}
      </div>
    </div>,
    document.body,
  );
}
