"use client";
import { useEffect, useRef, useState } from "react";
import { get, upload } from "@/lib/api";
import { Card, Badge, Button } from "@/components/ui";
import type { HandymanDocument, Paginated } from "@/lib/types";

const DOC_TYPES = [
  { value: "id_card", label: "Pièce d'identité" },
  { value: "license", label: "Permis" },
  { value: "casier", label: "Casier judiciaire" },
  { value: "insurance", label: "Assurance" },
  { value: "certification", label: "Certificat / diplôme" },
];
const TONE: Record<string, "primary" | "accent" | "gray"> = {
  approved: "primary", pending: "accent", rejected: "gray",
};

export default function KycPage() {
  const [docs, setDocs] = useState<HandymanDocument[]>([]);
  const [type, setType] = useState("id_card");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  function load() {
    get<Paginated<HandymanDocument>>("/handyman-docs/").then((d) => setDocs(d.results ?? [])).catch(() => {});
  }
  useEffect(() => { load(); }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("document_type", type);
      form.append("file", file);
      await upload("/handyman-docs/", form);
      if (fileRef.current) fileRef.current.value = "";
      load();
    } catch {
      setError("Échec du téléversement (profil artisan requis).");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-2xl space-y-5">
      <Card>
        <h2 className="mb-3 text-lg font-bold">Vérification (KYC)</h2>
        <form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="flex-1 text-sm text-ash">Type de document
            <select value={type} onChange={(e) => setType(e.target.value)}
              className="mt-1 w-full rounded-xl border border-slate-200 px-4 py-2.5 outline-none focus:ring-2 focus:ring-accent">
              {DOC_TYPES.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
            </select>
          </label>
          <input ref={fileRef} type="file" className="text-sm" required />
          <Button type="submit" disabled={busy}>{busy ? "Envoi…" : "Téléverser"}</Button>
        </form>
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </Card>

      <Card>
        <h3 className="mb-3 font-bold">Mes documents</h3>
        {docs.length === 0 ? (
          <p className="text-ash">Aucun document. Téléversez au moins une pièce d'identité pour être vérifié.</p>
        ) : (
          <div className="grid gap-2">
            {docs.map((d) => (
              <div key={d.id} className="flex items-center justify-between rounded-xl border border-slate-100 p-3 text-sm">
                <span>{DOC_TYPES.find((t) => t.value === d.document_type)?.label ?? d.document_type}</span>
                <Badge tone={TONE[d.status] ?? "gray"}>{d.status}</Badge>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
