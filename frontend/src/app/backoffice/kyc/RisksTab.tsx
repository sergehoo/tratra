"use client";
import { useState } from "react";
import { Eye, ShieldAlert } from "lucide-react";
import { Badge, type BadgeTone } from "@/components/ds";
import { bo } from "@/lib/bo";
import { useCounts, useManagedList } from "@/lib/useBoList";
import { Drawer } from "../_components/Drawer";
import { FilterBar, FilterSelect, ListView, ReasonModal, SearchBox, Section, StatusChips, dt, useNotice, type BoColumn, type RowAction } from "../_components/ui";

interface Case {
  id: number; subject_id: number; subject_name: string; kind: string; kind_label: string; status: string; status_label: string; priority: number; explanation: string;
  evidence: Record<string, unknown>; related_users: number[]; source: string; detected_at: string; allowed: string[];
}
interface Detail extends Case { history: { decision: string; decision_label: string; reason: string; at: string; by: string | null }[] }

const TONE: Record<string, BadgeTone> = { open: "warning", investigating: "info", confirmed: "danger", dismissed: "gray" };
const DECISION: Record<string, { label: string; help: string; tone: "primary" | "danger" }> = {
  investigate: { label: "Ouvrir une enquête", help: "Aucun effet sur le compte.", tone: "primary" },
  confirm: { label: "Confirmer", help: "Consigne que l’équipe confirme l’anomalie. Aucune suspension ni aucun rejet n’en découle automatiquement : ces actions restent distinctes.", tone: "danger" },
  dismiss: { label: "Écarter", help: "L’anomalie n’est pas retenue ; le dossier n’est pas rouvert sans nouvel élément.", tone: "primary" },
  reopen: { label: "Rouvrir", help: "Remet le dossier à examiner.", tone: "primary" },
};
const PRIO = ["", "Faible", "Moyenne", "Haute"];

