"use client";
import { useEffect, useId, useRef, type ReactNode, type RefObject } from "react";
import { AnimatePresence, m } from "framer-motion";
import { X } from "lucide-react";
import { Button } from "@/components/ds/Button";
import { DURATION, EASE } from "@/components/ds/motion";
import { FOCUS_RING } from "./controls";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Panneau de filtres mobile (bottom-sheet) :
 * role="dialog" + aria-modal, fermeture Échap / clic sur le voile, focus
 * initial dans le panneau, focus piégé, retour du focus au bouton d'ouverture,
 * défilement de la page verrouillé. Se ferme si l'écran passe en mode bureau.
 */
export default function FilterSheet({
  open,
  onClose,
  onReset,
  resetDisabled,
  applyLabel,
  returnFocusRef,
  children,
}: {
  open: boolean;
  onClose: () => void;
  onReset: () => void;
  resetDisabled?: boolean;
  applyLabel: string;
  returnFocusRef?: RefObject<HTMLElement>;
  children: ReactNode;
}) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const body = document.body;
    const previousOverflow = body.style.overflow;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    body.style.overflow = "hidden";
    const raf = requestAnimationFrame(() => panelRef.current?.focus({ preventScroll: true }));

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab" || !panelRef.current) return;
      const nodes = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (!nodes.length) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || active === panelRef.current)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      } else if (!panelRef.current.contains(active)) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);

    const desktop = window.matchMedia("(min-width: 1024px)");
    const onBreakpoint = () => {
      if (desktop.matches) onCloseRef.current();
    };
    desktop.addEventListener?.("change", onBreakpoint);

    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("keydown", onKeyDown);
      desktop.removeEventListener?.("change", onBreakpoint);
      body.style.overflow = previousOverflow;
      (returnFocusRef?.current ?? previouslyFocused)?.focus?.({ preventScroll: true });
    };
  }, [open, returnFocusRef]);

  return (
    <AnimatePresence>
      {open ? (
        <div key="filter-sheet" className="fixed inset-0 z-modal lg:hidden">
          <m.div
            aria-hidden
            className="absolute inset-0 bg-night/60 backdrop-blur-[2px]"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: DURATION.base }}
          />
          <m.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
            className="absolute inset-x-0 bottom-0 flex max-h-[90dvh] flex-col rounded-t-sheet bg-white shadow-strong outline-none"
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ duration: DURATION.slow, ease: EASE }}
          >
            <div aria-hidden className="flex justify-center pt-3">
              <span className="h-1.5 w-12 rounded-full bg-line" />
            </div>
            <div className="flex items-center justify-between gap-3 border-b border-lineSoft px-5 pb-3 pt-1">
              <h2 id={titleId} className="font-display text-lg font-extrabold text-ink">
                Filtres
              </h2>
              <button
                type="button"
                onClick={onClose}
                aria-label="Fermer les filtres"
                className={`-mr-2 grid h-11 w-11 place-items-center rounded-full text-ink transition duration-base hover:bg-lineSoft ${FOCUS_RING}`}
              >
                <X aria-hidden className="h-5 w-5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto overscroll-contain px-5 py-6">{children}</div>
            <div className="flex gap-3 border-t border-lineSoft bg-white px-5 pb-[max(1rem,env(safe-area-inset-bottom))] pt-4">
              <Button type="button" variant="outline" size="lg" onClick={onReset} disabled={resetDisabled}>
                Réinitialiser
              </Button>
              <Button type="button" size="lg" onClick={onClose} className="min-w-0 flex-1 !whitespace-normal text-center">
                {applyLabel}
              </Button>
            </div>
          </m.div>
        </div>
      ) : null}
    </AnimatePresence>
  );
}
