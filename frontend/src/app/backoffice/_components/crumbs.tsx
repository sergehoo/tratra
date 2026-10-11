"use client";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

interface CrumbState {
  label: string | null;
  setLabel: (label: string | null) => void;
}

const Ctx = createContext<CrumbState>({ label: null, setLabel: () => undefined });

/** Libellé du dernier maillon du fil d'Ariane pour les pages de fiche (« Awa K. » plutôt que « Fiche #12 »). */
export function BoCrumbProvider({ children }: { children: ReactNode }) {
  const [label, setLabel] = useState<string | null>(null);
  const value = useMemo(() => ({ label, setLabel }), [label]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useCrumbLabel = (): string | null => useContext(Ctx).label;

/** À appeler depuis une page de fiche : `useCrumb(user?.name)` — le libellé disparaît en quittant la page. */
export function useCrumb(label: string | null | undefined): void {
  const { setLabel } = useContext(Ctx);
  useEffect(() => {
    setLabel(label || null);
    return () => setLabel(null);
  }, [label, setLabel]);
}
