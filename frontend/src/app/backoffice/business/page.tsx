"use client";
import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Modal, PageHeader, Tabs, type Column } from "@/components/ds";
import { bo, boError, moneyLabel } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useBoList, useDebounced } from "@/lib/useBoList";
import { DateRange, FilterBar, FilterSelect, KV, ListView, ReasonModal, SearchBox, Section, dt, postTo, useNotice, useTabParam } from "../_components/ui";

interface Org { id: number; name: string; city: string | null; industry: string | null; owner: string; is_active: boolean; members: number; sites: number; open_requests: number; created_at: string }
interface OrgDetail extends Org {
  legal_name: string; registration_number: string; currency: string; address: string;
  members_list: { id: number; name: string; role: string; role_label: string; is_active: boolean; phone: string | null }[];
  sites_list: { id: number; name: string; city: string | null; is_active: boolean }[];
  equipment: number; contracts: { active: number; total: number };
  requests: { by_status: Record<string, number>; late_response: number };
  budgets: { id: number; name: string; amount: string; period_start: string; period_end: string; spent: string; remaining: string; percent: number; level: string }[];
  invoices: { id: number; number: string; period_start: string; period_end: string; total: string; status: string }[];
  history: { action: string; at: string; by: string; reason: string }[];
}
interface Req { id: number; number: string; organization: string; organization_id: number; site: string; title: string; priority: string; status: string; status_label: string; requested_by: string; created_at: string; due_response_at: string | null; due_resolution_at: string | null; overdue: boolean; booking_id: number | null }
interface Inv { id: number; number: string; organization: string; organization_id: number; period_start: string; period_end: string; total: string; status: string; lines: number; created_at: string }

const PRIORITY_FR: Record<string, string> = { low: "Basse", normal: "Normale", high: "Haute", urgent: "Urgente" };
const LEVEL_TONE: Record<string, "success" | "warning" | "danger"> = { ok: "success", warning: "warning", exceeded: "danger" };

