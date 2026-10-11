"use client";
import { useCallback, useEffect, useState } from "react";
import { Banknote, Check, Eye, EyeOff, FileSignature, Gavel, Hourglass, Scale, Trash2, Undo2, Users } from "lucide-react";
import { Alert, Badge, Button, Card, Checkbox, Modal, PageHeader, SelectField, SkeletonStats, Tabs, TextField } from "@/components/ds";
import { bo, boError, fieldErrors, moneyLabel } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useCounts, useManagedList } from "@/lib/useBoList";
import { Bars, DateRange, ExportButton, FilterBar, FilterSelect, Kpi, KpiGrid, KV, ListView, ReasonModal, SearchBox, Section, StatusChips, Tag, dd, dt, postTo, useNotice, useTabParam, type BoColumn, type BulkAction, type RowAction } from "../_components/ui";

const CONTRACT_FR: Record<string, string> = { draft: "Brouillon", pending_acceptance: "À accepter", accepted: "Accepté", active: "En cours", suspended: "Suspendu", notice: "Préavis", terminated: "Résilié", completed: "Terminé", cancelled: "Annulé" };
const CONTRACT_TONE: Record<string, "gray" | "warning" | "info" | "success" | "danger" | "primary"> = { draft: "gray", pending_acceptance: "warning", accepted: "info", active: "success", suspended: "warning", notice: "warning", terminated: "gray", completed: "primary", cancelled: "gray" };
const INST_FR: Record<string, string> = { scheduled: "Planifiée", due: "À régler", partial: "Partielle", paid: "Réglée", overdue: "En retard", on_hold: "Suspendue", waived: "Abandonnée", cancelled: "Annulée" };
const INST_TONE: Record<string, "gray" | "warning" | "info" | "success" | "danger"> = { scheduled: "gray", due: "warning", partial: "info", paid: "success", overdue: "danger", on_hold: "warning", waived: "gray", cancelled: "gray" };
const POSTING_FR: Record<string, string> = { draft: "Brouillon", open: "Ouvert", closed: "Clos", filled: "Pourvu", cancelled: "Annulé", expired: "Expiré" };
const DISPUTE_FR: Record<string, string> = { open: "Ouvert", under_review: "En examen", resolved: "Résolu", rejected: "Rejeté" };
const KIND_FR: Record<string, string> = { payment: "Paiement", conditions: "Conditions", conduct: "Comportement", planning: "Planning et présences", other: "Autre" };
const MISSION_FR: Record<string, string> = { recurring: "Récurrente", long_term: "Longue durée" };
const REL_FR: Record<string, string> = { independent: "Indépendante", employment: "Emploi salarié" };
const PERIOD_FR: Record<string, string> = { monthly: "/ mois", hourly: "/ h", per_visit: "/ intervention" };

interface Who { id: number; name: string }
interface ContractRow { id: number; title: string; status: string; mission_type: string; work_relationship: string; category: string; principal: Who; worker: Who; organization: string | null; start_date: string; end_date: string | null; amount: string; period: string; open_disputes: number; overdue_installments: number; created_at: string }
interface Overview {
  contracts: { total: number; by_status: Record<string, number>; live: number; by_mission_type: Record<string, number>; by_relationship: Record<string, number>; monthly_commitment: string; renewed: number; average_duration_days: number | null; terminations: number; created_30d: number };
  installments: { overdue: number; overdue_amount: string; due_7d: number; payments_awaiting_confirmation: number; payments_contested: number };
  postings: { open: number; applications_30d: number }; disputes: { open: number; total: number }; evaluations: { total: number; hidden: number; reports_open: number };
  series: { contracts_created: { month: string; count: number }[]; confirmed_payments: { month: string; count: number; amount: string }[] };
}
interface InstRow { id: number; contract: { id: number; title: string; status: string }; principal: Who; worker: Who; number: number; period_start: string; period_end: string; due_date: string; status: string; total: string; confirmed: string; declared: string; balance: string; platform_fee: string; platform_fee_status: string; platform_fee_payer: string }
interface PostingRow { id: number; title: string; status: string; mission_type: string; work_relationship: string; city: string; category: string; publisher: Who; organization: string | null; amount: string; period: string; applications: number; created_at: string }
interface DisputeRow { id: number; contract: { id: number; title: string; status: string }; kind: string; status: string; opened_by: Who; opened_by_role: string; created_at: string; resolution_action: string }
interface EvalRow { id: number; contract: { id: number; title: string }; kind: string; rating: number; comment: string; reply: string; author: Who; subject: Who; is_hidden: boolean; hidden_reason: string; reports: number; created_at: string }
interface RuleSet { allow_recurring: boolean; allow_long_term: boolean; allow_employment: boolean; max_duration_months: number; min_notice_days_independent: number; min_notice_days_employment: number; commission_percent_independent: string; commission_percent_employment: string; commission_payer: string; max_advance_percent: number; late_grace_days: number; min_days_for_evaluation: number; evaluation_interval_days: number; evaluation_edit_days: number; source: string }
interface RulesIndex { default: RuleSet & { customized: boolean }; categories: (RuleSet & { category: { id: number; name: string }; customized: boolean })[]; notice: string }

// ── Aperçu ──────────────────────────────────────────────────────────────────────────────────────────────────────────

