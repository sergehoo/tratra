"use client";
import { ReactNode, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { HOME_BY_ROLE } from "@/lib/config";
import type { UserType } from "@/lib/types";

/** Protège une page : exige une session et (optionnellement) un ou plusieurs rôles. */
export function RoleGuard({ roles, children }: { roles?: UserType[]; children: ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
    } else if (roles && !roles.includes(user.user_type)) {
      router.replace(HOME_BY_ROLE[user.user_type] ?? "/login");
    }
  }, [user, loading, roles, router]);

  if (loading || !user || (roles && !roles.includes(user.user_type))) {
    return <div className="grid min-h-screen place-items-center text-ash">Chargement…</div>;
  }
  return <>{children}</>;
}
