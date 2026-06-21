"use client";
import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { get, post } from "@/lib/api";
import { Card, Badge, Button } from "@/components/ui";
import type { Booking } from "@/lib/types";

// Transitions proposées à l'ouvrier selon le statut courant
const NEXT: Record<string, { status: string; label: string; variant?: "primary" | "ghost" }[]> = {
  pending: [
    { status: "confirmed", label: "Accepter" },
    { status: "cancelled", label: "Refuser", variant: "ghost" },
  ],
  confirmed: [{ status: "in_progress", label: "Démarrer la mission" }],
  in_progress: [{ status: "completed", label: "Marquer terminée" }],
};

export default function MissionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [b, setB] = useState<Booking | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    get<Booking>(`/bookings/${id}/`).then(setB).catch(() => {}).finally(() => setLoading(false));
  }, [id]);
  useEffect(() => { load(); }, [load]);

  async function transition(status: string) {
    setBusy(true);
    setError("");
    try {
      await post(`/bookings/${id}/transition/`, { status });
      load();
    } catch {
      setError("Transition impossible.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="text-ash">Chargement…</p>;
  if (!b) return <Card><p className="text-ash">Mission introuvable.</p></Card>;
  const actions = NEXT[b.status] ?? [];

  return (
    <div className="max-w-2xl space-y-5">
      <Card>
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold">{b.service_detail?.title ?? `Mission #${b.id}`}</h2>
          <Badge tone={b.status === "completed" ? "gray" : "primary"}>{b.status}</Badge>
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-y-2 text-sm">
          <dt className="text-ash">Client</dt>
          <dd>{b.client_detail?.first_name ?? b.client_detail?.username ?? "—"}</dd>
          <dt className="text-ash">Date</dt>
          <dd>{b.booking_date ? new Date(b.booking_date).toLocaleString("fr-FR") : "—"}</dd>
          <dt className="text-ash">Lieu</dt>
          <dd>{b.address}, {b.city}</dd>
        </dl>
        {actions.length > 0 && (
          <div className="mt-5 flex gap-2">
            {actions.map((a) => (
              <Button key={a.status} variant={a.variant ?? "primary"} disabled={busy}
                      onClick={() => transition(a.status)}>{a.label}</Button>
            ))}
          </div>
        )}
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </Card>
    </div>
  );
}