function OrgPanel({ id, onClose, onChanged }: { id: number | null; onClose: () => void; onChanged: () => void }) {
  const { can } = useBo();
  const [d, setD] = useState<OrgDetail | null>(null);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"suspend" | "reactivate" | null>(null);
  const load = useCallback(async () => {
    if (id === null) return;
    setError("");
    try { setD(await bo.get<OrgDetail>(`/business/organizations/${id}/`)); } catch (e) { setError(boError(e, "Cette organisation n’a pas pu être chargée.")); }
  }, [id]);
  useEffect(() => { setD(null); void load(); }, [load]);
  return (
    <>
      <Modal open={id !== null && mode === null} onClose={onClose} size="lg" title={d?.name ?? "Organisation"}>
        {error ? <Alert tone="danger">{error}</Alert> : null}
        {!d && !error ? <p className="text-sm text-inkSoft" role="status">Chargement…</p> : null}
        {d ? (
          <div className="space-y-5">
            {!d.is_active ? <Alert tone="danger">Organisation suspendue : ses membres n’ont plus accès à Tratra Business.</Alert> : null}
            <KV items={[["Raison sociale", d.legal_name || "—"], ["N° d’enregistrement", d.registration_number || "—"], ["Secteur", d.industry || "—"], ["Ville", d.city], ["Propriétaire", d.owner], ["Devise", d.currency],
              ["Équipements", d.equipment], ["Contrats actifs", `${d.contracts.active} / ${d.contracts.total}`], ["Demandes en retard de prise en charge", d.requests.late_response], ["Créée le", dt(d.created_at)]]} />
            <div><h3 className="mb-1.5 text-sm font-bold text-ink">Membres ({d.members_list.length})</h3>
              <ul className="divide-y divide-lineSoft text-sm">{d.members_list.map((m) => <li key={m.id} className="flex justify-between gap-3 py-1.5"><span>{m.name} <span className="text-ash">{m.phone ?? ""}</span></span><span>{m.role_label}{!m.is_active ? " · inactif" : ""}</span></li>)}</ul></div>
            <div><h3 className="mb-1.5 text-sm font-bold text-ink">Sites ({d.sites_list.length})</h3>
              <p className="text-sm text-inkSoft">{d.sites_list.map((s) => `${s.name}${s.city ? ` (${s.city})` : ""}${s.is_active ? "" : " — inactif"}`).join(" · ") || "Aucun site."}</p></div>
            {d.budgets.length ? <div><h3 className="mb-1.5 text-sm font-bold text-ink">Budgets</h3>
              <ul className="space-y-1.5 text-sm">{d.budgets.map((b) => <li key={b.id} className="flex flex-wrap items-center justify-between gap-2"><span>{b.name} — {moneyLabel(b.spent)} / {moneyLabel(b.amount)}</span><Badge tone={LEVEL_TONE[b.level] ?? "gray"}>{b.percent} %</Badge></li>)}</ul></div> : null}
            {d.invoices.length ? <div><h3 className="mb-1.5 text-sm font-bold text-ink">Dernières factures</h3>
              <ul className="space-y-1 text-sm">{d.invoices.map((i) => <li key={i.id}>{i.number} — {moneyLabel(i.total)} ({i.period_start} → {i.period_end})</li>)}</ul></div> : null}
            {d.history.length ? <ul className="divide-y divide-lineSoft text-sm">{d.history.map((h, i) => <li key={i} className="py-1.5"><strong>{h.action.replace("backoffice.", "")}</strong> — {h.by} · {dt(h.at)}{h.reason ? <span className="block text-inkSoft">{h.reason}</span> : null}</li>)}</ul> : null}
            {can("business.manage") ? <div className="flex gap-2">{d.is_active ? <Button variant="danger" onClick={() => setMode("suspend")}>Suspendre l’organisation</Button> : <Button onClick={() => setMode("reactivate")}>Réactiver l’organisation</Button>}</div> : null}
          </div>
        ) : null}
      </Modal>
      <ReasonModal open={mode === "suspend"} title="Suspendre cette organisation ?" description="Ses membres perdent l’accès à Tratra Business ; aucune donnée n’est supprimée ni aucune demande annulée." confirmLabel="Suspendre" tone="danger" onClose={() => setMode(null)}
        request={postTo(`/business/organizations/${id}/suspend/`)} onDone={() => { setMode(null); void load(); onChanged(); }} />
      <ReasonModal open={mode === "reactivate"} title="Réactiver cette organisation ?" confirmLabel="Réactiver" onClose={() => setMode(null)}
        request={postTo(`/business/organizations/${id}/reactivate/`)} onDone={() => { setMode(null); void load(); onChanged(); }} />
    </>
  );
}

