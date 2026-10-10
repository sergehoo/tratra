"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError } from "./api";
import { bo, type BoMe } from "./bo";
import { useAuth } from "./auth";

interface BoState {
  me: BoMe | null;
  loading: boolean;
  /** Compte connecté sans aucun rôle d'administration (403) : l'accès est refusé, jamais un menu vide. */
  forbidden: boolean;
  error: string;
  can: (permission: string) => boolean;
  reload: () => Promise<void>;
}

const Ctx = createContext<BoState | null>(null);

/** Identité et droits du personnel connecté. L'interface reflète les droits ; chaque endpoint les applique de toute façon. */
export function BoProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [me, setMe] = useState<BoMe | null>(null);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    setError("");
    try {
      setMe(await bo.get<BoMe>("/me/"));
      setForbidden(false);
    } catch (e) {
      setMe(null);
      if (e instanceof ApiError && (e.status === 403 || e.status === 401)) setForbidden(true);
      else setError("Le Back-Office est indisponible pour le moment. Vérifiez votre connexion puis réessayez.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user) void reload();
  }, [user, reload]);

  const value = useMemo<BoState>(
    () => ({ me, loading, forbidden, error, reload, can: (p) => Boolean(me?.permissions.includes(p)) }),
    [me, loading, forbidden, error, reload],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useBo(): BoState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useBo doit être utilisé dans <BoProvider>");
  return ctx;
}
