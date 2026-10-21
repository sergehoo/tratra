"use client";
import { useCallback, useEffect, useState } from "react";
import { Eye, Gauge, Hourglass, Timer, UserRound, Zap } from "lucide-react";
import { Alert, Badge, Button, Modal, PageHeader, Tabs } from "@/components/ds";
import { bo, boError } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useManagedList } from "@/lib/useBoList";
import { Kpi, KpiGrid } from "../_components/list";
import { FilterBar, FilterSelect, KV, ListView, ReasonModal, SearchBox, Section, dt, postTo, useNotice, useTabParam, type BoColumn, type RowAction } from "../_components/ui";

/* Tratra Flash & Smart Dispatch : supervision (chiffres réels + recommandations explicables), historique des attributions (propositions,
   réponses, délais, motifs), réglages (poids, délais, règles), pénalités Tratra Trust et contestations (décision humaine motivée). */

interface ReqRow {
  id: number; status: string; status_label: string; mode: string; category: string; commune: string; immediate: boolean; amount: number | null;
  client: string; client_id: number; created_at: string; scheduled_for: string; wave: number; contacted: number | null; assigned_to: string | null;
  assigned_at: string | null; seconds_to_assign: number | null; booking: number | null; close_reason: string;
  matching: "auto" | "direct"; matching_label: string; switches: number; target: string | null;
}
interface Criterion { key: string; label: string; weight: number; value: number; measured: boolean; points: number; detail: string }
interface OfferRow {
  id: number; pro: string; pro_id: number; wave: number; rank: number; score: number; criteria: Criterion[]; distance_km: number | null; status: string;
  status_label: string; sent_at: string; expires_at: string; seen_at: string | null; responded_at: string | null; response_seconds: number | null;
  decline_reason: string; quote_amount: number | null; targeted: boolean;
}
interface EventRow { kind: string; label: string; at: string; actor: string | null; data: Record<string, unknown> }
interface ReqDetail extends ReqRow { description: string; offers: OfferRow[]; events: EventRow[] }
interface Supervision {
  period_days: number;
  requests: { total: number; by_status: Record<string, number>; assignment_rate: number | null; median_seconds_to_assign: number | null };
  offers: { total: number; by_status: Record<string, number>; expiry_rate: number | null; median_response_seconds: number | null; decline_reasons: Record<string, number> };
  auto_paused: number; no_candidate: number; waiting_over_10_min: number; switches: number; awaiting_choice: number;
  by_matching: Record<"auto" | "direct", { total: number; assigned: number }>;
  recommendations: { rule: string; evidence: string; suggestion: string }[];
  open_requests: ReqRow[]; recent_unfulfilled: ReqRow[];
}
interface ConfigField { name: string; label: string; value: number; type: "int" | "float"; group: "waves" | "weights" | "rules" }
interface Penalty {
  id: number; kind: string; kind_label: string; status: string; status_label: string; explanation: string; booking: number | null; created_at: string;
  by_team: boolean; contest_reason: string; contested_at: string | null; decided_at: string | null; decision_note: string; user: string; user_id: number;
  created_by: string; decided_by: string | null;
}

