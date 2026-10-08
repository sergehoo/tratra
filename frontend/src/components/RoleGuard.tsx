"use client";
import { ReactNode, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { HOME_BY_ROLE } from "@/lib/config";
import { loginHref } from "@/lib/links";
import type { UserType } from "@/lib/types";

/** Protège une page : exige une session et (optionnellement) un ou plusieurs rôles. */
export function RoleGuard({ roles, children }: { roles?: UserType[]; children: ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  // Une session ouverte puis fermée (déconnexion, expiration) est redirigée par
  // AuthProvider lui-même : le garde ne gère que l'accès direct sans session.
  const hadUser = useRef(false);

  useEffect(() => {
    if (loading) return;
    if (!user) {
      if (hadUser.current) return;
      // Retour automatique sur la page demandée après connexion
      // (window.location : évite d'imposer une frontière Suspense aux layouts).
      const { pathname, search } = window.location;
      router.replace(loginHref(`${pathname}${search}`));
    } else {
      hadUser.current = true;
      if (roles && !roles.includes(user.user_type)) {
        router.replace(HOME_BY_ROLE[user.user_type] ?? "/login");
      }
    }
  }, [user, loading, roles, router]);

  if (loading || !user || (roles && !roles.includes(user.user_type))) {
    return <div className="grid min-h-screen place-items-center text-ash">Chargement…</div>;
  }
  return <>{children}</>;
}
