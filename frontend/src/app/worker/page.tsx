"use client";
import { useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import { Card, Badge, Button, Stat } from "@/components/ui";
import type { Booking, Paginated } from "@/lib/types";

export default function WorkerHome() {
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [available, setAvailable] = useState<string>("—");
  const [online, setOnline] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    Promise.all([
      get<Paginated<Booking>>("/bookings/").then((d) => setBookings(d.results ?? [])).catch(() => {}),
      get<{ available: string }>("/payouts/available/").then((d) => setAvailable(d.available)).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  async function setPresence(value: boolean) {
    setMsg("");
    try {
      await post("/handymen/presence/", { online: value });
      setOnline(value);
    } catch {
      setMsg("Action impossible (profil non vérifié ?).");
    }
  }

  const upcoming = bookings.filter((b) => ["pending", "confirmed", "in_progress"].includes(b.status));

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Missions à venir" value={loading ? "…" : upcoming.length} />
        <Stat label="Gains disponibles" value={`${Number(available || 0).toLocaleString("fr-FR")} FCFA`} />
        <Card className="!p-5">
          <p className="mb-2 text-sm text-ash">Disponibilité</p>
          <div className="flex gap-2">
            <Button variant={online ? "primary" : "ghost"} onClick={() => setPresence(true)}>En ligne</Button>
            <Button variant={online === false ? "primary" : "ghost"} onClick={() => setPresence(false)}>Hors ligne</Button>
          </div>
          {msg && <p className="mt-2 text-xs text-red-600">{msg}</p>}
        </Card>
      </div>

      <div>
        <h2 className="mb-3 text-xl font-bold">Mes missions</h2>
        {loading ? (
          <p className="text-ash">Chargement…</p>
        ) : bookings.length === 0 ? (
          <Card><p className="text-ash">Aucune mission pour le moment.</p></Card>
        ) : (
          <div className="grid gap-3">
            {bookings.map((b) => (
              <Card key={b.id} className="flex items-center justify-between !p-5">
                <div>
                  <p className="font-semibold">{b.service_detail?.title ?? `Mission #${b.id}`}</p>
                  <p className="text-sm text-ash">
                    {b.client_detail?.first_name ?? b.client_detail?.username ?? "Client"} · {b.city ?? ""}
                  </p>
                </div>
                <Badge tone={b.status === "completed" ? "gray" : "primary"}>{b.status}</Badge>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
