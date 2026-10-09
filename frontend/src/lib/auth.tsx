"use client";
import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { useRouter } from "next/navigation";
import * as api from "./api";
import { isProtectedPath, loginHref, safeNext } from "./links";
import type { User } from "./types";

interface AuthState {
  user: User | null;
  loading: boolean;
  /** `next` : page de retour après connexion (validée par safeNext, sinon espace du rôle). */
  login: (u: string, p: string, next?: string | null) => Promise<User>;
  register: (payload: Parameters<typeof api.register>[0], next?: string | null) => Promise<User>;
  logout: () => Promise<void>;
  /** Recharge le profil (ex. `is_verified` après une vérification par code). */
  refreshUser: () => Promise<User | null>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    let active = true;
    const handleSessionExpired = () => {
      if (!active) return;
      setUser(null);
      // Seule une page protégée renvoie vers la connexion (avec retour après
      // connexion). Sur une page publique (/, /search, /login…), le visiteur
      // reste où il est : sa session est simplement vidée.
      const { pathname, search } = window.location;
      if (isProtectedPath(pathname)) router.replace(loginHref(`${pathname}${search}`));
    };

    const restoreSession = async () => {
      api.tokens.migrateLegacy();
      if (api.tokens.access || api.tokens.refresh) {
        try {
          const currentUser = await api.me();
          if (active) setUser(currentUser);
        } catch {
          // Une indisponibilité réseau ne doit pas supprimer la session locale.
          // Les jetons invalides déclenchent déjà SESSION_EXPIRED_EVENT dans api.ts.
        }
      }
      if (active) setLoading(false);
    };

    window.addEventListener(api.SESSION_EXPIRED_EVENT, handleSessionExpired);
    void restoreSession();
    return () => {
      active = false;
      window.removeEventListener(api.SESSION_EXPIRED_EVENT, handleSessionExpired);
    };
  }, [router]);

  async function login(u: string, p: string, next?: string | null) {
    const me = await api.login(u, p);
    setUser(me);
    router.push(safeNext(next, me.user_type));
    return me;
  }

  async function register(payload: Parameters<typeof api.register>[0], next?: string | null) {
    const me = await api.register(payload);
    setUser(me);
    const destination = safeNext(next, me.user_type);
    // Un numéro a été enregistré : proposer sa vérification par code (« Plus tard » possible).
    router.push(me.phone && !me.is_verified ? `/verify-phone?next=${encodeURIComponent(destination)}` : destination);
    return me;
  }

  async function logout() {
    await api.logout();
    setUser(null);
    router.push("/login");
  }

  async function refreshUser() {
    try {
      const fresh = await api.me();
      setUser(fresh);
      return fresh;
    } catch {
      return null;
    }
  }

  return (
    <Ctx.Provider value={{ user, loading, login, register, logout, refreshUser }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth doit être utilisé dans <AuthProvider>");
  return ctx;
}
