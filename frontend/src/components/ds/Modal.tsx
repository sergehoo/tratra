"use client";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, m } from "framer-motion";
import { X } from "lucide-react";
import { cx } from "./cx";
import { Button, type ButtonVariant } from "./Button";
import { DURATION, EASE } from "./motion";

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

const SIZES = { sm: "sm:max-w-md", md: "sm:max-w-lg", lg: "sm:max-w-2xl" } as const;

/**
 * Boîte de dialogue accessible : portail, focus piégé puis restitué, Échap,
 * verrouillage du défilement, voile cliquable. Feuille basse en mobile, carte
 * centrée dès `sm`. Mouvement réduit : géré par <MotionConfig> (Providers).
 */
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
  dismissible = true,
  className = "",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: keyof typeof SIZES;
  /** false : Échap, voile et croix sont inactifs (action en cours). */
  dismissible?: boolean;
  className?: string;
}) {
  const uid = useId();
  const titleId = `${uid}-title`;
  const descId = `${uid}-desc`;
  const panelRef = useRef<HTMLDivElement>(null);
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
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const panel = panelRef.current;
    // Focus initial : premier champ de saisie, sinon premier élément focalisable, sinon le panneau.
    const first = panel?.querySelector<HTMLElement>("input, textarea, select") ?? panel?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? panel)?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && dismissibleRef.current) {
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab" || !panel) return;
      const nodes = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (nodes.length === 0) {
        e.preventDefault();
        panel.focus();
        return;
      }
      const firstNode = nodes[0];
      const lastNode = nodes[nodes.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === firstNode || active === panel)) {
        e.preventDefault();
        lastNode.focus();
      } else if (!e.shiftKey && active === lastNode) {
        e.preventDefault();
        firstNode.focus();
      } else if (!(active instanceof Node && panel.contains(active))) {
        e.preventDefault();
        firstNode.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
      lastFocus.current?.focus?.();
    };
  }, [open]);

  if (!mounted) return null;

  return createPortal(
    <AnimatePresence>
      {open ? (
        <div className="fixed inset-0 z-modal flex items-end justify-center sm:items-center sm:p-6">
          <m.div
            aria-hidden
            className="absolute inset-0 bg-night/60 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: DURATION.base }}
            onClick={() => dismissible && onClose()}
          />
          <m.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            aria-describedby={description ? descId : undefined}
            tabIndex={-1}
            initial={{ opacity: 0, y: 32, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.98 }}
            transition={{ duration: DURATION.slow, ease: EASE }}
            className={cx(
              "safe-bottom relative flex max-h-[92vh] w-full flex-col overflow-hidden bg-white shadow-strong outline-none",
              "rounded-t-sheet sm:rounded-card",
              SIZES[size],
              className,
            )}
          >
            <div className="flex items-start justify-between gap-4 px-5 pb-3 pt-5 sm:px-6 sm:pt-6">
              <div className="min-w-0">
                <h2 id={titleId} className="font-display text-xl font-extrabold leading-tight text-ink">
                  {title}
                </h2>
                {description ? (
                  <p id={descId} className="mt-1.5 text-sm leading-relaxed text-ash">
                    {description}
                  </p>
                ) : null}
              </div>
              {dismissible ? (
                <button
                  type="button"
                  onClick={onClose}
                  aria-label="Fermer la fenêtre"
                  className="-mr-2 -mt-1 grid h-11 w-11 shrink-0 place-items-center rounded-xl text-ash transition hover:bg-lineSoft hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                >
                  <X aria-hidden className="h-5 w-5" />
                </button>
              ) : null}
            </div>
            {children ? <div className="overflow-y-auto px-5 pb-5 sm:px-6">{children}</div> : null}
            {footer ? (
              <div className="flex flex-col-reverse gap-3 border-t border-lineSoft bg-canvas px-5 py-4 sm:flex-row sm:justify-end sm:px-6">
                {footer}
              </div>
            ) : null}
          </m.div>
        </div>
      ) : null}
    </AnimatePresence>,
    document.body,
  );
}

/** Confirmation d'une action (éventuellement destructive), avec contenu libre (ex. motif). */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = "Confirmer",
  cancelLabel = "Annuler",
  tone = "primary",
  loading,
  confirmDisabled,
  children,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: ReactNode;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: Extract<ButtonVariant, "primary" | "danger">;
  loading?: boolean;
  confirmDisabled?: boolean;
  children?: ReactNode;
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      size="sm"
      dismissible={!loading}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button variant={tone} onClick={onConfirm} loading={loading} disabled={confirmDisabled}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
    </Modal>
  );
}
