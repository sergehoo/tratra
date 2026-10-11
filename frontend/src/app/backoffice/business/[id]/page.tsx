"use client";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Pause, Play } from "lucide-react";
import { Alert, Badge, Button, PageHeader, SkeletonPage } from "@/components/ds";
import { bo, boError, moneyLabel } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useBoList } from "@/lib/useBoList";
import { Fiche, Pane, Restricted } from "../../_components/fiche";
import { useCrumb } from "../../_components/crumbs";
import { KV, ListView, ReasonModal, Section, dd, dt, postTo, useNotice, type BoColumn } from "../../_components/ui";

interface Detail {
  id: number; name: string; city: string | null; industry: string | null; owner: string; is_active: boolean; members: number; sites: number; open_requests: number; created_at: string;
  legal_name: string; registration_number: string; currency: string; address: string;
  members_list: { id: number; name: string; role: string; role_label: string; is_active: boolean; phone: string | null }[];
  sites_list: { id: number; name: string; city: string | null; is_active: boolean }[];
  equipment: number; contracts: { active: number; total: number };
  requests: { by_status: Record<string, number>; late_response: number };
  budgets: { id: number; name: string; amount: string; period_start: string; period_end: string; spent: string; remaining: string; percent: number; level: string }[];
  invoices: { id: number; number: string; period_start: string; period_end: string; total: string; status: string }[];
  history: { action: string; at: string; by: string; reason: string }[];
}
interface Req { id: number; number: string; title: string; site: string; priority: string; status: string; status_label: string; created_at: string; overdue: boolean }
interface Inv { id: number; number: string; period_start: string; period_end: string; total: string; status: string; lines: number }
interface ContractRow { id: number; title: string; status: string; amount: string; worker: { name: string } }
interface AuditRow { id: number; at: string; actor: string; action: string }

const PRIORITY_FR: Record<string, string> = { low: "Basse", normal: "Normale", high: "Haute", urgent: "Urgente" };
const LEVEL_TONE: Record<string, "success" | "warning" | "danger"> = { ok: "success", warning: "warning", exceeded: "danger" };

function RequestsPane({ id }: { id: number }) {
  const list = useBoList<Req>("/business/requests/", { organization: id }, 10);
  const columns: BoColumn<Req>[] = [
    { key: "n", header: "Demande", primary: true, wrap: true, cell: (r) => <span className="font-semibold text-ink">{r.number} — {r.title}</span> },
    { key: "p", header: "Priorité", cell: (r) => <Badge tone={r.priority === "urgent" ? "danger" : r.priority === "high" ? "warning" : "gray"}>{PRIORITY_FR[r.priority] ?? r.priority}</Badge> },
    { key: "s", header: "Statut", cell: (r) => <span className="flex flex-wrap gap-1.5"><Badge tone="primary">{r.status_label}</Badge>{r.overdue ? <Badge tone="danger">Délai dépassé</Badge> : null}</span> },
    { key: "site", header: "Site", hideOnMobile: true, cell: (r) => r.site },
    { key: "d", header: "Créée le", hideOnMobile: true, cell: (r) => dd(r.created_at) },
  ];
  return <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => r.number} caption="Demandes d’intervention" empty="Aucune demande d’intervention." />;
}

function InvoicesPane({ id }: { id: number }) {
  const list = useBoList<Inv>("/business/invoices/", { organization: id }, 10);
  const columns: BoColumn<Inv>[] = [
    { key: "n", header: "Facture", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.number}</span> },
    { key: "p", header: "Période", cell: (r) => `${r.period_start} → ${r.period_end}` },
    { key: "l", header: "Lignes", align: "right", hideOnMobile: true, cell: (r) => r.lines },
    { key: "t", header: "Total", align: "right", cell: (r) => moneyLabel(r.total) },
    { key: "s", header: "Statut", cell: (r) => <Badge tone={r.status === "issued" ? "success" : "gray"}>{r.status === "issued" ? "Émise" : "Annulée"}</Badge> },
  ];
  return <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => r.number} caption="Factures consolidées" empty="Aucune facture émise." />;
}