function OverviewTab() {
  const [o, setO] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { bo.get<Overview>("/engagements/").then(setO).catch((e) => setError(boError(e, "Indicateurs indisponibles."))); }, []);
  if (error) return <Alert tone="danger">{error}</Alert>;
  if (!o) return <SkeletonStats />;
  const bars = (rows: { month: string; count: number }[]) => rows.map((r) => ({ date: r.month, count: r.count }));
  return (
    <div className="space-y-6">
      <KpiGrid>
        <Kpi label="Contrats en vigueur" value={o.contracts.live} hint={`${o.contracts.created_30d} créés en 30 jours`} icon={<FileSignature className="h-5 w-5" />} />
        <Kpi label="Engagement mensuel" value={moneyLabel(o.contracts.monthly_commitment)} hint="contrats mensuels en vigueur" icon={<Banknote className="h-5 w-5" />} tone="accent" />
        <Kpi label="Échéances en retard" value={o.installments.overdue} hint={moneyLabel(o.installments.overdue_amount)} icon={<Hourglass className="h-5 w-5" />} tone="night" />
        <Kpi label="Litiges ouverts" value={o.disputes.open} hint={`${o.disputes.total} au total`} icon={<Scale className="h-5 w-5" />} />
        <Kpi label="Paiements à confirmer" value={o.installments.payments_awaiting_confirmation} hint={`${o.installments.payments_contested} contestés`} icon={<Gavel className="h-5 w-5" />} />
        <Kpi label="Besoins ouverts" value={o.postings.open} hint={`${o.postings.applications_30d} candidatures en 30 jours`} icon={<Users className="h-5 w-5" />} />
        <Kpi label="Contrats renouvelés" value={o.contracts.renewed} hint={`${o.contracts.terminations} résiliés`} icon={<FileSignature className="h-5 w-5" />} />
        <Kpi label="Durée moyenne" value={o.contracts.average_duration_days != null ? `${Math.round(o.contracts.average_duration_days / 30.4)} mois` : "—"} hint="contrats terminés" icon={<Hourglass className="h-5 w-5" />} />
      </KpiGrid>
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Contrats créés (12 mois)">
          {o.series.contracts_created.length ? <Bars data={bars(o.series.contracts_created)} label="Contrats" /> : <p className="text-sm text-ash">Aucun contrat créé sur la période.</p>}
        </Section>
        <Section title="Paiements confirmés par les parties (12 mois)">
          {o.series.confirmed_payments.length ? <Bars data={bars(o.series.confirmed_payments)} label="Paiements confirmés" /> : <p className="text-sm text-ash">Aucun paiement confirmé sur la période.</p>}
        </Section>
      </div>
      <Section title="Répartition des contrats en vigueur">
        <KV items={[["Par type", Object.entries(o.contracts.by_mission_type).map(([k, v]) => `${MISSION_FR[k] ?? k} : ${v}`).join(" · ") || "—"], ["Par relation", Object.entries(o.contracts.by_relationship).map(([k, v]) => `${REL_FR[k] ?? k} : ${v}`).join(" · ") || "—"],
          ["Par état", Object.entries(o.contracts.by_status).map(([k, v]) => `${CONTRACT_FR[k] ?? k} : ${v}`).join(" · ") || "—"], ["Évaluations", `${o.evaluations.total} (dont ${o.evaluations.hidden} masquées, ${o.evaluations.reports_open} signalements ouverts)`]]} />
      </Section>
    </div>
  );
}

// ── Contrats ────────────────────────────────────────────────────────────────────────────────────────────────────────

interface ContractDetail extends ContractRow {
  terms: Record<string, unknown>; terms_version: number; terms_hash: string; renewal_count: number; end_reason: string; closed_at: string | null; principal_detail: Who & { phone: string | null }; worker_detail: Who & { phone: string | null };
  acceptances: { role: string; terms_version: number; accepted_at: string }[]; amendments: { id: number; kind: string; status: string; reason: string; effective_date: string }[];
  suspensions: { starts_on: string; ends_on: string | null; source: string; reason: string }[];
  installments: { id: number; number: number; period_start: string; period_end: string; due_date: string; status: string; total: string; confirmed: string; balance: string; platform_fee: string; platform_fee_status: string; payments: { id: number; amount: string; method: string; status: string; declared_by_role: string; paid_on: string; has_evidence: boolean }[] }[];
  events: { id: number; type: string; actor: string; at: string }[]; disputes: { id: number; kind: string; status: string }[]; evaluations: { id: number; kind: string; rating: number; is_hidden: boolean }[];
  admin_actions: { action: string; at: string; by: string; reason: string }[];
}