const STATUS_TONE: Record<string, "success" | "accent" | "gray" | "danger" | "warning"> = {
  assigned: "success", searching: "accent", quoting: "warning", awaiting: "warning", unfulfilled: "danger", cancelled: "gray",
  accepted: "success", pending: "accent", quoted: "warning", declined: "gray", expired: "danger", withdrawn: "gray",
};
const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)} %`);
const secs = (v: number | null) => (v === null ? "—" : v < 120 ? `${v} s` : `${Math.round(v / 60)} min`);
const money = (v: number | null) => (v === null ? "Sur devis" : `${v.toLocaleString("fr-FR")} FCFA`);

function RequestPanel({ id, onClose }: { id: number | null; onClose: () => void }) {
  const [d, setD] = useState<ReqDetail | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    if (id === null) return;
    setError("");
    try { setD(await bo.get(`/flash/requests/${id}/`)); } catch (e) { setError(boError(e, "Cette demande n’a pas pu être chargée.")); }
  }, [id]);
  useEffect(() => { setD(null); void load(); }, [load]);
  return (
    <Modal open={id !== null} onClose={onClose} size="lg" title={d ? `Demande Tratra Flash #${d.id} — ${d.category}` : "Demande Tratra Flash"}>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {d ? (
        <div className="space-y-5">
          <KV items={[["Statut", <Badge key="s" tone={STATUS_TONE[d.status] ?? "gray"}>{d.status_label}</Badge>], ["Mode", `${d.matching_label}${d.target ? ` — ${d.target}` : ""}${d.switches ? ` (${d.switches} changement${d.switches > 1 ? "s" : ""} de mode)` : ""}`],
            ["Client", d.client], ["Zone", d.commune || "—"],
            ["Quand", `${d.immediate ? "Immédiate" : "Planifiée"} — ${dt(d.scheduled_for)}`], ["Montant", money(d.amount)], ["Vagues", d.wave],
            ["Attribuée à", d.assigned_to ?? "—"], ["Délai d’attribution", secs(d.seconds_to_assign)], ["Réservation", d.booking ? `#${d.booking}` : "—"]]} />
          {d.description ? <p className="whitespace-pre-line rounded-panel bg-canvas p-3 text-sm text-inkSoft">{d.description}</p> : null}
          <div>
            <h3 className="mb-2 text-sm font-bold text-ink">Propositions (ordre du classement)</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead><tr className="text-xs text-ash"><th className="py-1 pr-2">Vague</th><th className="pr-2">Professionnel</th><th className="pr-2">Score</th><th className="pr-2">Distance</th><th className="pr-2">Réponse</th><th>Délai</th></tr></thead>
                <tbody>
                  {d.offers.map((o) => (
                    <tr key={o.id} className="border-t border-line align-top">
                      <td className="py-1.5 pr-2">{o.wave}.{o.rank}</td>
                      <td className="pr-2">{o.pro}{o.targeted ? <Badge tone="accent" className="ml-1">Choisi par le client</Badge> : null}<details className="text-xs text-ash"><summary className="cursor-pointer">Pourquoi ce rang</summary>
                        <ul className="mt-1 space-y-0.5">{o.criteria.map((c) => <li key={c.key}>{c.label} : {c.points} pts (poids {c.weight}) — {c.detail}</li>)}</ul></details></td>
                      <td className="pr-2">{o.score.toFixed(1)}</td>
                      <td className="pr-2">{o.distance_km === null ? "Même commune" : `${o.distance_km.toFixed(1)} km`}</td>
                      <td className="pr-2"><Badge tone={STATUS_TONE[o.status] ?? "gray"}>{o.status_label}</Badge>{o.decline_reason ? <span className="block text-xs text-ash">{o.decline_reason}</span> : null}
                        {o.quote_amount !== null ? <span className="block text-xs text-ash">Devis : {money(o.quote_amount)}</span> : null}</td>
                      <td>{secs(o.response_seconds)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!d.offers.length ? <p className="text-sm text-ash">Aucune proposition : voir le journal (motifs d’exclusion).</p> : null}
            </div>
          </div>
          <div>
            <h3 className="mb-2 text-sm font-bold text-ink">Journal</h3>
            <ol className="space-y-1 text-sm">
              {d.events.map((e, i) => (
                <li key={i}><span className="text-ash">{dt(e.at)}</span> — {e.label}{e.actor ? ` (${e.actor})` : ""}
                  {e.data && "reasons" in e.data && e.data.reasons && Object.keys(e.data.reasons as object).length
                    ? <span className="block text-xs text-ash">Exclus : {Object.entries(e.data.reasons as Record<string, number>).map(([k, v]) => `${k} (${v})`).join(", ")}</span> : null}
                </li>
              ))}
            </ol>
          </div>
        </div>
      ) : !error ? <p className="text-sm text-inkSoft" role="status">Chargement…</p> : null}
    </Modal>
  );
}

