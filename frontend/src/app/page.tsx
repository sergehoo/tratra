"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { HOME_BY_ROLE } from "@/lib/config";

export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (loading) return;
    router.replace(user ? HOME_BY_ROLE[user.user_type] ?? "/client" : "/login");
  }, [user, loading, router]);
  return <div className="grid min-h-screen place-items-center text-ash">Chargement…</div>;
}