function ContractPanel({ id, onClose, onChanged }: { id: number | null; onClose: () => void; onChanged: () => void }) {
  const { can } = useBo();
  const [d, setD] = useState<ContractDetail | null>(null);
  const [error, setError] = useState("");
  const [decision, setDecision] = useState<"suspend" | "resume" | "terminate" | null>(null);
  const load = useCallback(async () => {
    if (id === null) return;
    setError("");
    try { setD(await bo.get(`/engagements/contracts/${id}/`)); } catch (e) { setError(boError(e, "Ce contrat n’a pas pu être chargé.")); }
  }, [id]);
  useEffect(() => { setD(null); void load(); }, [load]);
  const live = d && ["accepted", "active", "suspended", "notice"].includes(d.status);
  const adminSuspended = d?.suspensions.some((s) => s.source === "admin" && !s.ends_on);
  return (
    <>
      <Modal open={id !== null && decision === null} onClose={onClose} size="lg" title={d ? `Contrat #${d.id} — ${d.title}` : "Contrat"}>
        {error ? <Alert tone="danger">{error}</Alert> : null}
        {d ? (
          <div className="space-y-5">
            <KV items={[["État", <Tag key="s" value={d.status} label={CONTRACT_FR[d.status]} tone={CONTRACT_TONE[d.status]} />], ["Métier", d.category], ["Donneur d’ordre", `${d.principal_detail.name}${d.organization ? ` (${d.organization})` : ""} · ${d.principal_detail.phone ?? "—"}`],
              ["Prestataire", `${d.worker_detail.name} · ${d.worker_detail.phone ?? "—"}`], ["Type", `${MISSION_FR[d.mission_type]} · ${REL_FR[d.work_relationship]}`], ["Rémunération", `${moneyLabel(d.amount)} ${PERIOD_FR[d.period]}`],
              ["Début", d.start_date], ["Fin", d.end_date ?? "Indéterminée"], ["Version des conditions", `${d.terms_version} (renouvelé ${d.renewal_count} fois)`], ["Empreinte", <code key="h" className="break-all text-xs">{d.terms_hash.slice(0, 16)}…</code>]]} />
            {d.end_reason ? <p className="rounded-panel bg-canvas p-3 text-sm text-inkSoft">Motif de fin : {d.end_reason}</p> : null}
            <div>
              <h3 className="mb-2 text-sm font-bold text-ink">Échéances</h3>
              <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-xs uppercase text-ash"><th className="py-1 pr-3">N°</th><th className="pr-3">Période</th><th className="pr-3">Échéance</th><th className="pr-3">Total</th><th className="pr-3">Confirmé</th><th className="pr-3">Solde</th><th>État</th></tr></thead>
                <tbody>{d.installments.map((i) => <tr key={i.id} className="border-t border-lineSoft"><td className="py-1.5 pr-3">{i.number}</td><td className="pr-3">{i.period_start} → {i.period_end}</td><td className="pr-3">{i.due_date}</td><td className="pr-3">{moneyLabel(i.total)}</td><td className="pr-3">{moneyLabel(i.confirmed)}</td><td className="pr-3">{moneyLabel(i.balance)}</td><td><Tag value={i.status} label={INST_FR[i.status]} tone={INST_TONE[i.status]} />{i.payments.some((p) => p.status === "declared") ? <Badge tone="accent" className="ml-1">à confirmer</Badge> : null}</td></tr>)}</tbody></table></div>
              <p className="mt-2 text-xs text-ash">La plateforme ne confirme jamais un paiement : seule la partie concernée le fait.</p>
            </div>
            {d.disputes.length ? <p className="text-sm">Litiges : {d.disputes.map((x) => `#${x.id} ${KIND_FR[x.kind]} (${DISPUTE_FR[x.status]})`).join(" · ")}</p> : null}
            {d.amendments.length ? <div><h3 className="mb-1 text-sm font-bold text-ink">Avenants</h3><ul className="space-y-0.5 text-sm text-inkSoft">{d.amendments.map((a) => <li key={a.id}>{a.kind} · {a.status} · effet {a.effective_date} — {a.reason}</li>)}</ul></div> : null}
            {d.admin_actions.length ? <div><h3 className="mb-1 text-sm font-bold text-ink">Décisions de la plateforme</h3><ul className="space-y-0.5 text-sm text-inkSoft">{d.admin_actions.map((a, i) => <li key={i}>{a.action.replace("backoffice.engagement.", "")} · {a.by} · {dt(a.at)} — {a.reason}</li>)}</ul></div> : null}
            <div>
              <h3 className="mb-1 text-sm font-bold text-ink">Historique récent</h3>
              <ul className="max-h-48 space-y-0.5 overflow-y-auto text-xs text-inkSoft">{d.events.slice(0, 40).map((e) => <li key={e.id}>{dt(e.at)} · {e.type} · {e.actor}</li>)}</ul>
            </div>
            {can("engagements.manage") ? (
              <div className="flex flex-wrap gap-2 border-t border-lineSoft pt-4">
                {live && !adminSuspended && d.status !== "suspended" ? <Button variant="outline" onClick={() => setDecision("suspend")}>Suspendre</Button> : null}
                {adminSuspended ? <Button variant="outline" onClick={() => setDecision("resume")}>Lever la suspension</Button> : null}
                {live ? <Button variant="danger" onClick={() => setDecision("terminate")}>Résilier</Button> : null}
              </div>
            ) : null}
            <p className="text-xs text-ash">Chaque décision exige un motif, est journalisée et notifie les deux parties. Le Back-Office ne modifie jamais un montant ni une échéance.</p>
          </div>
        ) : !error ? <p className="text-sm text-inkSoft" role="status">Chargement…</p> : null}
      </Modal>
      <ReasonModal open={decision !== null} tone={decision === "terminate" ? "danger" : "primary"} confirmLabel={{ suspend: "Suspendre", resume: "Lever la suspension", terminate: "Résilier" }[decision ?? "suspend"]}
        title={{ suspend: "Suspendre ce contrat ?", resume: "Lever la suspension ?", terminate: "Résilier ce contrat ?" }[decision ?? "suspend"]} onClose={() => setDecision(null)}
        description={decision === "terminate" ? "Résiliation par la plateforme : définitive. Les échéances à venir sont annulées ; celles déjà dues restent dues." : "Les parties sont notifiées avec ce motif."}
        request={(body) => bo.post(`/engagements/contracts/${id}/decision/`, { ...body, action: decision })} onDone={() => { setDecision(null); void load(); onChanged(); }} />
    </>
  );
}

