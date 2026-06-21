"use client";
import { useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import { Card, Badge, Button } from "@/components/ui";
import type { HandymanDocument, Paginated } from "@/lib/types";

const TONE: Record<string, "primary" | "accent" | "gray"> = { approved: "primary", pending: "accent", rejected: "gray" };

export default function AdminKyc() {
  const [docs, setDocs] = useState<HandymanDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);

  function load() {
    setLoading(true);
    get<Paginated<HandymanDocument>>("/handyman-docs/")
      .then((d) => setDocs(d.results ?? []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }
  useEffect(() => { load(); }, []);

  async function review(id: number, action: "approve" | "reject") {
    setBusy(id);
    try {
      const reason = action === "reject" ? window.prompt("Motif du rejet ?") ?? "" : "";
      await post(`/handyman-docs/${id}/review/`, { action, reason });
      load();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <h2 className="text-xl font-bold">Vérification KYC des artisans</h2>
      {loading ? (
        <p className="text-ash">Chargement…</p>
      ) : docs.length === 0 ? (
        <Card><p className="text-ash">Aucun document à examiner.</p></Card>
      ) : (
        <div className="grid gap-3">
          {docs.map((d) => (
            <Card key={d.id} className="flex flex-wrap items-center justify-between gap-3 !p-5">
              <div>
                <p className="font-semibold">
                  {d.handyman_detail?.user_detail?.first_name ?? d.handyman_detail?.user_detail?.username ?? "Artisan"}
                  {" — "}{d.document_type}
                </p>
                {d.file && <a href={d.file} target="_blank" rel="noopener" className="text-sm text-primary">Voir le document</a>}
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={TONE[d.status] ?? "gray"}>{d.status}</Badge>
                {d.status !== "approved" && (
                  <Button disabled={busy === d.id} onClick={() => review(d.id, "approve")}>Approuver</Button>
                )}
                {d.status !== "rejected" && (
                  <Button variant="ghost" disabled={busy === d.id} onClick={() => review(d.id, "reject")}>Rejeter</Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