function SupervisionTab({ onOpen }: { onOpen: (id: number) => void }) {
  const [d, setD] = useState<Supervision | null>(null);
  const [days, setDays] = useState("7");
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setError("");
    try { setD(await bo.get(`/flash/supervision/?days=${days}`)); } catch (e) { setError(boError(e, "La supervision n’a pas pu être chargée.")); }
  }, [days]);
  useEffect(() => { void load(); const t = setInterval(() => void load(), 30000); return () => clearInterval(t); }, [load]);
  if (error) return <Alert tone="danger">{error}</Alert>;
  if (!d) return <p className="text-sm text-inkSoft" role="status">Chargement…</p>;
  const row = (r: ReqRow) => (
    <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-2 text-sm first:border-0">
      <span><span className="font-semibold text-ink">#{r.id} {r.category}</span> · {r.commune || "—"} · {money(r.amount)} · {r.contacted ?? 0} contacté(s), vague {r.wave}</span>
      <span className="flex items-center gap-2"><Badge tone={STATUS_TONE[r.status] ?? "gray"}>{r.status_label}</Badge><span className="text-xs text-ash">{dt(r.created_at)}</span>
        <Button size="sm" variant="ghost" onClick={() => onOpen(r.id)}>Détail</Button></span>
    </li>
  );
  return (
    <div className="space-y-5">
      <FilterBar activeCount={0} onReset={() => setDays("7")} onRefresh={() => void load()}>
        <FilterSelect label="Période" value={days} onChange={setDays} options={[["1", "24 heures"], ["7", "7 jours"], ["30", "30 jours"]]} />
      </FilterBar>
      <KpiGrid>
        <Kpi icon={<Zap className="h-5 w-5" />} label="Demandes" value={d.requests.total} hint={`${pct(d.requests.assignment_rate)} attribuées`} />
        <Kpi icon={<Timer className="h-5 w-5" />} tone="accent" label="Délai d’attribution médian" value={secs(d.requests.median_seconds_to_assign)} hint="De la demande à l’acceptation" />
        <Kpi icon={<Gauge className="h-5 w-5" />} tone="night" label="Propositions sans réponse" value={pct(d.offers.expiry_rate)} hint={`Réponse médiane : ${secs(d.offers.median_response_seconds)}`} />
        <Kpi icon={<Hourglass className="h-5 w-5" />} tone={d.waiting_over_10_min ? "danger" : "primary"} label="En recherche depuis +10 min" value={d.waiting_over_10_min} hint={`${d.no_candidate} sans candidat · ${d.auto_paused} pause(s) auto`} />
      </KpiGrid>
      <KpiGrid>
        <Kpi icon={<Zap className="h-5 w-5" />} label="Trouvez-moi un professionnel" value={d.by_matching.auto.total} hint={`${d.by_matching.auto.assigned} attribuée(s)`} />
        <Kpi icon={<UserRound className="h-5 w-5" />} tone="accent" label="Choisir mon professionnel" value={d.by_matching.direct.total} hint={`${d.by_matching.direct.assigned} attribuée(s)`} />
        <Kpi icon={<Timer className="h-5 w-5" />} tone={d.awaiting_choice ? "danger" : "night"} label="Choix du client attendu" value={d.awaiting_choice} hint={`${d.switches} changement(s) de mode sur la période`} />
      </KpiGrid>
      <Section title="Recommandations (lecture seule)">
        {d.recommendations.length ? (
          <ul className="space-y-3">{d.recommendations.map((r, i) => (
            <li key={i} className="rounded-panel bg-canvas p-3 text-sm"><p className="font-semibold text-ink">{r.rule}</p><p className="text-ash">Constat : {r.evidence}</p><p className="text-inkSoft">Proposition : {r.suggestion}</p></li>
          ))}</ul>
        ) : <p className="text-sm text-ash">Aucune anomalie détectée sur la période.</p>}
      </Section>
      <Section title={`Demandes en cours (${d.open_requests.length})`}>{d.open_requests.length ? <ul>{d.open_requests.map(row)}</ul> : <p className="text-sm text-ash">Aucune demande en attente.</p>}</Section>
      <Section title="Dernières demandes sans professionnel">{d.recent_unfulfilled.length ? <ul>{d.recent_unfulfilled.map(row)}</ul> : <p className="text-sm text-ash">Aucune.</p>}</Section>
      {Object.keys(d.offers.decline_reasons).length ? (
        <Section title="Motifs de refus (sans conséquence pour les professionnels)">
          <p className="flex flex-wrap gap-1.5 text-xs">{Object.entries(d.offers.decline_reasons).map(([k, v]) => <span key={k} className="rounded-full bg-canvas px-2.5 py-0.5">{k} : {v}</span>)}</p>
        </Section>
      ) : null}
    </div>
  );
}

