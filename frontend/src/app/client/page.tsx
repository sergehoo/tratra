"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { get } from "@/lib/api";
import { Card, Badge, Button } from "@/components/ui";
import type { Booking, Paginated } from "@/lib/types";

const STATUS: Record<string, { label: string; tone: "primary" | "accent" | "gray" }> = {
  pending: { label: "En attente", tone: "accent" },
  confirmed: { label: "Confirmée", tone: "primary" },
  in_progress: { label: "En cours", tone: "primary" },
  completed: { label: "Terminée", tone: "gray" },
  cancelled: { label: "Annulée", tone: "gray" },
};

export default function ClientHome() {
  const [items, setItems] = useState<Booking[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    get<Paginated<Booking>>("/bookings/")
      .then((d) => setItems(d.results ?? []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">Mes réservations</h2>
        <Link href="/client/services"><Button>Nouvelle demande</Button></Link>
      </div>

      {loading ? (
        <p className="text-ash">Chargement…</p>
      ) : items.length === 0 ? (
        <Card><p className="text-ash">Aucune réservation pour le moment.</p></Card>
      ) : (
        <div className="grid gap-3">
          {items.map((b) => {
            const s = STATUS[b.status] ?? { label: b.status, tone: "gray" as const };
            return (
              <Link key={b.id} href={`/client/bookings/${b.id}`}>
                <Card className="flex items-center justify-between !p-5 transition hover:shadow-strong">
                  <div>
                    <p className="font-semibold">{b.service_detail?.title ?? `Réservation #${b.id}`}</p>
                    <p className="text-sm text-ash">
                      {b.city ?? ""} {b.booking_date ? "· " + new Date(b.booking_date).toLocaleDateString("fr-FR") : ""}
                    </p>
                  </div>
                  <Badge tone={s.tone}>{s.label}</Badge>
                </Card>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
