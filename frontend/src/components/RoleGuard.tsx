"use client";
import { ReactNode, useEffect, useRef } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { Spinner } from "@/components/ds";
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
    return <GuardLoading />;
  }
  return <>{children}</>;
}

/**
 * État d'attente de la garde (résolution de la session, redirection en cours) :
 * pastille logo + spinner, annoncé aux lecteurs d'écran.
 */
function GuardLoading() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="relative isolate grid min-h-screen place-items-center overflow-hidden bg-canvas px-4"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute -top-32 left-1/2 -z-10 h-72 w-[40rem] max-w-[160vw] -translate-x-1/2 rounded-full bg-primary/15 blur-3xl"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-24 -right-20 -z-10 h-56 w-56 rounded-full bg-accent/25 blur-3xl"
      />
      <div className="flex animate-fadeIn flex-col items-center gap-5">
        <span aria-hidden className="grid h-16 w-16 place-items-center rounded-card bg-white shadow-soft ring-1 ring-lineSoft">
          <Image src="/tratra_logo.webp" alt="" width={40} height={40} priority className="h-10 w-10" />
        </span>
        <p className="inline-flex items-center gap-2.5 rounded-full bg-white px-4 py-2 text-sm font-medium text-inkSoft shadow-hair ring-1 ring-lineSoft">
          <Spinner className="h-4 w-4 text-primary" />
          Chargement de votre espace…
        </p>
      </div>
    </div>
  );
}