function ContractsTab() {
  const { can } = useBo();
  const m = useManagedList<ContractRow, { status: string; mission_type: string; work_relationship: string; flag: string; user: string; from: string; to: string }>("/engagements/contracts/", { status: "", mission_type: "", work_relationship: "", flag: "", user: "", from: "", to: "" });
  const { values: f, list } = m;
  const counts = useCounts("/engagements/contracts/", { _all: "", active: "status=active", pending_acceptance: "status=pending_acceptance", suspended: "status=suspended", notice: "status=notice", terminated: "status=terminated" }, list.count);
  const [open, setOpen] = useState<number | null>(null);
  const columns: BoColumn<ContractRow>[] = [
    { key: "t", header: "Contrat", primary: true, sort: "created_at", wrap: true, cell: (r) => <span><span className="font-semibold text-ink">#{r.id} {r.title}</span><span className="block text-xs text-ash">{r.category} · {r.principal.name}{r.organization ? ` (${r.organization})` : ""} → {r.worker.name}</span></span> },
    { key: "s", header: "État", sort: "status", cell: (r) => <span className="flex flex-wrap gap-1"><Tag value={r.status} label={CONTRACT_FR[r.status]} tone={CONTRACT_TONE[r.status]} />{r.overdue_installments ? <Badge tone="danger">{r.overdue_installments} en retard</Badge> : null}{r.open_disputes ? <Badge tone="warning">litige</Badge> : null}</span> },
    { key: "m", header: "Type", hideOnMobile: true, from: "xl", cell: (r) => `${MISSION_FR[r.mission_type]} · ${REL_FR[r.work_relationship]}` },
    { key: "a", header: "Rémunération", align: "right", sort: "amount", hideOnMobile: true, from: "lg", cell: (r) => `${moneyLabel(r.amount)} ${PERIOD_FR[r.period]}` },
    { key: "d", header: "Période", sort: "start_date", hideOnMobile: true, from: "2xl", cell: (r) => `${r.start_date} → ${r.end_date ?? "…"}` },
  ];
  const rowActions = (r: ContractRow): RowAction[] => [
    { label: "Examiner le contrat", icon: Eye, onClick: () => setOpen(r.id) },
    { label: "Ses échéances", icon: Banknote, href: `/backoffice/engagements?tab=installments&contract=${r.id}` },
    { label: "Fiche du donneur d’ordre", icon: Users, href: `/backoffice/users/${r.principal.id}`, hidden: !can("users.view") },
    { label: "Fiche du prestataire", icon: Users, href: `/backoffice/users/${r.worker.id}`, hidden: !can("users.view") },
  ];
  return (
    <>
      <StatusChips items={[["", "Tous"], ["active", "En cours"], ["pending_acceptance", "À accepter"], ["suspended", "Suspendus"], ["notice", "Préavis"], ["terminated", "Résiliés"]]} value={f.status} onChange={(v) => m.set({ status: v })} counts={counts} label="État du contrat" />
      <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="Titre, nom, organisation…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}
        actions={<ExportButton dataset="engagements" from={f.from} to={f.to} />}>
        <FilterSelect label="État" value={f.status} onChange={(v) => m.set({ status: v })} options={[["", "Tous"], ...Object.entries(CONTRACT_FR)]} />
        <FilterSelect label="Type" value={f.mission_type} onChange={(v) => m.set({ mission_type: v })} options={[["", "Tous"], ["recurring", "Récurrente"], ["long_term", "Longue durée"]]} />
        <FilterSelect label="Relation" value={f.work_relationship} onChange={(v) => m.set({ work_relationship: v })} options={[["", "Toutes"], ["independent", "Indépendante"], ["employment", "Emploi salarié"]]} />
        <FilterSelect label="À surveiller" value={f.flag} onChange={(v) => m.set({ flag: v })} options={[["", "Tous"], ["overdue", "Échéances en retard"], ["disputed", "Litige ouvert"]]} />
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
        {f.user ? <Button size="sm" variant="soft" onClick={() => m.set({ user: "" })} title="Retirer le filtre par compte">Compte #{f.user} ✕</Button> : null}
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => `contrat #${r.id}`} caption="Contrats d’engagement" empty="Aucun contrat ne correspond." emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        ordering={f.ordering} onOrdering={(v) => m.set({ ordering: v })} rowActions={rowActions} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
      <ContractPanel id={open} onClose={() => setOpen(null)} onChanged={() => void list.reload()} />
    </>
  );
}

// ── Besoins ─────────────────────────────────────────────────────────────────────────────────────────────────────────

function PostingsTab() {
  const { can } = useBo();
  const manage = can("engagements.manage");
  const m = useManagedList<PostingRow, { status: string }>("/engagements/postings/", { status: "" });
  const { values: f, list } = m;
  const counts = useCounts("/engagements/postings/", { _all: "", open: "status=open", filled: "status=filled", closed: "status=closed", cancelled: "status=cancelled" }, list.count);
  const [remove, setRemove] = useState<PostingRow | null>(null);
  const [notice, setNotice] = useNotice();
  const columns: BoColumn<PostingRow>[] = [
    { key: "t", header: "Besoin", primary: true, wrap: true, cell: (r) => <span><span className="font-semibold text-ink">#{r.id} {r.title}</span><span className="block text-xs text-ash">{r.category} · {r.city} · {r.publisher.name}{r.organization ? ` (${r.organization})` : ""}</span></span> },
    { key: "s", header: "État", cell: (r) => <Tag value={r.status} label={POSTING_FR[r.status]} tone={r.status === "open" ? "success" : "gray"} /> },
    { key: "m", header: "Type", hideOnMobile: true, from: "xl", cell: (r) => `${MISSION_FR[r.mission_type]} · ${REL_FR[r.work_relationship]}` },
    { key: "a", header: "Rémunération", align: "right", hideOnMobile: true, from: "lg", cell: (r) => `${moneyLabel(r.amount)} ${PERIOD_FR[r.period]}` },
    { key: "c", header: "Candidatures", align: "right", hideOnMobile: true, cell: (r) => r.applications },
    { key: "d", header: "Publié le", hideOnMobile: true, from: "2xl", cell: (r) => dd(r.created_at) },
  ];
  const removable = (r: PostingRow) => manage && ["open", "draft"].includes(r.status);
  const rowActions = (r: PostingRow): RowAction[] => [
    { label: "Retirer le besoin", icon: Trash2, tone: "danger", onClick: () => setRemove(r), hidden: !removable(r) },
    { label: "Fiche du publicateur", icon: Users, href: `/backoffice/users/${r.publisher.id}`, hidden: !can("users.view") },
  ];
  const bulk: BulkAction<PostingRow>[] | undefined = manage
    ? [{ id: "remove", label: "Retirer", icon: Trash2, tone: "danger", title: "Retirer les besoins sélectionnés ?", confirmLabel: "Retirer", description: "Chaque besoin est annulé (jamais supprimé), ses candidatures ouvertes sont refusées et son auteur est prévenu avec ce motif.", eligible: (r) => ["open", "draft"].includes(r.status), run: (r, b) => bo.post(`/engagements/postings/${r.id}/remove/`, b) }]
    : undefined;
  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <StatusChips items={[["", "Tous"], ["open", "Ouverts"], ["filled", "Pourvus"], ["closed", "Clos"], ["cancelled", "Annulés"]]} value={f.status} onChange={(v) => m.set({ status: v })} counts={counts} label="État du besoin" />
      <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="Titre, ville, description…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading} />
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => `besoin #${r.id}`} caption="Besoins publiés" empty="Aucun besoin ne correspond." emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        rowActions={rowActions} bulk={bulk} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
      <ReasonModal open={Boolean(remove)} tone="danger" title="Retirer ce besoin ?" description="Il est annulé (jamais supprimé), les candidatures ouvertes sont refusées et son auteur est prévenu avec ce motif." confirmLabel="Retirer le besoin" onClose={() => setRemove(null)}
        request={remove ? postTo(`/engagements/postings/${remove.id}/remove/`) : async () => undefined} onDone={() => { setRemove(null); setNotice("Besoin retiré."); void list.reload(); }} />
    </>
  );
}

