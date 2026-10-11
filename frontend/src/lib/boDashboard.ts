"use client";
import { useEffect, useState } from "react";
import { bo } from "./bo";

export interface Dashboard {
  generated_at: string;
  kpis: {
    users?: { total: number; new_7d: number; new_30d: number; artisans: number; artisans_approved: number };
    bookings?: { total: number; by_status: Record<string, number>; active: number; created_7d: number; completed_30d: number };
    finance?: { gmv_30d: string; commission_30d: string; refunded_30d: string; escrow_held: string; payouts_pending: number; payouts_pending_amount: string };
    live?: { sharing_sessions: number };
  };
  series: { signups?: { date: string; count: number }[]; bookings?: { date: string; count: number }[] };
  alerts: { key: string; label: string; count: number; href: string; severity: "warning" | "danger" | "info" }[];
}

let cached: { at: number; promise: Promise<Dashboard> } | null = null;
const TTL_MS = 30_000;

/** Indicateurs du tableau de bord partagés entre les pages (un seul appel toutes les 30 s) ; `null` tant que non chargés ou si le rôle n'y a pas droit. */
export function useDashboardKpis(enabled = true): Dashboard["kpis"] | null {
  const [kpis, setKpis] = useState<Dashboard["kpis"] | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    if (!cached || Date.now() - cached.at > TTL_MS) cached = { at: Date.now(), promise: bo.get<Dashboard>("/dashboard/") };
    cached.promise.then((d) => alive && setKpis(d.kpis)).catch(() => {
      cached = null;
    });
    return () => {
      alive = false;
    };
  }, [enabled]);
  return kpis;
}
