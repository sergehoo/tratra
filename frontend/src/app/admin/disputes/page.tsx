"use client";
import { useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import { Card, Badge, Button } from "@/components/ui";
import type { Dispute, Paginated } from "@/lib/types";

export default function AdminDisputes() {
  const [items, setItems] = useState<Dispute[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);

  function load() {
    setLoading(true);
    get<Paginated<Dispute>>("/disputes/")
      .then((d) => setItems(d.results ?? []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }
  useEffect(() => { load(); }, []);

  async function resolve(id: number, action: "refund_client" | "release_artisan" | "reject") {
    setBusy(id);
    try {
      await post(`/disputes/${id}/resolve/`, { action, resolution: "" });
      load();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <h2 className="text-xl font-bold">Litiges</h2>
      {loading ? (
        <p className="text-ash">Chargement…</p>
      ) : items.length === 0 ? (
        <Card><p className="text-ash">Aucun litige.</p></Card>
      ) : (
        <div className="grid gap-3">
          {items.map((d) => (
            <Card key={d.id} className="!p-5">
              <div className="flex items-center justify-between">
                <p className="font-semibold">Litige #{d.id} — réservation #{d.booking}</p>
                <Badge tone={d.status === "open" ? "accent" : "gray"}>{d.status}</Badge>
              </div>
              <p className="mt-2 text-sm text-ash">{d.reason}</p>
              {d.status === "open" && (
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button disabled={busy === d.id} onClick={() => resolve(d.id, "refund_client")}>Rembourser le client</Button>
                  <Button disabled={busy === d.id} onClick={() => resolve(d.id, "release_artisan")}>Verser à l'artisan</Button>
                  <Button variant="ghost" disabled={busy === d.id} onClick={() => resolve(d.id, "reject")}>Rejeter</Button>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
