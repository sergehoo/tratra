"use client";
import { useState } from "react";
import { Eye, RefreshCw, UserRound } from "lucide-react";
import { Alert, Badge, PageHeader } from "@/components/ds";
import { bo, boError } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useManagedList } from "@/lib/useBoList";
import { FilterBar, FilterSelect, ListView, SearchBox, dd, useNotice, type BoColumn, type RowAction } from "../_components/ui";

interface Row {
  profile_id: number;
  user_id: number;
  name: string;
  commune: string | null;
  trust_score: number | null;
  badges: string[];
  evaluated_at: string | null;
  completed_jobs: number;
  rating: number;
  approved: boolean;
}

const BADGE_FR: Record<string, string> = { VERIFIE: "Vérifié", EXPERT: "Expert", SUR: "Sûr", NOUVEAU: "Nouveau" };

export default function TrustPage() {
  const { can } = useBo();
  const m = useManagedList<Row, { badge: string; no_score: string }>("/trust/", { badge: "", no_score: "" });
  const { values: f, list } = m;
  const [notice, setNotice] = useNotice();
  const [error, setError] = useState("");

  async function reevaluate(r: Row) {
    setError("");
    try {
      const res = await bo.post<{ score: number | null; badges: string[] }>(`/trust/${r.profile_id}/reevaluate/`);
      setNotice(`${r.name} réévalué : score ${res.score ?? "non évaluable"}.`);
      void list.reload();
    } catch (e) {
      setError(boError(e, "La réévaluation a échoué."));
    }
  }

  const columns: BoColumn<Row>[] = [
    { key: "name", header: "Prestataire", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.name} <span className="font-normal text-ash">#{r.profile_id}</span></span> },
    { key: "score", header: "Score", align: "right", sort: "score", cell: (r) => r.trust_score ?? <span className="text-ash">Non évaluable</span> },
    { key: "badges", header: "Badges", cell: (r) => r.badges.length ? <span className="flex flex-wrap gap-1.5">{r.badges.map((b) => <Badge key={b} tone={b === "VERIFIE" ? "success" : b === "EXPERT" ? "accent" : "primary"}>{BADGE_FR[b] ?? b}</Badge>)}</span> : <span className="text-ash">Aucun</span> },
    { key: "jobs", header: "Missions", align: "right", sort: "jobs", hideOnMobile: true, cell: (r) => r.completed_jobs },
    { key: "rating", header: "Note", align: "right", hideOnMobile: true, from: "xl", cell: (r) => (r.rating ? r.rating.toFixed(1) : "—") },
    { key: "eval", header: "Évalué le", sort: "evaluated", from: "xl", hideOnMobile: true, cell: (r) => dd(r.evaluated_at) },
  ];
  const rowActions = (r: Row): RowAction[] => [
    { label: "Ouvrir la fiche", icon: Eye, href: `/backoffice/trust/${r.profile_id}` },
    { label: "Demander une réévaluation", icon: RefreshCw, onClick: () => void reevaluate(r), hidden: !can("trust.manage") },
    { label: "Fiche du compte", icon: UserRound, href: `/backoffice/users/${r.user_id}`, hidden: !can("users.view") },
  ];

  return (
    <>
      <PageHeader title="Tratra Trust" description="Badges et score de confiance, calculés par la règle à partir de faits mesurés. Aucun badge ne s’attribue à la main : on peut seulement demander une réévaluation." />
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      {error ? <Alert tone="danger" className="mb-4">{error}</Alert> : null}
      <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="Nom ou identifiant d’artisan…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
        <FilterSelect label="Badge" value={f.badge} onChange={(v) => m.set({ badge: v })} options={[["", "Tous"], ["VERIFIE", "Vérifié"], ["EXPERT", "Expert"], ["SUR", "Sûr"], ["NOUVEAU", "Nouveau"]]} />
        <FilterSelect label="Score" value={f.no_score} onChange={(v) => m.set({ no_score: v })} options={[["", "Tous"], ["true", "Sans score publié"]]} />
      </FilterBar>
      <ListView
        list={list}
        columns={columns}
        rowKey={(r) => r.profile_id}
        rowHref={(r) => `/backoffice/trust/${r.profile_id}`}
        rowLabel={(r) => `${r.name} #${r.profile_id}`}
        caption="Artisans et confiance"
        empty="Aucun artisan ne correspond."
        emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        ordering={f.ordering}
        onOrdering={(v) => m.set({ ordering: v })}
        rowActions={rowActions}
        pageSize={m.pageSize}
        onPageSize={(n) => m.set({ size: String(n) })}
      />
    </>
  );
}
