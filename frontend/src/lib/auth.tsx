"use client";
import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { useRouter } from "next/navigation";
import * as api from "./api";
import { HOME_BY_ROLE } from "./config";
import type { User } from "./types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (u: string, p: string) => Promise<User>;
  register: (payload: Parameters<typeof api.register>[0]) => Promise<User>;
  logout: () => Promise<void>;
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
      router.replace("/login");
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

  async function login(u: string, p: string) {
    const me = await api.login(u, p);
    setUser(me);
    router.push(HOME_BY_ROLE[me.user_type] ?? "/client");
    return me;
  }

  async function register(payload: Parameters<typeof api.register>[0]) {
    const me = await api.register(payload);
    setUser(me);
    router.push(HOME_BY_ROLE[me.user_type] ?? "/client");
    return me;
  }

  async function logout() {
    await api.logout();
    setUser(null);
    router.push("/login");
  }

  return (
    <Ctx.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth doit être utilisé dans <AuthProvider>");
  return ctx;
}