// ── Échéances ───────────────────────────────────────────────────────────────────────────────────────────────────────

function InstallmentsTab() {
  const { can } = useBo();
  const m = useManagedList<InstRow, { status: string; fee: string; user: string; contract: string; from: string; to: string }>("/engagements/installments/", { status: "", fee: "", user: "", contract: "", from: "", to: "" });
  const { values: f, list } = m;
  const counts = useCounts("/engagements/installments/", { _all: "", overdue: "status=overdue", due: "status=due", partial: "status=partial", paid: "status=paid" }, list.count);
  const [settle, setSettle] = useState<InstRow | null>(null);
  const [waive, setWaive] = useState<InstRow | null>(null);
  const [notice, setNotice] = useNotice();
  const manage = can("finance.manage");
  const columns: BoColumn<InstRow>[] = [
    { key: "t", header: "Échéance", primary: true, wrap: true, cell: (r) => <span><span className="font-semibold text-ink">#{r.id} · contrat #{r.contract.id} · n° {r.number}</span><span className="block text-xs text-ash">{r.principal.name} → {r.worker.name}</span></span> },
    { key: "s", header: "État", cell: (r) => <Tag value={r.status} label={INST_FR[r.status]} tone={INST_TONE[r.status]} /> },
    { key: "d", header: "À régler le", hideOnMobile: true, from: "lg", cell: (r) => dd(r.due_date) },
    { key: "m", header: "Total / solde", align: "right", hideOnMobile: true, from: "xl", cell: (r) => `${moneyLabel(r.total)} / ${moneyLabel(r.balance)}` },
    { key: "f", header: "Commission", hideOnMobile: true, from: "xl", cell: (r) => Number(r.platform_fee) > 0 ? <span>{moneyLabel(r.platform_fee)} <Badge tone={r.platform_fee_status === "due" ? "warning" : "gray"}>{{ due: "à régler", settled: "réglée", waived: "abandonnée", none: "—" }[r.platform_fee_status] ?? r.platform_fee_status}</Badge></span> : "—" },
    { key: "act", header: "Commission", align: "right", cell: (r) => manage && r.platform_fee_status === "due" ? <span className="flex justify-end gap-2"><Button size="sm" leftIcon={<Check aria-hidden className="h-4 w-4" />} onClick={() => setSettle(r)}>Réglée</Button><Button size="sm" variant="outline" onClick={() => setWaive(r)}>Abandonner</Button></span> : <span className="text-ash">—</span> },
  ];
  const rowActions = (r: InstRow): RowAction[] => [
    { label: "Examiner le contrat", icon: Eye, href: `/backoffice/engagements?tab=contracts&q=${encodeURIComponent(r.contract.title)}` },
    { label: "Commission réglée", icon: Check, onClick: () => setSettle(r), hidden: !manage || r.platform_fee_status !== "due" },
    { label: "Abandonner la commission", icon: Undo2, tone: "danger", onClick: () => setWaive(r), hidden: !manage || r.platform_fee_status !== "due" },
  ];
  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <Alert tone="info" className="mb-4">Le Back-Office suit les échéances mais ne confirme jamais un paiement entre les parties : seule la contrepartie le fait. Il règle uniquement la commission de la plateforme, avec la référence du règlement effectué hors plateforme.</Alert>
      <StatusChips items={[["", "Toutes"], ["overdue", "En retard"], ["due", "À régler"], ["partial", "Partielles"], ["paid", "Réglées"]]} value={f.status} onChange={(v) => m.set({ status: v })} counts={counts} label="État de l’échéance" />
      <FilterBar search={undefined} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading} actions={<ExportButton dataset="engagement_installments" from={f.from} to={f.to} />}>
        <FilterSelect label="Commission" value={f.fee} onChange={(v) => m.set({ fee: v })} options={[["", "Toutes"], ["due", "À régler"], ["settled", "Réglées"], ["waived", "Abandonnées"]]} />
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
        {f.user ? <Button size="sm" variant="soft" onClick={() => m.set({ user: "" })} title="Retirer le filtre par compte">Compte #{f.user} ✕</Button> : null}
        {f.contract ? <Button size="sm" variant="soft" onClick={() => m.set({ contract: "" })} title="Retirer le filtre par contrat">Contrat #{f.contract} ✕</Button> : null}
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => `échéance #${r.id}`} caption="Échéances" empty="Aucune échéance ne correspond." emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        rowActions={rowActions} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
      <ReasonModal open={Boolean(settle)} title="Commission réglée" description="Indiquez la référence du règlement effectué hors plateforme." reasonLabel="Référence du règlement" reasonKey="reference" confirmLabel="Marquer comme réglée" onClose={() => setSettle(null)}
        request={(b) => bo.post(`/engagements/installments/${settle?.id}/fee/`, { status: "settled", reference: b.reference })} onDone={() => { setSettle(null); setNotice("Commission marquée comme réglée."); void list.reload(); }} />
      <ReasonModal open={Boolean(waive)} tone="danger" title="Abandonner la commission ?" description="Décision commerciale journalisée ; le montant dû entre les parties n’est pas modifié." confirmLabel="Abandonner" onClose={() => setWaive(null)}
        request={(b) => bo.post(`/engagements/installments/${waive?.id}/fee/`, { status: "waived", reason: b.reason })} onDone={() => { setWaive(null); setNotice("Commission abandonnée."); void list.reload(); }} />
    </>
  );
}

// ── Litiges ─────────────────────────────────────────────────────────────────────────────────────────────────────────