function RequestsTab({ onOpen }: { onOpen: (id: number) => void }) {
  const m = useManagedList<ReqRow, { status: string; matching: string }>("/flash/requests/", { status: "", matching: "" });
  const { values: f, list } = m;
  const columns: BoColumn<ReqRow>[] = [
    { key: "id", header: "Demande", primary: true, cell: (r) => <span className="font-semibold text-ink">#{r.id} {r.category}</span> },
    { key: "status", header: "Statut", cell: (r) => <Badge tone={STATUS_TONE[r.status] ?? "gray"}>{r.status_label}</Badge> },
    { key: "matching", header: "Mode", hideOnMobile: true, cell: (r) => <span>{r.matching === "direct" ? "Choix du client" : "Smart Dispatch"}{r.target ? <span className="block text-xs text-ash">{r.target}</span> : null}</span> },
    { key: "client", header: "Client", hideOnMobile: true, cell: (r) => r.client },
    { key: "amount", header: "Montant", align: "right", hideOnMobile: true, cell: (r) => money(r.amount) },
    { key: "contacted", header: "Contactés", align: "right", from: "xl", hideOnMobile: true, cell: (r) => r.contacted ?? 0 },
    { key: "assigned", header: "Attribuée à", hideOnMobile: true, cell: (r) => r.assigned_to ?? <span className="text-ash">—</span> },
    { key: "delay", header: "Délai", align: "right", from: "xl", hideOnMobile: true, cell: (r) => secs(r.seconds_to_assign) },
    { key: "created", header: "Créée le", from: "xl", hideOnMobile: true, cell: (r) => dt(r.created_at) },
  ];
  const rowActions = (r: ReqRow): RowAction[] => [
    { label: "Voir l’historique", icon: Eye, onClick: () => onOpen(r.id) },
    { label: "Fiche du client", icon: UserRound, href: `/backoffice/users/${r.client_id}` },
  ];
  return (
    <>
      <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="Métier, commune, client, professionnel…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
        <FilterSelect label="Statut" value={f.status} onChange={(v) => m.set({ status: v })} options={[["", "Tous"], ["open", "En cours"], ["awaiting", "Choix du client attendu"], ["assigned", "Attribuées"], ["unfulfilled", "Sans professionnel"], ["cancelled", "Annulées"]]} />
        <FilterSelect label="Mode" value={f.matching} onChange={(v) => m.set({ matching: v })} options={[["", "Tous"], ["auto", "Smart Dispatch"], ["direct", "Choix du client"]]} />
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => `Demande #${r.id}`} caption="Historique des attributions" empty="Aucune demande."
        ordering={f.ordering} onOrdering={(v) => m.set({ ordering: v })} rowActions={rowActions} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
    </>
  );
}

