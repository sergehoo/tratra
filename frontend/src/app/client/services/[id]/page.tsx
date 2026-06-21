"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { get, post, ApiError } from "@/lib/api";
import { Card, Badge, Button, Input } from "@/components/ui";
import type { Service } from "@/lib/types";

export default function ServiceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [svc, setSvc] = useState<Service | null>(null);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ booking_date: "", address: "", city: "", postal_code: "", description: "" });
  const [pay, setPay] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((s) => ({ ...s, [k]: e.target.value }));

  useEffect(() => {
    get<Service>(`/services/${id}/`).then(setSvc).catch(() => {}).finally(() => setLoading(false));
  }, [id]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!svc) return;
    setError("");
    setBusy(true);
    try {
      const booking = await post<{ id: number }>("/bookings/", {
        service: svc.id,
        handyman: svc.handyman ?? svc.handyman_detail?.id,
        booking_date: new Date(form.booking_date).toISOString(),
        address: form.address,
        city: form.city,
        postal_code: form.postal_code || "00000",
        description: form.description,
        type: "scheduled",
        minutes: 60,
        category_id: svc.category ?? svc.category_detail?.id,
      });
      if (pay) {
        await post("/payments/initiate/", {
          booking_id: booking.id,
          method: "om",
          minutes: 60,
          category_id: svc.category ?? svc.category_detail?.id,
        }).catch(() => {});
      }
      router.push(`/client/bookings/${booking.id}`);
    } catch (err) {
      const data = err instanceof ApiError ? err.data : null;
      setError(typeof data === "object" && data ? Object.values(data).flat().join(" ") : "Réservation impossible.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="text-ash">Chargement…</p>;
  if (!svc) return <Card><p className="text-ash">Service introuvable.</p></Card>;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        {svc.category_detail && <Badge>{svc.category_detail.name}</Badge>}
        <h2 className="mt-2 text-2xl font-bold">{svc.title}</h2>
        <p className="mt-2 text-ash">{svc.description}</p>
        <p className="mt-4 text-xl font-extrabold text-primary">
          {svc.price ? `${Number(svc.price).toLocaleString("fr-FR")} FCFA` : "Sur devis"}
        </p>
        <p className="mt-1 text-sm text-ash">
          Artisan : {svc.handyman_detail?.first_name ?? svc.handyman_detail?.username ?? "—"}
        </p>
      </Card>

      <Card>
        <h3 className="mb-3 text-lg font-bold">Réserver</h3>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <label className="text-sm text-ash">Date &amp; heure
            <Input type="datetime-local" value={form.booking_date} onChange={set("booking_date")} required />
          </label>
          <Input placeholder="Adresse" value={form.address} onChange={set("address")} required />
          <div className="grid grid-cols-2 gap-3">
            <Input placeholder="Ville" value={form.city} onChange={set("city")} required />
            <Input placeholder="Code postal" value={form.postal_code} onChange={set("postal_code")} />
          </div>
          <textarea placeholder="Décrivez votre besoin" value={form.description} onChange={set("description")}
            className="w-full rounded-xl border border-slate-200 px-4 py-2.5 outline-none focus:ring-2 focus:ring-accent" rows={3} />
          <label className="flex items-center gap-2 text-sm text-ash">
            <input type="checkbox" checked={pay} onChange={(e) => setPay(e.target.checked)} />
            Régler maintenant (paiement sous séquestre)
          </label>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <Button type="submit" disabled={busy}>{busy ? "Réservation…" : "Confirmer la réservation"}</Button>
        </form>
      </Card>
    </div>
  );
}