function DisputesTab() {
  const { can } = useBo();
  const m = useManagedList<DisputeRow, { status: string; kind: string; user: string; from: string; to: string }>("/engagements/disputes/", { status: "open,under_review", kind: "", user: "", from: "", to: "" });
  const { values: f, list } = m;
  const counts = useCounts("/engagements/disputes/", { "open,under_review": "status=open,under_review", "resolved,rejected": "status=resolved,rejected", _all: "" }, list.count);
  const [open, setOpen] = useState<number | null>(null);
  const [resolve, setResolve] = useState<DisputeRow | null>(null);
  const [notice, setNotice] = useNotice();
  const [detail, setDetail] = useState<(DisputeRow & { reason: string; resolution: string; principal: { name: string }; worker: { name: string } }) | null>(null);
  useEffect(() => { if (open === null) { setDetail(null); return; } bo.get<typeof detail>(`/engagements/disputes/${open}/`).then(setDetail).catch(() => setDetail(null)); }, [open]);
  const columns: BoColumn<DisputeRow>[] = [
    { key: "t", header: "Litige", primary: true, wrap: true, cell: (r) => <span><span className="font-semibold text-ink">#{r.id} · {KIND_FR[r.kind]}</span><span className="block text-xs text-ash">Contrat #{r.contract.id} {r.contract.title} · ouvert par {r.opened_by.name} ({r.opened_by_role === "worker" ? "prestataire" : "donneur d’ordre"})</span></span> },
    { key: "s", header: "État", cell: (r) => <Tag value={r.status} label={DISPUTE_FR[r.status]} /> },
    { key: "d", header: "Ouvert le", hideOnMobile: true, from: "lg", cell: (r) => dd(r.created_at) },
  ];
  const rowActions = (r: DisputeRow): RowAction[] => [
    { label: can("engagements.manage") && ["open", "under_review"].includes(r.status) ? "Traiter le litige" : "Voir le litige", icon: Gavel, onClick: () => setOpen(r.id) },
    { label: "Fiche de la personne", icon: Users, href: `/backoffice/users/${r.opened_by.id}`, hidden: !can("users.view") },
  ];
  async function review(id: number) {
    try { await bo.post(`/engagements/disputes/${id}/review/`); setNotice("Litige pris en charge."); void list.reload(); setOpen(null); } catch (e) { setNotice(boError(e, "Action impossible.")); }
  }
  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <StatusChips items={[["open,under_review", "À traiter"], ["resolved,rejected", "Traités"], ["", "Tous"]]} value={f.status} onChange={(v) => m.set({ status: v })} counts={counts} label="État du litige" />
      <FilterBar activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
        <FilterSelect label="Nature" value={f.kind} onChange={(v) => m.set({ kind: v })} options={[["", "Toutes"], ...Object.entries(KIND_FR)]} />
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
        {f.user ? <Button size="sm" variant="soft" onClick={() => m.set({ user: "" })} title="Retirer le filtre par compte">Compte #{f.user} ✕</Button> : null}
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => `litige #${r.id}`} caption="Litiges d’engagement" empty="Aucun litige dans cet état." emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        rowActions={rowActions} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
      <Modal open={open !== null && !resolve} onClose={() => setOpen(null)} size="lg" title={detail ? `Litige #${detail.id} — ${KIND_FR[detail.kind]}` : "Litige"}>
        {detail ? (
          <div className="space-y-4">
            <KV items={[["Contrat", `#${detail.contract.id} ${detail.contract.title}`], ["État", DISPUTE_FR[detail.status]], ["Donneur d’ordre", detail.principal.name], ["Prestataire", detail.worker.name], ["Ouvert par", `${detail.opened_by.name} (${detail.opened_by_role === "worker" ? "prestataire" : "donneur d’ordre"})`], ["Ouvert le", dt(detail.created_at)]]} />
            <p className="whitespace-pre-line rounded-panel bg-canvas p-3 text-sm text-inkSoft">{detail.reason}</p>
            {detail.resolution ? <p className="rounded-panel bg-primarySoft/60 p-3 text-sm text-inkSoft"><strong>Décision :</strong> {detail.resolution}</p> : null}
            {can("engagements.manage") && ["open", "under_review"].includes(detail.status) ? (
              <div className="flex flex-wrap gap-2">
                {detail.status === "open" ? <Button variant="outline" onClick={() => void review(detail.id)}>Prendre en charge</Button> : null}
                <Button onClick={() => setResolve(detail)}>Rendre une décision</Button>
              </div>
            ) : null}
          </div>
        ) : <p className="text-sm text-inkSoft" role="status">Chargement…</p>}
      </Modal>
      <ReasonModal open={Boolean(resolve)} title="Décision sur le litige" description="La décision est communiquée aux deux parties. Suspendre ou résilier applique l’action au contrat ; un paiement n’est jamais corrigé par la plateforme." confirmLabel="Enregistrer la décision" reasonLabel="Décision motivée" reasonKey="resolution"
        fields={[{ key: "accepted", label: "Issue", type: "select", options: [["true", "Litige résolu (fondé)"], ["false", "Litige rejeté (non fondé)"]] }, { key: "resolution_action", label: "Action sur le contrat", type: "select", options: [["none", "Aucune"], ["mediated", "Médiation / accord des parties"], ["suspend", "Suspendre le contrat"], ["terminate", "Résilier le contrat"]] }]}
        onClose={() => setResolve(null)} request={(b) => bo.post(`/engagements/disputes/${resolve?.id}/resolve/`, { accepted: (b.accepted ?? "true") === "true", resolution_action: b.resolution_action || "none", resolution: b.resolution })}
        onDone={() => { setResolve(null); setOpen(null); setNotice("Décision enregistrée."); void list.reload(); }} />
    </>
  );
}

// ── Évaluations ─────────────────────────────────────────────────────────────────────────────────────────────────────

