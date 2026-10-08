"use client";
import { useEffect, useState } from "react";
import { apiErrorMessage, get, post, privateFileUrl } from "@/lib/api";
import { Card, Badge, Button } from "@/components/ui";
import type { HandymanDocument, Paginated } from "@/lib/types";

const TONE: Record<string, "primary" | "accent" | "gray"> = { approved: "primary", pending: "accent", rejected: "gray" };

export default function AdminKyc() {
  const [docs, setDocs] = useState<HandymanDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");

  function load() {
    setLoading(true);
    setError("");
    get<Paginated<HandymanDocument>>("/handyman-docs/")
      .then((d) => setDocs(d.results ?? []))
      .catch((requestError) => setError(apiErrorMessage(requestError, "Les documents KYC ne peuvent pas être chargés.")))
      .finally(() => setLoading(false));
  }
  useEffect(() => { load(); }, []);

  async function review(id: number, action: "approve" | "reject") {
    setBusy(id);
    try {
      const reason = action === "reject" ? window.prompt("Motif du rejet ?") ?? "" : "";
      await post(`/handyman-docs/${id}/review/`, { action, reason });
      load();
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "La revue du document a échoué."));
    } finally {
      setBusy(null);
    }
  }

  async function viewDocument(document: HandymanDocument) {
    if (!document.download_url) return;
    setBusy(document.id);
    setError("");
    try {
      const objectUrl = await privateFileUrl(document.download_url);
      const link = window.document.createElement("a");
      link.href = objectUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      window.document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Le document KYC ne peut pas être ouvert."));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <h2 className="text-xl font-bold">Vérification KYC des artisans</h2>
      {error && <p className="text-sm text-red-600" role="alert">{error}</p>}
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
                {d.download_url && (
                  <Button variant="ghost" disabled={busy === d.id} onClick={() => void viewDocument(d)}>
                    Voir le document
                  </Button>
                )}
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
