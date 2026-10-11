"use client";
import { useState } from "react";
import { Building2, Eye, Pause, Play } from "lucide-react";
import { Badge, PageHeader, Tabs } from "@/components/ds";
import { bo, moneyLabel } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useCounts, useManagedList } from "@/lib/useBoList";
import { DateRange, FilterBar, FilterSelect, ListView, ReasonModal, SearchBox, StatusChips, dd, dt, postTo, useNotice, useTabParam, type BoColumn, type BulkAction, type RowAction } from "../_components/ui";

interface Org { id: number; name: string; city: string | null; industry: string | null; owner: string; is_active: boolean; members: number; sites: number; open_requests: number; created_at: string }
interface Req { id: number; number: string; organization: string; organization_id: number; site: string; title: string; priority: string; status: string; status_label: string; requested_by: string; created_at: string; due_response_at: string | null; due_resolution_at: string | null; overdue: boolean; booking_id: number | null }
interface Inv { id: number; number: string; organization: string; organization_id: number; period_start: string; period_end: string; total: string; status: string; lines: number; created_at: string }

const PRIORITY_FR: Record<string, string> = { low: "Basse", normal: "Normale", high: "Haute", urgent: "Urgente" };
const LEVEL_TONE: Record<string, "success" | "warning" | "danger"> = { ok: "success", warning: "warning", exceeded: "danger" };

function OrganizationsTab({ version }: { version: number }) {
  const { can } = useBo();
  const manage = can("business.manage");
  const m = useManagedList<Org, { active: string }>("/business/organizations/", { active: "" });
  const { values: f, list } = m;
  const counts = useCounts("/business/organizations/", { _all: "", true: "active=true", false: "active=false" }, `${list.count}-${version}`);
  const [target, setTarget] = useState<{ row: Org; op: "suspend" | "reactivate" } | null>(null);
  const [notice, setNotice] = useNotice();
  const columns: BoColumn<Org>[] = [
    { key: "name", header: "Organisation", primary: true, sort: "name", cell: (r) => <span className="font-semibold text-ink">{r.name}</span> },
    { key: "owner", header: "Propriétaire", cell: (r) => r.owner },
    { key: "city", header: "Ville", hideOnMobile: true, from: "xl", cell: (r) => r.city ?? "—" },
    { key: "stats", header: "Structure", hideOnMobile: true, from: "xl", cell: (r) => `${r.members} membre(s) · ${r.sites} site(s)` },
    { key: "open", header: "Demandes ouvertes", align: "right", sort: "open", cell: (r) => r.open_requests },
    { key: "state", header: "Statut", cell: (r) => <Badge tone={r.is_active ? "success" : "danger"}>{r.is_active ? "Active" : "Suspendue"}</Badge> },
    { key: "created", header: "Créée le", sort: "created_at", hideOnMobile: true, from: "2xl", cell: (r) => dd(r.created_at) },
  ];
  const rowActions = (r: Org): RowAction[] => [
    { label: "Ouvrir la fiche", icon: Eye, href: `/backoffice/business/${r.id}` },
    { label: "Ses demandes d’intervention", icon: Building2, href: `/backoffice/business?tab=requests&q=${encodeURIComponent(r.name)}` },
    { label: "Suspendre l’organisation", icon: Pause, tone: "danger", onClick: () => setTarget({ row: r, op: "suspend" }), hidden: !manage || !r.is_active },
    { label: "Réactiver l’organisation", icon: Play, onClick: () => setTarget({ row: r, op: "reactivate" }), hidden: !manage || r.is_active },
  ];
  const bulk: BulkAction<Org>[] | undefined = manage
    ? [
        { id: "suspend", label: "Suspendre", icon: Pause, tone: "danger", title: "Suspendre les organisations sélectionnées ?", confirmLabel: "Suspendre", description: "Leurs membres perdent l’accès à Tratra Business ; aucune donnée n’est supprimée ni aucune demande annulée.", eligible: (r) => r.is_active, run: (r, b) => bo.post(`/business/organizations/${r.id}/suspend/`, b) },
        { id: "reactivate", label: "Réactiver", icon: Play, title: "Réactiver les organisations sélectionnées ?", confirmLabel: "Réactiver", eligible: (r) => !r.is_active, run: (r, b) => bo.post(`/business/organizations/${r.id}/reactivate/`, b) },
      ]
    : undefined;
  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <StatusChips items={[["", "Toutes"], ["true", "Actives"], ["false", "Suspendues"]]} value={f.active} onChange={(v) => m.set({ active: v })} counts={counts} label="Statut de l’organisation" />
      <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="Nom, raison sociale, ville, RCCM…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading} />
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowHref={(r) => `/backoffice/business/${r.id}`} rowLabel={(r) => r.name} caption="Organisations" empty="Aucune organisation ne correspond." emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        ordering={f.ordering} onOrdering={(v) => m.set({ ordering: v })} rowActions={rowActions} bulk={bulk} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
      <ReasonModal open={target?.op === "suspend"} title={`Suspendre ${target?.row.name ?? "cette organisation"} ?`} description="Ses membres perdent l’accès à Tratra Business ; aucune donnée n’est supprimée ni aucune demande annulée." confirmLabel="Suspendre" tone="danger" onClose={() => setTarget(null)}
        request={target ? postTo(`/business/organizations/${target.row.id}/suspend/`) : async () => undefined} onDone={() => { setTarget(null); setNotice("Organisation suspendue."); void list.reload(); }} />
      <ReasonModal open={target?.op === "reactivate"} title={`Réactiver ${target?.row.name ?? "cette organisation"} ?`} confirmLabel="Réactiver" onClose={() => setTarget(null)}
        request={target ? postTo(`/business/organizations/${target.row.id}/reactivate/`) : async () => undefined} onDone={() => { setTarget(null); setNotice("Organisation réactivée."); void list.reload(); }} />
    </>
  );
}