function EvaluationsTab() {
  const { can } = useBo();
  const manage = can("engagements.manage");
  const m = useManagedList<EvalRow, { hidden: string; flag: string; from: string; to: string }>("/engagements/evaluations/", { hidden: "", flag: "", from: "", to: "" });
  const { values: f, list } = m;
  const counts = useCounts("/engagements/evaluations/", { _all: "", false: "hidden=false", true: "hidden=true", reported: "flag=reported" }, list.count);
  const [target, setTarget] = useState<{ row: EvalRow; op: "hide" | "restore" } | null>(null);
  const [notice, setNotice] = useNotice();
  const columns: BoColumn<EvalRow>[] = [
    { key: "t", header: "Évaluation", primary: true, wrap: true, cell: (r) => <span><span className="font-semibold text-ink">{r.rating} / 5 · {r.kind === "final" ? "finale" : "périodique"}</span><span className="block text-xs text-ash">{r.author.name} → {r.subject.name} · contrat #{r.contract.id}</span></span> },
    { key: "c", header: "Commentaire", wrap: true, cell: (r) => <span className="text-inkSoft">{r.comment || "—"}</span> },
    { key: "s", header: "État", cell: (r) => <span className="flex flex-wrap gap-1">{r.is_hidden ? <Badge tone="danger">Masquée</Badge> : <Badge tone="success">Publiée</Badge>}{r.reports ? <Badge tone="warning">{r.reports} signalement(s)</Badge> : null}</span> },
    { key: "d", header: "Le", hideOnMobile: true, from: "lg", cell: (r) => dd(r.created_at) },
  ];
  const rowActions = (r: EvalRow): RowAction[] => [
    { label: "Masquer l’évaluation", icon: EyeOff, tone: "danger", onClick: () => setTarget({ row: r, op: "hide" }), hidden: !manage || r.is_hidden },
    { label: "Rétablir l’évaluation", icon: Undo2, onClick: () => setTarget({ row: r, op: "restore" }), hidden: !manage || !r.is_hidden },
  ];
  const bulk: BulkAction<EvalRow>[] | undefined = manage
    ? [
        { id: "hide", label: "Masquer", icon: EyeOff, tone: "danger", title: "Masquer les évaluations sélectionnées ?", confirmLabel: "Masquer", description: "Retirées du profil et du calcul de la moyenne ; le texte n’est jamais modifié ni supprimé.", eligible: (r) => !r.is_hidden, run: (r, b) => bo.post(`/engagements/evaluations/${r.id}/hide/`, b) },
        { id: "restore", label: "Rétablir", icon: Undo2, title: "Rétablir les évaluations sélectionnées ?", confirmLabel: "Rétablir", eligible: (r) => r.is_hidden, run: (r, b) => bo.post(`/engagements/evaluations/${r.id}/restore/`, b) },
      ]
    : undefined;
  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <StatusChips items={[["", "Toutes"], ["false", "Publiées"], ["true", "Masquées"]]} value={f.hidden} onChange={(v) => m.set({ hidden: v })} counts={counts} label="Visibilité" />
      <FilterBar activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
        <FilterSelect label="Signalements" value={f.flag} onChange={(v) => m.set({ flag: v })} options={[["", "Tous"], ["reported", "Signalées"]]} />
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => `évaluation #${r.id}`} caption="Évaluations d’engagement" empty="Aucune évaluation ne correspond." emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        rowActions={rowActions} bulk={bulk} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
      <ReasonModal open={target?.op === "hide"} tone="danger" title="Masquer cette évaluation ?" description="Retirée du profil et du calcul de la moyenne ; le texte n’est jamais modifié ni supprimé. Les signalements ouverts sont clos." confirmLabel="Masquer" onClose={() => setTarget(null)}
        request={target ? postTo(`/engagements/evaluations/${target.row.id}/hide/`) : async () => undefined} onDone={() => { setTarget(null); setNotice("Évaluation masquée."); void list.reload(); }} />
      <ReasonModal open={target?.op === "restore"} title="Rétablir cette évaluation ?" confirmLabel="Rétablir" onClose={() => setTarget(null)} request={target ? postTo(`/engagements/evaluations/${target.row.id}/restore/`) : async () => undefined} onDone={() => { setTarget(null); setNotice("Évaluation rétablie."); void list.reload(); }} />
    </>
  );
}

// ── Règles ──────────────────────────────────────────────────────────────────────────────────────────────────────────

const RULE_BOOLS: [keyof RuleSet, string][] = [["allow_recurring", "Prestations récurrentes autorisées"], ["allow_long_term", "Engagements de longue durée autorisés"], ["allow_employment", "Emploi salarié autorisé (désactivé par défaut)"]];
const RULE_NUMS: [keyof RuleSet, string, string][] = [["max_duration_months", "Durée maximale (mois)", "1 à 240"], ["min_notice_days_independent", "Préavis minimal indépendant (jours)", "0 à 365"], ["min_notice_days_employment", "Préavis minimal emploi (jours)", "0 à 365"],
  ["commission_percent_independent", "Commission Tratra — indépendant (%)", "0 à 50"], ["commission_percent_employment", "Commission Tratra — emploi (%)", "0 à 50"], ["max_advance_percent", "Avance maximale (% d’une échéance)", "0 à 100"], ["late_grace_days", "Tolérance avant retard (jours)", "0 à 60"],
  ["min_days_for_evaluation", "Ancienneté avant la 1re évaluation (jours)", "0 à 365"], ["evaluation_interval_days", "Intervalle entre évaluations périodiques (jours)", "7 à 365"], ["evaluation_edit_days", "Délai de modification d’une évaluation (jours)", "0 à 60"]];

