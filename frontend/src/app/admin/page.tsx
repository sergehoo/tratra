"use client";
import { useEffect, useState } from "react";
import { get } from "@/lib/api";
import { Stat } from "@/components/ui";

async function count(path: string): Promise<number> {
  try {
    const d = await get<{ count?: number; results?: unknown[] }>(`${path}?page_size=1`);
    return d.count ?? d.results?.length ?? 0;
  } catch {
    return 0;
  }
}

export default function AdminHome() {
  const [s, setS] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const [bookings, services, handymen, disputes] = await Promise.all([
        count("/bookings/"), count("/services/"), count("/handymen/"), count("/disputes/"),
      ]);
      setS({ bookings, services, handymen, disputes });
      setLoading(false);
    })();
  }, []);

  return (
    <div className="space-y-5">
      <h2 className="text-xl font-bold">Vue d'ensemble</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Réservations" value={loading ? "…" : s.bookings} />
        <Stat label="Services actifs" value={loading ? "…" : s.services} />
        <Stat label="Artisans" value={loading ? "…" : s.handymen} />
        <Stat label="Litiges" value={loading ? "…" : s.disputes} />
      </div>
      <p className="text-sm text-ash">
        Administration détaillée disponible via l'admin Django (`/admin/`) en attendant l'extension du back-office React.
      </p>
    </div>
  );
}
