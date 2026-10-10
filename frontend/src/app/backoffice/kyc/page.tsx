"use client";
import { useState } from "react";
import { Badge, PageHeader, type BadgeTone, type Column } from "@/components/ds";
import { useBoList, useDebounced } from "@/lib/useBoList";
import { FilterBar, FilterSelect, ListView, SearchBox, dt } from "../_components/ui";

interface Row {
  profile_id: number;
  user_id: number;
  name: string;
  commune: string | null;
  state: string;
  state_label: string;
  is_approved: boolean;
  documents: { pending: number; approved: number; rejected: number };
  oldest_pending_at: string | null;
  account_active: boolean;
}

const TONE: Record<string, BadgeTone> = { pending: "warning", ready: "info", approved: "success", rejected: "danger", incomplete: "gray" };

export default function KycPage() {
  const [q, setQ] = useState("");
  const [state, setState] = useState("");
  const list = useBoList<Row>("/kyc/", { q: useDebounced(q), state });
  const columns: Column<Row>[] = [
    { key: "name", header: "Artisan", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.name} <span className="font-normal text-ash">#{r.profile_id}</span></span> },
    { key: "commune", header: "Commune", hideOnMobile: true, cell: (r) => r.commune ?? "—" },
    { key: "state", header: "Dossier", cell: (r) => <span className="flex flex-wrap gap-1.5"><Badge tone={TONE[r.state] ?? "gray"}>{r.state_label}</Badge>{!r.account_active ? <Badge tone="danger">Compte suspendu</Badge> : null}</span> },
    { key: "docs", header: "Pièces", cell: (r) => <span className="text-inkSoft">{r.documents.pending} à examiner · {r.documents.approved} approuvée(s) · {r.documents.rejected} refusée(s)</span> },
    { key: "since", header: "En attente depuis", hideOnMobile: true, cell: (r) => dt(r.oldest_pending_at) },
  ];
  return (
    <>
      <PageHeader title="Vérification KYC" description="File des dossiers artisans, du plus ancien au plus récent. Une pièce d’identité approuvée est requise avant toute approbation du dossier." />
      <FilterBar>
        <SearchBox value={q} onChange={setQ} placeholder="Nom, identifiant, commune…" />
        <FilterSelect label="État du dossier" value={state} onChange={setState} options={[["", "Tous"], ["pending", "Pièces à examiner"], ["ready", "Prêt pour approbation"], ["approved", "Approuvé"], ["rejected", "Refusé"], ["incomplete", "Dossier incomplet"]]} />
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.profile_id} rowHref={(r) => `/backoffice/kyc/${r.profile_id}`} caption="Dossiers KYC" empty="Aucun dossier dans cet état." />
    </>
  );
}