export default function BusinessPage() {
  const [tab, setTab] = useTabParam(["organizations", "requests", "invoices"] as const, "organizations");
  const [notice] = useNotice();
  const [q, setQ] = useState("");
  const [active, setActive] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [overdue, setOverdue] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const orgs = useBoList<Org>("/business/organizations/", { q: useDebounced(q), active });
  const reqs = useBoList<Req>("/business/requests/", { q: useDebounced(q), status, priority, overdue, from, to });
  const invs = useBoList<Inv>("/business/invoices/", {});

  const oColumns: Column<Org>[] = [
    { key: "name", header: "Organisation", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.name}</span> },
    { key: "owner", header: "Propriétaire", cell: (r) => r.owner },
    { key: "city", header: "Ville", hideOnMobile: true, cell: (r) => r.city ?? "—" },
    { key: "stats", header: "Structure", hideOnMobile: true, cell: (r) => `${r.members} membre(s) · ${r.sites} site(s)` },
    { key: "open", header: "Demandes ouvertes", align: "right", cell: (r) => r.open_requests },
    { key: "state", header: "Statut", cell: (r) => <Badge tone={r.is_active ? "success" : "danger"}>{r.is_active ? "Active" : "Suspendue"}</Badge> },
    { key: "act", header: "", align: "right", cell: (r) => <Button size="sm" variant="outline" onClick={() => setOpen(r.id)}>Ouvrir</Button> },
  ];
  const rColumns: Column<Req>[] = [
    { key: "num", header: "Demande", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.number} — {r.title}</span> },
    { key: "org", header: "Organisation", hideOnMobile: true, cell: (r) => `${r.organization} · ${r.site}` },
    { key: "prio", header: "Priorité", cell: (r) => <Badge tone={r.priority === "urgent" ? "danger" : r.priority === "high" ? "warning" : "gray"}>{PRIORITY_FR[r.priority] ?? r.priority}</Badge> },
    { key: "status", header: "Statut", cell: (r) => <span className="flex flex-wrap gap-1.5"><Badge tone="primary">{r.status_label}</Badge>{r.overdue ? <Badge tone="danger">Délai dépassé</Badge> : null}</span> },
    { key: "due", header: "Résolution due", hideOnMobile: true, cell: (r) => dt(r.due_resolution_at) },
    { key: "by", header: "Demandeur", hideOnMobile: true, cell: (r) => r.requested_by },
  ];
  const iColumns: Column<Inv>[] = [
    { key: "num", header: "Facture", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.number}</span> },
    { key: "org", header: "Organisation", cell: (r) => r.organization },
    { key: "period", header: "Période", hideOnMobile: true, cell: (r) => `${r.period_start} → ${r.period_end}` },
    { key: "lines", header: "Lignes", align: "right", cell: (r) => r.lines },
    { key: "total", header: "Total", align: "right", cell: (r) => moneyLabel(r.total) },
    { key: "status", header: "Statut", cell: (r) => <Badge tone={r.status === "issued" ? "success" : "gray"}>{r.status === "issued" ? "Émise" : "Annulée"}</Badge> },
  ];

  return (
    <>
      <PageHeader title="Tratra Business" description="Supervision des organisations, de leurs demandes d’intervention et de leur facturation. Lecture : le circuit de validation des demandes n’est jamais contourné ici." />
      {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}
      <Tabs ariaLabel="Sections" value={tab} onChange={setTab} className="mb-4" items={[{ id: "organizations", label: "Organisations" }, { id: "requests", label: "Demandes" }, { id: "invoices", label: "Factures" }]} />
      {tab === "organizations" ? (
        <>
          <FilterBar><SearchBox value={q} onChange={setQ} placeholder="Nom, raison sociale, ville, RCCM…" /><FilterSelect label="Statut" value={active} onChange={setActive} options={[["", "Toutes"], ["true", "Actives"], ["false", "Suspendues"]]} /></FilterBar>
          <ListView list={orgs} columns={oColumns} rowKey={(r) => r.id} caption="Organisations" empty="Aucune organisation ne correspond." />
        </>
      ) : null}
      {tab === "requests" ? (
        <>
          <FilterBar>
            <SearchBox value={q} onChange={setQ} placeholder="N°, intitulé ou organisation…" />
            <FilterSelect label="Statut" value={status} onChange={setStatus} options={[["", "Tous"], ["pending_approval", "En attente de validation"], ["approved", "Validée"], ["dispatched", "Artisan sollicité"], ["scheduled", "Planifiée"], ["in_progress", "En cours"], ["completed", "Terminée"], ["rejected", "Refusée"], ["cancelled", "Annulée"]]} />
            <FilterSelect label="Priorité" value={priority} onChange={setPriority} options={[["", "Toutes"], ["low", "Basse"], ["normal", "Normale"], ["high", "Haute"], ["urgent", "Urgente"]]} />
            <FilterSelect label="Délai" value={overdue} onChange={setOverdue} options={[["", "Tous"], ["true", "Dépassé"]]} />
            <DateRange from={from} to={to} onFrom={setFrom} onTo={setTo} />
          </FilterBar>
          <ListView list={reqs} columns={rColumns} rowKey={(r) => r.id} caption="Demandes d’intervention" empty="Aucune demande ne correspond." />
        </>
      ) : null}
      {tab === "invoices" ? <Section title="Factures consolidées"><ListView list={invs} columns={iColumns} rowKey={(r) => r.id} caption="Factures consolidées" empty="Aucune facture émise." /></Section> : null}
      <OrgPanel id={open} onClose={() => setOpen(null)} onChanged={() => orgs.reload()} />
    </>
  );
}
