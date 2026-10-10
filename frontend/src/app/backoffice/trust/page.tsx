"use client";
import { useState } from "react";
import { Badge, PageHeader, type Column } from "@/components/ds";
import { useBoList, useDebounced } from "@/lib/useBoList";
import { FilterBar, FilterSelect, ListView, SearchBox, dt } from "../_components/ui";

interface Row {
  profile_id: number;
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
  const [q, setQ] = useState("");
  const [badge, setBadge] = useState("");
  const [noScore, setNoScore] = useState("");
  const list = useBoList<Row>("/trust/", { q: useDebounced(q), badge, no_score: noScore });
  const columns: Column<Row>[] = [
    { key: "name", header: "Artisan", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.name} <span className="font-normal text-ash">#{r.profile_id}</span></span> },
    { key: "score", header: "Score", align: "right", cell: (r) => r.trust_score ?? <span className="text-ash">Non évaluable</span> },
    { key: "badges", header: "Badges", cell: (r) => r.badges.length ? <span className="flex flex-wrap gap-1.5">{r.badges.map((b) => <Badge key={b} tone={b === "VERIFIE" ? "success" : b === "EXPERT" ? "accent" : "primary"}>{BADGE_FR[b] ?? b}</Badge>)}</span> : <span className="text-ash">Aucun</span> },
    { key: "jobs", header: "Missions", align: "right", hideOnMobile: true, cell: (r) => r.completed_jobs },
    { key: "rating", header: "Note", align: "right", hideOnMobile: true, cell: (r) => (r.rating ? r.rating.toFixed(1) : "—") },
    { key: "eval", header: "Évalué le", hideOnMobile: true, cell: (r) => dt(r.evaluated_at) },
  ];
  return (
    <>
      <PageHeader title="Tratra Trust" description="Badges et score de confiance, calculés par la règle à partir de faits mesurés. Aucun badge ne s’attribue à la main : on peut seulement demander une réévaluation." />
      <FilterBar>
        <SearchBox value={q} onChange={setQ} placeholder="Nom ou identifiant d’artisan…" />
        <FilterSelect label="Badge" value={badge} onChange={setBadge} options={[["", "Tous"], ["VERIFIE", "Vérifié"], ["EXPERT", "Expert"], ["SUR", "Sûr"], ["NOUVEAU", "Nouveau"]]} />
        <FilterSelect label="Score" value={noScore} onChange={setNoScore} options={[["", "Tous"], ["true", "Sans score publié"]]} />
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.profile_id} rowHref={(r) => `/backoffice/trust/${r.profile_id}`} caption="Artisans et confiance" empty="Aucun artisan ne correspond." />
    </>
  );
}