function ContractsPane({ name }: { name: string }) {
  const list = useBoList<ContractRow>("/engagements/contracts/", { q: name }, 10);
  const columns: BoColumn<ContractRow>[] = [
    { key: "t", header: "Contrat", primary: true, wrap: true, cell: (r) => <span className="font-semibold text-ink">#{r.id} {r.title}</span> },
    { key: "s", header: "État", cell: (r) => <Badge tone={r.status === "active" ? "success" : "gray"}>{r.status}</Badge> },
    { key: "w", header: "Prestataire", hideOnMobile: true, cell: (r) => r.worker.name },
    { key: "a", header: "Rémunération", align: "right", cell: (r) => moneyLabel(r.amount) },
  ];
  return (
    <>
      <p className="mb-3 flex items-center justify-between text-sm text-inkSoft"><span><strong className="text-ink">{list.count}</strong> contrat(s) d’engagement</span><Link className="font-semibold text-primaryDark underline underline-offset-2" href={`/backoffice/engagements?tab=contracts&q=${encodeURIComponent(name)}`}>Voir tout dans le module</Link></p>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => `contrat #${r.id}`} caption="Contrats d’engagement" empty="Aucun contrat d’engagement." />
    </>
  );
}

function AuditPane({ id, history, canAudit }: { id: number; history: Detail["history"]; canAudit: boolean }) {
  const list = useBoList<AuditRow>("/security/audit/", canAudit ? { target_type: "organization", target_id: id } : {}, 10);
  const columns: BoColumn<AuditRow>[] = [
    { key: "at", header: "Date", primary: true, cell: (r) => <span className="font-semibold text-ink">{dt(r.at)}</span> },
    { key: "actor", header: "Auteur", cell: (r) => r.actor },
    { key: "action", header: "Action", wrap: true, cell: (r) => <span className="font-mono text-xs">{r.action.replace("backoffice.", "")}</span> },
  ];
  return canAudit ? <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => `événement #${r.id}`} caption="Audit de l’organisation" empty="Aucun événement." /> : history.length ? (
    <ul className="divide-y divide-lineSoft text-sm">{history.map((h, i) => <li key={i} className="py-2"><strong>{h.action.replace("backoffice.", "")}</strong> — {h.by} · {dt(h.at)}{h.reason ? <span className="block text-inkSoft">Motif : {h.reason}</span> : null}</li>)}</ul>
  ) : <p className="text-sm text-inkSoft">Aucune décision d’administration sur cette organisation.</p>;
}

