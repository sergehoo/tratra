"use client";
import { Eye, UserRound } from "lucide-react";
import { Badge, PageHeader, type BadgeTone } from "@/components/ds";
import { useBo } from "@/lib/BoProvider";
import { useCounts, useManagedList } from "@/lib/useBoList";
import { FilterBar, ListView, SearchBox, StatusChips, dd, type BoColumn, type RowAction } from "../_components/ui";

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
  const { can } = useBo();
  const m = useManagedList<Row, { state: string }>("/kyc/", { state: "" });
  const { values: f, list } = m;
  const counts = useCounts("/kyc/", { _all: "", pending: "state=pending", ready: "state=ready", approved: "state=approved", rejected: "state=rejected", incomplete: "state=incomplete" }, list.version);

  const columns: BoColumn<Row>[] = [
    { key: "name", header: "Prestataire", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.name} <span className="font-normal text-ash">#{r.profile_id}</span></span> },
    { key: "commune", header: "Commune", from: "xl", hideOnMobile: true, cell: (r) => r.commune ?? "—" },
    { key: "state", header: "Dossier", cell: (r) => <span className="flex flex-wrap gap-1.5"><Badge tone={TONE[r.state] ?? "gray"}>{r.state_label}</Badge>{!r.account_active ? <Badge tone="danger">Compte suspendu</Badge> : null}</span> },
    { key: "docs", header: "Pièces", wrap: true, cell: (r) => <span className="text-inkSoft">{r.documents.pending} à examiner · {r.documents.approved} approuvée(s) · {r.documents.rejected} refusée(s)</span> },
    { key: "since", header: "En attente depuis", from: "lg", hideOnMobile: true, cell: (r) => dd(r.oldest_pending_at) },
  ];
  const rowActions = (r: Row): RowAction[] => [
    { label: "Examiner le dossier", icon: Eye, href: `/backoffice/kyc/${r.profile_id}` },
    { label: "Fiche du compte", icon: UserRound, href: `/backoffice/users/${r.user_id}`, hidden: !can("users.view") },
  ];

  return (
    <>
      <PageHeader title="Vérification KYC" description="File des dossiers artisans, du plus ancien au plus récent. Une pièce d’identité approuvée est requise avant toute approbation du dossier ; l’approbation reste une décision humaine." />
      <StatusChips items={[["", "Tous"], ["pending", "À examiner"], ["ready", "Prêts"], ["approved", "Approuvés"], ["rejected", "Refusés"], ["incomplete", "Incomplets"]]} value={f.state} onChange={(v) => m.set({ state: v })} counts={counts} label="État du dossier" />
      <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="Nom, identifiant, commune…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading} />
      <ListView
        list={list}
        columns={columns}
        rowKey={(r) => r.profile_id}
        rowHref={(r) => `/backoffice/kyc/${r.profile_id}`}
        rowLabel={(r) => `${r.name} #${r.profile_id}`}
        caption="Dossiers KYC"
        empty="Aucun dossier dans cet état."
        emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : "La file est vide."}
        rowActions={rowActions}
        pageSize={m.pageSize}
        onPageSize={(n) => m.set({ size: String(n) })}
      />
    </>
  );
}