/** Risques et fraudes : dossiers PROPOSÉS par les règles et l'analyse de documents ; décisions humaines motivées, sans effet automatique. */
export function RisksTab() {
  const m = useManagedList<Case, { status: string; kind: string }>("/risk/cases/", { status: "active", kind: "" });
  const { values: f, list } = m;
  const counts = useCounts("/risk/cases/", { active: "status=active", open: "status=open", investigating: "status=investigating", confirmed: "status=confirmed", dismissed: "status=dismissed" }, list.version);
  const [act, setAct] = useState<{ c: Case; d: string } | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [notice, setNotice] = useNotice();

  async function openDetail(c: Case) { setDetail({ ...c, history: [] }); setDetail(await bo.get<Detail>(`/risk/cases/${c.id}/`)); }
  const columns: BoColumn<Case>[] = [
    { key: "who", header: "Compte", primary: true, cell: (c) => <span className="font-semibold text-ink">{c.subject_name} <span className="font-normal text-ash">#{c.subject_id}</span></span> },
    { key: "kind", header: "Anomalie", wrap: true, cell: (c) => <span><strong className="text-ink">{c.kind_label}</strong><span className="mt-0.5 block text-xs text-inkSoft">{c.explanation}</span></span> },
    { key: "prio", header: "Priorité", cell: (c) => <Badge tone={c.priority >= 3 ? "danger" : c.priority === 2 ? "warning" : "gray"}>{PRIO[c.priority]}</Badge> },
    { key: "st", header: "Statut", cell: (c) => <Badge tone={TONE[c.status] ?? "gray"}>{c.status_label}</Badge> },
    { key: "at", header: "Détecté le", from: "xl", hideOnMobile: true, cell: (c) => dt(c.detected_at) },
  ];
  const rowActions = (c: Case): RowAction[] => [
    { label: "Éléments et historique", icon: Eye, onClick: () => void openDetail(c) },
    { label: "Fiche du compte", icon: Eye, href: `/backoffice/users/${c.subject_id}` },
    ...Object.entries(DECISION).filter(([d]) => c.allowed.includes(d)).map(([d, meta]): RowAction => ({ label: meta.label, icon: ShieldAlert, tone: meta.tone === "danger" ? "danger" : undefined, onClick: () => setAct({ c, d }) })),
  ];

  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <StatusChips items={[["active", "En cours"], ["open", "À examiner"], ["investigating", "Enquête"], ["confirmed", "Confirmés"], ["dismissed", "Écartés"]]} value={f.status} onChange={(v) => m.set({ status: v })} counts={counts} label="Statut du dossier" />
      <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="Nom, téléphone…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
        <FilterSelect label="Type" value={f.kind} onChange={(v) => m.set({ kind: v })} options={[["", "Tous"], ["duplicate_account", "Doublons"], ["document_inconsistent", "Documents incohérents"], ["identity_incomplete", "Identité incomplète"], ["kyc_expired", "KYC expirés"], ["abnormal_activity", "Activité anormale"], ["artificial_bookings", "Réservations artificielles"]]} />
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(c) => c.id} rowLabel={(c) => c.subject_name} caption="Dossiers de risque" empty="Aucun dossier de risque." emptyHint="Les dossiers sont proposés par les règles et l’analyse des documents."
        rowActions={rowActions} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
      <p className="mt-2 text-xs text-ash">L’IA et les règles proposent, l’équipe décide. Un nom, une adresse ou un appareil partagé n’est jamais une preuve de fraude ; aucune suspension ni accusation n’est automatique.</p>

      <ReasonModal open={Boolean(act)} title={act ? `${DECISION[act.d].label} — ${act.c.subject_name}` : ""} description={act ? DECISION[act.d].help : undefined} confirmLabel={act ? DECISION[act.d].label : "Confirmer"} tone={act ? DECISION[act.d].tone : "primary"}
        reasonLabel="Motif (10 caractères minimum, conservé dans l’historique)" onClose={() => setAct(null)} request={act ? (b) => bo.post(`/risk/cases/${act.c.id}/decision/`, { decision: act.d, reason: b.reason }) : async () => undefined}
        onDone={() => { setAct(null); setNotice("Décision enregistrée et journalisée."); void list.reload(); }} />

      <Drawer open={Boolean(detail)} onClose={() => setDetail(null)} title={detail ? `${detail.subject_name} — ${detail.kind_label}` : ""} description={detail?.explanation}>
        {detail ? (
          <div className="space-y-5">
            <Section title="Éléments">
              <dl className="grid gap-2 text-sm sm:grid-cols-2">{Object.entries(detail.evidence).map(([k, v]) => <div key={k}><dt className="text-xs font-semibold text-ash">{k.replace(/_/g, " ")}</dt><dd className="font-semibold text-ink">{String(v)}</dd></div>)}<div><dt className="text-xs font-semibold text-ash">source</dt><dd className="font-semibold text-ink">{detail.source === "document_analysis" ? "Analyse de document" : "Règles"}</dd></div></dl>
              {detail.related_users.length ? <p className="mt-2 text-sm text-inkSoft">Comptes liés : {detail.related_users.map((u) => <a key={u} className="mr-2 font-semibold text-primaryDark underline" href={`/backoffice/users/${u}`}>#{u}</a>)}</p> : null}
            </Section>
            <Section title="Historique des décisions">
              {detail.history.length === 0 ? <p className="text-sm text-ash">Aucune décision pour l’instant.</p> : <ol className="space-y-2">{detail.history.map((h, i) => <li key={i} className="rounded-panel border border-lineSoft p-3 text-sm"><p className="font-semibold text-ink">{h.decision_label} <span className="font-normal text-ash">· {dt(h.at)}{h.by ? ` · ${h.by}` : ""}</span></p><p className="mt-0.5 text-inkSoft">{h.reason}</p></li>)}</ol>}
            </Section>
          </div>
        ) : null}
      </Drawer>
    </>
  );
}