function ConfigTab() {
  const { can } = useBo();
  const [fields, setFields] = useState<ConfigField[] | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [meta, setMeta] = useState<{ updated_at: string; updated_by: string | null } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useNotice();
  const apply = (d: { fields: ConfigField[]; updated_at: string; updated_by: string | null }) => {
    setFields(d.fields);
    setValues(Object.fromEntries(d.fields.map((f) => [f.name, String(f.value)])));
    setMeta({ updated_at: d.updated_at, updated_by: d.updated_by });
  };
  useEffect(() => { bo.get<{ fields: ConfigField[]; updated_at: string; updated_by: string | null }>("/flash/config/").then(apply).catch((e) => setError(boError(e, "Réglages indisponibles."))); }, []);
  async function save() {
    setBusy(true);
    setError("");
    try {
      apply(await bo.put("/flash/config/", values));
      setNotice("Réglages enregistrés : ils s’appliquent aux prochaines vagues.");
    } catch (e) { setError(boError(e, "Les réglages n’ont pas été enregistrés.")); } finally { setBusy(false); }
  }
  if (!fields) return error ? <Alert tone="danger">{error}</Alert> : <p className="text-sm text-inkSoft" role="status">Chargement…</p>;
  const editable = can("settings.manage");
  const group = (g: ConfigField["group"], title: string, hint: string) => (
    <Section title={title}>
      <p className="mb-3 text-xs text-ash">{hint}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.filter((f) => f.group === g).map((f) => (
          <label key={f.name} className="text-sm">
            <span className="mb-1 block text-inkSoft">{f.label}</span>
            <input className="h-10 w-full rounded-control border border-line px-3" inputMode="decimal" value={values[f.name] ?? ""} disabled={!editable}
              onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))} aria-label={f.label} />
          </label>
        ))}
      </div>
    </Section>
  );
  return (
    <div className="space-y-5">
      {notice ? <p role="status" className="rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {group("waves", "Vagues et délais", "Nombre de professionnels sollicités à la fois, délais de réponse, choix des devis.")}
      {group("weights", "Classement pondéré", "Chaque critère vaut entre 0 et 1 ; sans historique, il prend la valeur neutre (aucun désavantage pour les nouveaux).")}
      {group("rules", "Règles", "Zone, pause automatique après silences (jamais une sanction), limites anti-abus, délai de grâce d’un désistement.")}
      <div className="flex flex-wrap items-center gap-3">
        {editable ? <Button onClick={() => void save()} loading={busy}>Enregistrer les réglages</Button> : <p className="text-sm text-ash">Lecture seule : la modification exige le droit « Règles métier ».</p>}
        {meta ? <span className="text-xs text-ash">Dernière modification : {dt(meta.updated_at)}{meta.updated_by ? ` par ${meta.updated_by}` : ""}</span> : null}
      </div>
    </div>
  );
}

