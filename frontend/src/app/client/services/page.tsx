"use client";
import { useEffect, useState } from "react";
import { get } from "@/lib/api";
import { Card, Badge, Input } from "@/components/ui";
import type { Service, Paginated } from "@/lib/types";

export default function ServicesPage() {
  const [items, setItems] = useState<Service[]>([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);

  async function load(query = "") {
    setLoading(true);
    try {
      const d = await get<Paginated<Service>>(`/services/${query ? `?search=${encodeURIComponent(query)}` : ""}`);
      setItems(d.results ?? []);
    } catch {
      /* noop */
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, []);

  return (
    <div className="space-y-5">
      <h2 className="text-xl font-bold">Trouver un service</h2>
      <form onSubmit={(e) => { e.preventDefault(); load(q); }} className="max-w-md">
        <Input placeholder="Rechercher (plomberie, ménage…)" value={q} onChange={(e) => setQ(e.target.value)} />
      </form>

      {loading ? (
        <p className="text-ash">Chargement…</p>
      ) : items.length === 0 ? (
        <Card><p className="text-ash">Aucun service trouvé.</p></Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((s) => (
            <Card key={s.id}>
              {s.category_detail && <Badge>{s.category_detail.name}</Badge>}
              <h3 className="mt-2 font-semibold">{s.title}</h3>
              <p className="mt-1 line-clamp-2 text-sm text-ash">{s.description}</p>
              <div className="mt-4 flex items-center justify-between">
                <span className="font-bold text-primary">
                  {s.price ? `${Number(s.price).toLocaleString("fr-FR")} FCFA` : "Sur devis"}
                </span>
                <span className="text-sm text-ash">
                  {s.handyman_detail?.first_name ?? s.handyman_detail?.username ?? ""}
                </span>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