const REQUEST_STATES: [string, string][] = [["pending_approval", "En attente de validation"], ["approved", "Validée"], ["dispatched", "Artisan sollicité"], ["scheduled", "Planifiée"], ["in_progress", "En cours"], ["completed", "Terminée"], ["rejected", "Refusée"], ["cancelled", "Annulée"]];

function RequestsTab() {
  const m = useManagedList<Req, { status: string; priority: string; overdue: string; from: string; to: string }>("/business/requests/", { status: "", priority: "", overdue: "", from: "", to: "" });
  const { values: f, list } = m;
  const counts = useCounts("/business/requests/", { _all: "", overdue: "overdue=true", pending_approval: "status=pending_approval", in_progress: "status=in_progress" }, list.count);
  const columns: BoColumn<Req>[] = [
    { key: "num", header: "Demande", primary: true, wrap: true, cell: (r) => <span className="font-semibold text-ink">{r.number} — {r.title}</span> },
    { key: "org", header: "Organisation", hideOnMobile: true, from: "xl", cell: (r) => `${r.organization} · ${r.site}` },
    { key: "prio", header: "Priorité", cell: (r) => <Badge tone={r.priority === "urgent" ? "danger" : r.priority === "high" ? "warning" : "gray"}>{PRIORITY_FR[r.priority] ?? r.priority}</Badge> },
    { key: "status", header: "Statut", cell: (r) => <span className="flex flex-wrap gap-1.5"><Badge tone="primary">{r.status_label}</Badge>{r.overdue ? <Badge tone="danger">Délai dépassé</Badge> : null}</span> },
    { key: "due", header: "Résolution due", hideOnMobile: true, from: "lg", cell: (r) => dd(r.due_resolution_at) },
    { key: "by", header: "Demandeur", hideOnMobile: true, from: "2xl", cell: (r) => r.requested_by },
  ];
  const rowActions = (r: Req): RowAction[] => [
    { label: "Ouvrir la réservation liée", icon: Eye, href: `/backoffice/bookings/${r.booking_id}`, hidden: !r.booking_id },
  ];
  return (
    <>
      <StatusChips items={[["", "Toutes"], ["pending_approval", "À valider"], ["in_progress", "En cours"]]} value={f.overdue === "true" ? "overdue" : f.status} onChange={(v) => m.set(v === "overdue" ? { overdue: "true", status: "" } : { overdue: "", status: v })} counts={counts} label="Demandes" />
      <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="N°, intitulé ou organisation…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
        <FilterSelect label="Statut" value={f.status} onChange={(v) => m.set({ status: v })} options={[["", "Tous"], ...REQUEST_STATES]} />
        <FilterSelect label="Priorité" value={f.priority} onChange={(v) => m.set({ priority: v })} options={[["", "Toutes"], ["low", "Basse"], ["normal", "Normale"], ["high", "Haute"], ["urgent", "Urgente"]]} />
        <FilterSelect label="Délai" value={f.overdue} onChange={(v) => m.set({ overdue: v })} options={[["", "Tous"], ["true", "Dépassé"]]} />
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => r.number} caption="Demandes d’intervention" empty="Aucune demande ne correspond." emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        rowActions={rowActions} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
    </>
  );
}

function InvoicesTab() {
  const m = useManagedList<Inv, { status: string; from: string; to: string }>("/business/invoices/", { status: "", from: "", to: "" });
  const { values: f, list } = m;
  const columns: BoColumn<Inv>[] = [
    { key: "num", header: "Facture", primary: true, sort: "created_at", cell: (r) => <span className="font-semibold text-ink">{r.number}</span> },
    { key: "org", header: "Organisation", cell: (r) => r.organization },
    { key: "period", header: "Période", hideOnMobile: true, from: "lg", cell: (r) => `${r.period_start} → ${r.period_end}` },
    { key: "lines", header: "Lignes", align: "right", hideOnMobile: true, from: "xl", cell: (r) => r.lines },
    { key: "total", header: "Total", align: "right", sort: "total", cell: (r) => moneyLabel(r.total) },
    { key: "status", header: "Statut", cell: (r) => <Badge tone={r.status === "issued" ? "success" : "gray"}>{r.status === "issued" ? "Émise" : "Annulée"}</Badge> },
  ];
  return (
    <>
      <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="N° de facture ou organisation…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
        <FilterSelect label="Statut" value={f.status} onChange={(v) => m.set({ status: v })} options={[["", "Tous"], ["issued", "Émises"], ["void", "Annulées"]]} />
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => r.number} caption="Factures consolidées" empty="Aucune facture ne correspond." ordering={f.ordering} onOrdering={(v) => m.set({ ordering: v })}
        pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
    </>
  );
}

export default function BusinessPage() {
  const [tab, setTab] = useTabParam(["organizations", "requests", "invoices"] as const, "organizations");
  return (
    <>
      <PageHeader title="Tratra Business" description="Supervision des organisations, de leurs demandes d’intervention et de leur facturation. Lecture : le circuit de validation des demandes n’est jamais contourné ici." />
      <Tabs ariaLabel="Sections" value={tab} onChange={setTab} className="mb-4" items={[{ id: "organizations", label: "Organisations" }, { id: "requests", label: "Demandes" }, { id: "invoices", label: "Factures" }]} />
      {tab === "organizations" ? <OrganizationsTab version={0} /> : null}
      {tab === "requests" ? <RequestsTab /> : null}
      {tab === "invoices" ? <InvoicesTab /> : null}
    </>
  );
}