function PenaltiesTab() {
  const { can } = useBo();
  const m = useManagedList<Penalty, { status: string }>("/trust/penalties/", { status: "contested" });
  const { values: f, list } = m;
  const [decide, setDecide] = useState<{ p: Penalty; decision: "cancel" | "uphold" } | null>(null);
  const [notice, setNotice] = useNotice();
  const columns: BoColumn<Penalty>[] = [
    { key: "user", header: "Professionnel", primary: true, cell: (p) => <span className="font-semibold text-ink">{p.user}</span> },
    { key: "kind", header: "Fait", cell: (p) => <span>{p.kind_label}<span className="block text-xs text-ash">{p.explanation}</span></span> },
    { key: "status", header: "Statut", cell: (p) => <Badge tone={p.status === "contested" ? "warning" : p.status === "cancelled" ? "gray" : "danger"}>{p.status_label}</Badge> },
    { key: "contest", header: "Contestation", hideOnMobile: true, cell: (p) => p.contest_reason ? <span className="text-sm">{p.contest_reason}<span className="block text-xs text-ash">{dt(p.contested_at)}</span></span> : <span className="text-ash">—</span> },
    { key: "by", header: "Origine", from: "xl", hideOnMobile: true, cell: (p) => p.created_by },
    { key: "decision", header: "Décision", from: "xl", hideOnMobile: true, cell: (p) => p.decided_at ? <span className="text-sm">{p.decision_note}<span className="block text-xs text-ash">{p.decided_by} · {dt(p.decided_at)}</span></span> : <span className="text-ash">—</span> },
  ];
  const rowActions = (p: Penalty): RowAction[] => [
    { label: "Retenir la contestation (annuler)", icon: Eye, onClick: () => setDecide({ p, decision: "cancel" }), hidden: !can("trust.manage") || p.status === "cancelled" },
    { label: "Maintenir la pénalité", icon: Eye, onClick: () => setDecide({ p, decision: "uphold" }), hidden: !can("trust.manage") || p.status !== "contested" },
    { label: "Fiche du compte", icon: UserRound, href: `/backoffice/users/${p.user_id}` },
  ];
  return (
    <>
      <p className="mb-3 text-sm text-inkSoft">Une pénalité repose toujours sur un fait vérifiable (désistement après une acceptation ferme, absence constatée). Les refus et les absences de réponse n’en créent jamais.</p>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <FilterBar activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
        <FilterSelect label="Statut" value={f.status} onChange={(v) => m.set({ status: v })} options={[["contested", "Contestées"], ["active", "En vigueur"], ["cancelled", "Annulées"], ["", "Toutes"]]} />
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(p) => p.id} rowLabel={(p) => `Pénalité #${p.id}`} caption="Pénalités Tratra Trust" empty="Aucune pénalité."
        ordering={f.ordering} onOrdering={(v) => m.set({ ordering: v })} rowActions={rowActions} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
      <ReasonModal open={decide !== null} title={decide?.decision === "cancel" ? "Retenir la contestation et annuler la pénalité ?" : "Maintenir la pénalité ?"}
        description="La décision est motivée, notifiée au professionnel et journalisée ; son score est recalculé aussitôt." confirmLabel="Confirmer la décision"
        tone={decide?.decision === "uphold" ? "danger" : "primary"} reasonLabel="Motivation de la décision" reasonKey="note" onClose={() => setDecide(null)}
        request={(body) => postTo(`/trust/penalties/${decide?.p.id}/decide/`)({ ...body, decision: decide?.decision ?? "" })}
        onDone={() => { setDecide(null); setNotice("Décision enregistrée."); void list.reload(); }} />
    </>
  );
}

export default function FlashPage() {
  const { can } = useBo();
  const tabs = [
    { id: "supervision" as const, label: "Supervision" },
    { id: "requests" as const, label: "Historique des attributions" },
    { id: "config" as const, label: "Réglages" },
    ...(can("trust.manage") ? [{ id: "penalties" as const, label: "Pénalités et contestations" }] : []),
  ];
  const [tab, setTab] = useTabParam(["supervision", "requests", "config", "penalties"] as const, "supervision");
  const [open, setOpen] = useState<number | null>(null);
  return (
    <>
      <PageHeader title="Tratra Flash" description="Smart Dispatch : propositions par vagues aux professionnels vérifiés et disponibles, attribution unique, délais et réponses journalisés." />
      <Tabs ariaLabel="Sections" value={tab} onChange={setTab} className="mb-4" items={tabs} />
      {tab === "supervision" ? <SupervisionTab onOpen={setOpen} /> : tab === "requests" ? <RequestsTab onOpen={setOpen} /> : tab === "config" ? <ConfigTab /> : <PenaltiesTab />}
      <RequestPanel id={open} onClose={() => setOpen(null)} />
    </>
  );
}