export default function OrganizationFichePage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useBo();
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"suspend" | "reactivate" | null>(null);
  const [notice, setNotice] = useNotice();
  useCrumb(d?.name);
  const load = useCallback(async () => {
    setError("");
    try { setD(await bo.get<Detail>(`/business/organizations/${id}/`)); } catch (e) { setError(boError(e, "Cette organisation n’a pas pu être chargée.")); }
  }, [id]);
  useEffect(() => void load(), [load]);

  if (error && !d) {
    return (
      <>
        <PageHeader title="Organisation" back={{ href: "/backoffice/business", label: "Tratra Business" }} />
        <Alert tone="danger" title="Organisation indisponible" action={<Button size="sm" variant="outline" onClick={() => void load()}>Réessayer</Button>}>{error}</Alert>
      </>
    );
  }
  if (!d) return <SkeletonPage />;
  const manage = can("business.manage");
  const orgId = Number(id);
  const pending = d.requests.by_status.pending_approval ?? 0;

  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <Fiche
        name={d.name}
        eyebrow={`Organisation #${d.id}`}
        subtitle={[d.industry, d.city].filter(Boolean).join(" · ") || undefined}
        badges={<><Badge tone={d.is_active ? "success" : "danger"}>{d.is_active ? "Active" : "Suspendue"}</Badge>{d.requests.late_response ? <Badge tone="danger">{d.requests.late_response} en retard de prise en charge</Badge> : null}</>}
        facts={[["Propriétaire", d.owner], ["Membres · sites", `${d.members} · ${d.sites}`], ["Demandes ouvertes", d.open_requests], ["Créée le", dd(d.created_at)]]}
        actions={manage ? (d.is_active ? <Button variant="danger" size="sm" leftIcon={<Pause aria-hidden className="h-4 w-4" />} onClick={() => setMode("suspend")}>Suspendre</Button> : <Button size="sm" leftIcon={<Play aria-hidden className="h-4 w-4" />} onClick={() => setMode("reactivate")}>Réactiver</Button>) : null}
        alert={!d.is_active ? <Alert tone="danger" className="mb-4" title="Organisation suspendue">Ses membres n’ont plus accès à Tratra Business.</Alert> : undefined}
        tabs={[
          {
            id: "general", label: "Informations générales", content: (
              <Pane>
                <Section title="Identité de l’organisation">
                  <KV items={[["Raison sociale", d.legal_name || "—"], ["N° d’enregistrement", d.registration_number || "—"], ["Secteur", d.industry || "—"], ["Ville", d.city], ["Adresse", d.address || "—"], ["Devise", d.currency], ["Équipements suivis", d.equipment], ["Contrats de maintenance actifs", `${d.contracts.active} / ${d.contracts.total}`]]} />
                </Section>
                <Section title={`Membres (${d.members_list.length})`}>
                  <ul className="divide-y divide-lineSoft text-sm">{d.members_list.map((m) => <li key={m.id} className="flex flex-wrap justify-between gap-2 py-2"><span><span className="font-semibold text-ink">{m.name}</span> <span className="text-ash">{m.phone ?? ""}</span></span><span className="text-inkSoft">{m.role_label}{!m.is_active ? " · inactif" : ""}</span></li>)}</ul>
                </Section>
                <Section title={`Sites (${d.sites_list.length})`} className="lg:col-span-2">
                  <p className="text-sm text-inkSoft">{d.sites_list.map((s) => `${s.name}${s.city ? ` (${s.city})` : ""}${s.is_active ? "" : " — inactif"}`).join(" · ") || "Aucun site."}</p>
                  <p className="mt-2 text-xs text-ash">Nom et ville seulement : aucune coordonnée ni adresse précise.</p>
                </Section>
              </Pane>
            ),
          },
          { id: "activity", label: "Activités et historique", count: pending || undefined, content: <Section title="Demandes d’intervention"><div className="mb-3 flex flex-wrap gap-2 text-xs">{Object.entries(d.requests.by_status).map(([s, n]) => <span key={s} className="rounded-full bg-canvas px-2.5 py-0.5 text-inkSoft">{s} : <strong>{n}</strong></span>)}</div><RequestsPane id={orgId} /></Section> },
          { id: "documents", label: "Documents et justificatifs", content: <Section title="Factures consolidées"><InvoicesPane id={orgId} /></Section> },
          {
            id: "money", label: "Paiements et engagements", content: (
              <div className="space-y-5">
                <Section title="Budgets">
                  {d.budgets.length ? <ul className="space-y-2 text-sm">{d.budgets.map((b) => <li key={b.id} className="flex flex-wrap items-center justify-between gap-2"><span>{b.name} — {moneyLabel(b.spent)} / {moneyLabel(b.amount)} <span className="text-xs text-ash">({b.period_start} → {b.period_end})</span></span><Badge tone={LEVEL_TONE[b.level] ?? "gray"}>{b.percent} %</Badge></li>)}</ul> : <p className="text-sm text-inkSoft">Aucun budget récent.</p>}
                </Section>
                {can("engagements.view") ? <Section title="Engagements"><ContractsPane name={d.name} /></Section> : <Restricted right="engagements.view" />}
              </div>
            ),
          },
          { id: "notes", label: "Notes internes et audit", content: <Section title="Journal d’audit de l’organisation"><AuditPane id={orgId} history={d.history} canAudit={can("security.manage")} /></Section> },
          {
            id: "actions", label: "Actions administratives", content: (
              <Pane columns={1}>
                <Section title="Statut de l’organisation">
                  {manage ? (
                    <div className="space-y-3">
                      {d.is_active ? <Button variant="danger" leftIcon={<Pause aria-hidden className="h-4 w-4" />} onClick={() => setMode("suspend")}>Suspendre l’organisation</Button> : <Button leftIcon={<Play aria-hidden className="h-4 w-4" />} onClick={() => setMode("reactivate")}>Réactiver l’organisation</Button>}
                      <p className="text-xs text-ash">Suspendre retire l’accès à Tratra Business à ses membres ; aucune donnée n’est supprimée ni aucune demande annulée. Le circuit de validation des demandes n’est jamais contourné ici.</p>
                    </div>
                  ) : <Restricted right="business.manage">Suspendre ou réactiver une organisation.</Restricted>}
                </Section>
              </Pane>
            ),
          },
        ]}
      />
      <ReasonModal open={mode === "suspend"} title="Suspendre cette organisation ?" description="Ses membres perdent l’accès à Tratra Business ; aucune donnée n’est supprimée ni aucune demande annulée." confirmLabel="Suspendre" tone="danger" onClose={() => setMode(null)}
        request={postTo(`/business/organizations/${d.id}/suspend/`)} onDone={() => { setMode(null); setNotice("Organisation suspendue."); void load(); }} />
      <ReasonModal open={mode === "reactivate"} title="Réactiver cette organisation ?" confirmLabel="Réactiver" onClose={() => setMode(null)}
        request={postTo(`/business/organizations/${d.id}/reactivate/`)} onDone={() => { setMode(null); setNotice("Organisation réactivée."); void load(); }} />
    </>
  );
}
