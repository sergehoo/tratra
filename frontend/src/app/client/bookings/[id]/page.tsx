"use client";
import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { get, post } from "@/lib/api";
import { Card, Badge, Button } from "@/components/ui";
import type { Booking, ReplacementSuggestion } from "@/lib/types";

export default function BookingDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [b, setB] = useState<Booking | null>(null);
  const [repl, setRepl] = useState<ReplacementSuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    get<Booking>(`/bookings/${id}/`).then(setB).catch(() => {}).finally(() => setLoading(false));
  }, [id]);
  useEffect(() => { load(); }, [load]);

  async function cancel() {
    setBusy(true);
    try {
      await post(`/bookings/${id}/transition/`, { status: "cancelled" });
      load();
    } finally {
      setBusy(false);
    }
  }

  async function loadReplacements() {
    const data = await get<ReplacementSuggestion[]>(`/bookings/${id}/replacements/`).catch(() => []);
    setRepl(data);
  }

  async function accept(suggestionId: number) {
    setBusy(true);
    try {
      await post(`/bookings/${id}/accept-replacement/`, { suggestion_id: suggestionId });
      setRepl([]);
      load();
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="text-ash">Chargement…</p>;
  if (!b) return <Card><p className="text-ash">Réservation introuvable.</p></Card>;

  const cancellable = ["pending", "confirmed"].includes(b.status);

  return (
    <div className="max-w-2xl space-y-5">
      <Card>
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold">{b.service_detail?.title ?? `Réservation #${b.id}`}</h2>
          <Badge tone={b.status === "completed" ? "gray" : "primary"}>{b.status}</Badge>
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-y-2 text-sm">
          <dt className="text-ash">Artisan</dt>
          <dd>{b.handyman_detail?.first_name ?? b.handyman_detail?.username ?? "—"}</dd>
          <dt className="text-ash">Date</dt>
          <dd>{b.booking_date ? new Date(b.booking_date).toLocaleString("fr-FR") : "—"}</dd>
          <dt className="text-ash">Adresse</dt>
          <dd>{b.address}, {b.city}</dd>
        </dl>
        {cancellable && (
          <div className="mt-5 flex gap-2">
            <Button variant="ghost" onClick={cancel} disabled={busy}>Annuler la réservation</Button>
            <Button variant="ghost" onClick={loadReplacements} disabled={busy}>Voir des remplaçants</Button>
          </div>
        )}
      </Card>

      {repl.length > 0 && (
        <Card>
          <h3 className="mb-3 font-bold">Artisans de remplacement suggérés</h3>
          <div className="grid gap-3">
            {repl.map((r) => (
              <div key={r.id} className="flex items-center justify-between rounded-xl border border-slate-100 p-3">
                <span>{r.suggested_service_detail?.title ?? "Service"} — {r.suggested_service_detail?.handyman_detail?.username}</span>
                <Button onClick={() => accept(r.id)} disabled={busy}>Choisir</Button>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