function RuleEditor({ scope, name, rules, onClose, onDone }: { scope: string | null; name: string; rules: RuleSet | null; onClose: () => void; onDone: () => void }) {
  const [v, setV] = useState<Record<string, string | boolean>>({});
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  useEffect(() => { if (scope && rules) { setV({ ...rules } as unknown as Record<string, string | boolean>); setReason(""); setError(""); setErrors({}); } }, [scope, rules]);
  async function save() {
    setBusy(true); setError(""); setErrors({});
    const body: Record<string, unknown> = { reason };
    for (const [k] of RULE_BOOLS) body[k] = Boolean(v[k]);
    for (const [k] of RULE_NUMS) body[k] = v[k];
    body.commission_payer = v.commission_payer;
    try { await bo.put(`/engagements/rules/${scope}/`, body); onDone(); } catch (e) { setErrors(fieldErrors(e)); setError(boError(e, "Enregistrement impossible.")); } finally { setBusy(false); }
  }
  return (
    <Modal open={scope !== null} onClose={onClose} size="lg" dismissible={!busy} title={`Règles — ${name}`}
      description="Règles de fonctionnement de Tratra, pas un avis juridique. Chaque modification est journalisée (avant / après)."
      footer={<><Button variant="outline" onClick={onClose} disabled={busy}>Annuler</Button><Button loading={busy} onClick={() => void save()}>Enregistrer</Button></>}>
      <div className="space-y-4">
        {RULE_BOOLS.map(([k, l]) => <Checkbox key={k} label={l} checked={Boolean(v[k])} onChange={(e) => setV({ ...v, [k]: e.target.checked })} />)}
        {errors.allow_employment ? <p role="alert" className="text-xs text-dangerInk">{errors.allow_employment}</p> : null}
        <div className="grid gap-4 sm:grid-cols-2">
          {RULE_NUMS.map(([k, l, h]) => <TextField key={k} label={l} hint={h} inputMode="decimal" value={String(v[k] ?? "")} error={errors[k]} onChange={(e) => setV({ ...v, [k]: e.target.value })} />)}
          <SelectField label="Commission payée par" value={String(v.commission_payer ?? "principal")} error={errors.commission_payer} onChange={(e) => setV({ ...v, commission_payer: e.target.value })}>
            <option value="principal">Le donneur d’ordre</option><option value="worker">Le prestataire</option>
          </SelectField>
        </div>
        <TextField label="Motif de la modification" optional value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} />
        {error ? <Alert tone="danger">{error}</Alert> : null}
      </div>
    </Modal>
  );
}

function RulesTab() {
  const { can } = useBo();
  const [data, setData] = useState<RulesIndex | null>(null);
  const [error, setError] = useState("");
  const [edit, setEdit] = useState<{ scope: string; name: string; rules: RuleSet } | null>(null);
  const [reset, setReset] = useState<{ id: number; name: string } | null>(null);
  const [notice, setNotice] = useNotice();
  const load = useCallback(async () => { try { setData(await bo.get<RulesIndex>("/engagements/rules/")); setError(""); } catch (e) { setError(boError(e, "Règles indisponibles.")); } }, []);
  useEffect(() => { void load(); }, [load]);
  const manage = can("settings.manage");
  const summary = (r: RuleSet) => `${r.allow_employment ? "Emploi salarié ouvert" : "Indépendant uniquement"} · max ${r.max_duration_months} mois · préavis ${r.min_notice_days_independent} j · commission ${Number(r.commission_percent_independent)} % · avance ${r.max_advance_percent} %`;
  if (error) return <Alert tone="danger">{error}</Alert>;
  if (!data) return <SkeletonStats />;
  return (
    <div className="space-y-5">
      {notice ? <Alert tone="success">{notice}</Alert> : null}
      <Alert tone="info">{data.notice} {manage ? "" : "Lecture seule : la modification exige le droit « Règles métier et intégrations »."}</Alert>
      <Card padding="md">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div><h2 className="font-display text-lg font-bold text-ink">Règle générale</h2><p className="mt-1 text-sm text-ash">{summary(data.default)}{data.default.customized ? "" : " (valeurs d’usine)"}</p></div>
          {manage ? <Button variant="outline" onClick={() => setEdit({ scope: "default", name: "règle générale", rules: data.default })}>Modifier</Button> : null}
        </div>
      </Card>
      <Card padding="none">
        <ul className="divide-y divide-lineSoft">
          {data.categories.map((c) => (
            <li key={c.category.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
              <div className="min-w-0"><p className="font-semibold text-ink">{c.category.name} {c.customized ? <Badge tone="primary">Personnalisée</Badge> : <Badge tone="gray">Règle générale</Badge>}</p><p className="text-xs text-ash">{summary(c)}</p></div>
              {manage ? (
                <span className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => setEdit({ scope: String(c.category.id), name: c.category.name, rules: c })}>{c.customized ? "Modifier" : "Personnaliser"}</Button>
                  {c.customized ? <Button size="sm" variant="ghost" onClick={() => setReset({ id: c.category.id, name: c.category.name })}>Revenir à la règle générale</Button> : null}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      </Card>
      <RuleEditor scope={edit?.scope ?? null} name={edit?.name ?? ""} rules={edit?.rules ?? null} onClose={() => setEdit(null)} onDone={() => { setEdit(null); setNotice("Règles enregistrées."); void load(); }} />
      <Modal open={Boolean(reset)} onClose={() => setReset(null)} size="sm" title={`Revenir à la règle générale pour ${reset?.name} ?`} footer={<><Button variant="outline" onClick={() => setReset(null)}>Annuler</Button>
        <Button variant="danger" onClick={async () => { try { await bo.delete(`/engagements/rules/${reset?.id}/`); setReset(null); setNotice("Règle de la catégorie supprimée."); void load(); } catch (e) { setNotice(boError(e, "Action impossible.")); setReset(null); } }}>Revenir à la règle générale</Button></>}>
        <p className="text-sm text-inkSoft">Les contrats existants conservent leurs conditions acceptées ; seules les nouvelles saisies suivent la règle générale.</p>
      </Modal>
    </div>
  );
}

export default function EngagementsBoPage() {
  const [tab, setTab] = useTabParam(["overview", "contracts", "postings", "installments", "disputes", "evaluations", "rules"] as const, "overview");
  return (
    <>
      <PageHeader title="Engagements" description="Contrats récurrents et de longue durée : suivi, échéances, litiges, modération et règles par métier. La plateforme ne confirme jamais un paiement ni ne modifie un montant." />
      <Tabs ariaLabel="Sections" value={tab} onChange={setTab} className="mb-5"
        items={[{ id: "overview", label: "Aperçu" }, { id: "contracts", label: "Contrats" }, { id: "postings", label: "Besoins" }, { id: "installments", label: "Échéances" }, { id: "disputes", label: "Litiges" }, { id: "evaluations", label: "Évaluations" }, { id: "rules", label: "Règles" }]} />
      {tab === "overview" ? <OverviewTab /> : tab === "contracts" ? <ContractsTab /> : tab === "postings" ? <PostingsTab /> : tab === "installments" ? <InstallmentsTab /> : tab === "disputes" ? <DisputesTab /> : tab === "evaluations" ? <EvaluationsTab /> : <RulesTab />}
    </>
  );
}
