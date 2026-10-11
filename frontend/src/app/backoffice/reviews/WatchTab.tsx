"use client";
import { useState } from "react";
import { Eye, Gavel, ShieldAlert } from "lucide-react";
import { Badge, type BadgeTone } from "@/components/ds";
import { bo } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useCounts, useManagedList } from "@/lib/useBoList";
import { Drawer } from "../_components/Drawer";
import { FilterBar, FilterSelect, ListView, ReasonModal, SearchBox, Section, StatusChips, dt, useNotice, postTo, type BoColumn, type RowAction } from "../_components/ui";

interface Watch {
  id: number; subject_id: number; subject_name: string; subject_active: boolean; kind: string; kind_label: string; status: string; status_label: string;
  priority: number; explanation: string; detected_at: string; evidence: Record<string, unknown>; allowed: string[]; decisions: number | null;
}
interface Contest { id: number; status: string; status_label: string; reason: string; created_at: string; author_name: string; evaluation: { id: number; rating: number; comment: string; from: string; hidden: boolean } | null }
interface Detail extends Watch { history: { decision: string; decision_label: string; reason: string; at: string; by: string | null }[] }

const STATUS_TONE: Record<string, BadgeTone> = { open: "warning", investigating: "info", warned: "warning", suspended: "danger", banned: "danger", cleared: "gray" };
const DECISION: Record<string, { label: string; tone: "primary" | "danger"; help: string }> = {
  investigate: { label: "Ouvrir une enquête", tone: "primary", help: "Aucun effet sur le compte : le dossier passe « en enquête »." },
  warn: { label: "Avertir", tone: "primary", help: "Un avertissement est envoyé à la personne. Le compte reste actif." },
  suspend: { label: "Suspendre le compte", tone: "danger", help: "Connexion impossible, sessions révoquées. Réversible (rétablissement). Les réservations en cours ne sont pas annulées." },
  ban: { label: "Bannir", tone: "danger", help: "Réservé au Super Admin, et seulement après un avertissement ou une suspension motivés. La personne garde un droit de recours." },
  appeal: { label: "Enregistrer un recours", tone: "primary", help: "Consigne le recours reçu (support, courrier). Il sera examiné ; le dossier reste en l’état jusqu’à décision." },
  reinstate: { label: "Rétablir", tone: "primary", help: "Réactive le compte et classe le dossier." },
  clear: { label: "Classer sans suite", tone: "primary", help: "Aucune mesure : le dossier est clos." },
};
const PRIO = ["", "Faible", "Moyenne", "Haute"];

function CasesSection({ onNotice }: { onNotice: (m: string) => void }) {
  const { can } = useBo();
  const m = useManagedList<Watch, { status: string; kind: string }>("/reputation/watch/", { status: "active", kind: "" });
  const { values: f, list } = m;
  const counts = useCounts("/reputation/watch/", { active: "status=active", open: "status=open", investigating: "status=investigating", warned: "status=warned", suspended: "status=suspended", banned: "status=banned", cleared: "status=cleared" }, list.version);
  const [act, setAct] = useState<{ w: Watch; decision: string } | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  async function openDetail(w: Watch) {
    setDetail({ ...w, history: [] }); setLoadingDetail(true);
    try { setDetail(await bo.get<Detail>(`/reputation/watch/${w.id}/`)); } finally { setLoadingDetail(false); }
  }
  const allowed = (w: Watch, d: string) => w.allowed.includes(d) && (!["suspend", "ban", "reinstate"].includes(d) || can("users.manage"));

  const columns: BoColumn<Watch>[] = [
    { key: "who", header: "Personne", primary: true, cell: (w) => <span className="font-semibold text-ink">{w.subject_name} <span className="font-normal text-ash">#{w.subject_id}</span>{!w.subject_active ? <Badge tone="danger" className="ml-1.5">Suspendu</Badge> : null}</span> },
    { key: "kind", header: "Motif de surveillance", wrap: true, cell: (w) => <span><strong className="text-ink">{w.kind_label}</strong><span className="mt-0.5 block text-xs text-inkSoft">{w.explanation}</span></span> },
    { key: "prio", header: "Priorité", cell: (w) => <Badge tone={w.priority >= 3 ? "danger" : w.priority === 2 ? "warning" : "gray"}>{PRIO[w.priority]}</Badge> },
    { key: "status", header: "État", cell: (w) => <Badge tone={STATUS_TONE[w.status] ?? "gray"}>{w.status_label}</Badge> },
    { key: "at", header: "Détecté le", from: "xl", hideOnMobile: true, cell: (w) => dt(w.detected_at) },
  ];
  const rowActions = (w: Watch): RowAction[] => [
    { label: "Dossier et historique", icon: Eye, onClick: () => void openDetail(w) },
    ...Object.entries(DECISION).filter(([d]) => allowed(w, d)).map(([d, meta]): RowAction => ({ label: meta.label, icon: d === "ban" || d === "suspend" ? Gavel : ShieldAlert, tone: meta.tone === "danger" ? "danger" : undefined, onClick: () => setAct({ w, decision: d }) })),
  ];
  const chip = (id: string, label: string): [string, string] => [id, label];

  return (
    <>
      <StatusChips items={[chip("active", "En cours"), chip("open", "À examiner"), chip("investigating", "Enquête"), chip("warned", "Avertis"), chip("suspended", "Suspendus"), chip("banned", "Bannis"), chip("cleared", "Classés")]} value={f.status} onChange={(v) => m.set({ status: v })} counts={counts} label="État du dossier" />
      <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="Nom, téléphone…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
        <FilterSelect label="Motif" value={f.kind} onChange={(v) => m.set({ kind: v })} options={[["", "Tous"], ["low_received", "Notes basses reçues"], ["low_given", "Notes basses données"], ["burst", "Rafale"], ["reciprocal", "Notes réciproques"]]} />
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(w) => w.id} rowLabel={(w) => w.subject_name} caption="Surveillance des évaluations" empty="Aucun dossier de surveillance."
        emptyHint="La détection ne propose un dossier qu’avec un échantillon réel de notes." rowActions={rowActions} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
      <p className="mt-2 text-xs text-ash">La détection propose, l’équipe décide : aucune suspension, aucun bannissement et aucune accusation ne sont automatiques. Un bannissement exige d’abord un avertissement ou une suspension motivés (Super Admin).</p>

      <ReasonModal open={Boolean(act)} title={act ? `${DECISION[act.decision].label} — ${act.w.subject_name}` : ""} description={act ? DECISION[act.decision].help : undefined} confirmLabel={act ? DECISION[act.decision].label : "Confirmer"} tone={act ? DECISION[act.decision].tone : "primary"}
        reasonLabel="Motif (10 caractères minimum, conservé dans l’historique)" onClose={() => setAct(null)} request={act ? (body) => bo.post(`/reputation/watch/${act.w.id}/decision/`, { decision: act.decision, reason: body.reason }) : async () => undefined}
        onDone={() => { setAct(null); onNotice("Décision enregistrée et journalisée."); void list.reload(); }} />

      <Drawer open={Boolean(detail)} onClose={() => setDetail(null)} title={detail ? `${detail.subject_name} — ${detail.kind_label}` : ""} description={detail?.explanation}>
        {detail ? (
          <div className="space-y-5">
            <Section title="Éléments chiffrés">
              <dl className="grid gap-2 text-sm sm:grid-cols-2">{Object.entries(detail.evidence).map(([k, v]) => <div key={k}><dt className="text-xs font-semibold text-ash">{k.replace(/_/g, " ")}</dt><dd className="font-semibold text-ink">{String(v)}</dd></div>)}</dl>
            </Section>
            <Section title="Historique des décisions">
              {loadingDetail ? <p className="text-sm text-ash">Chargement…</p> : detail.history.length === 0 ? <p className="text-sm text-ash">Aucune décision pour l’instant.</p> : (
                <ol className="space-y-2">{detail.history.map((h, i) => <li key={i} className="rounded-panel border border-lineSoft p-3 text-sm"><p className="font-semibold text-ink">{h.decision_label} <span className="font-normal text-ash">· {dt(h.at)}{h.by ? ` · ${h.by}` : ""}</span></p><p className="mt-0.5 text-inkSoft">{h.reason}</p></li>)}</ol>
              )}
            </Section>
          </div>
        ) : null}
      </Drawer>
    </>
  );
}

function ContestsSection({ onNotice }: { onNotice: (m: string) => void }) {
  const m = useManagedList<Contest, { status: string }>("/reputation/contests/", { status: "open" });
  const { values: f, list } = m;
  const [target, setTarget] = useState<{ c: Contest; outcome: "upheld" | "rejected" } | null>(null);
  const columns: BoColumn<Contest>[] = [
    { key: "who", header: "Contestataire", primary: true, cell: (c) => <span className="font-semibold text-ink">{c.author_name}</span> },
    { key: "ev", header: "Évaluation contestée", wrap: true, cell: (c) => c.evaluation ? <span>{c.evaluation.rating}/5 par {c.evaluation.from}{c.evaluation.comment ? ` — « ${c.evaluation.comment} »` : ""}{c.evaluation.hidden ? " (masquée)" : ""}</span> : "—" },
    { key: "why", header: "Motif de la contestation", wrap: true, cell: (c) => c.reason },
    { key: "st", header: "État", cell: (c) => <Badge tone={c.status === "open" ? "warning" : c.status === "upheld" ? "success" : "gray"}>{c.status_label}</Badge> },
    { key: "at", header: "Reçue le", from: "xl", hideOnMobile: true, cell: (c) => dt(c.created_at) },
  ];
  const rowActions = (c: Contest): RowAction[] => c.status !== "open" ? [] : [
    { label: "Retenir (masquer l’évaluation)", icon: Gavel, onClick: () => setTarget({ c, outcome: "upheld" }) },
    { label: "Rejeter la contestation", icon: Eye, onClick: () => setTarget({ c, outcome: "rejected" }) },
  ];
  return (
    <Section title="Contestations d’évaluations" className="mt-8">
      <StatusChips items={[["open", "À traiter"], ["upheld", "Retenues"], ["rejected", "Rejetées"]]} value={f.status} onChange={(v) => m.set({ status: v })} label="État" />
      <ListView list={list} columns={columns} rowKey={(c) => c.id} rowLabel={(c) => `Contestation ${c.id}`} caption="Contestations" empty="Aucune contestation." rowActions={rowActions} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
      <ReasonModal open={Boolean(target)} title={target?.outcome === "upheld" ? "Retenir la contestation ?" : "Rejeter la contestation ?"} description={target?.outcome === "upheld" ? "L’évaluation est masquée (jamais supprimée) et ne compte plus dans le score." : "L’évaluation reste publiée."}
        confirmLabel={target?.outcome === "upheld" ? "Masquer l’évaluation" : "Rejeter"} tone={target?.outcome === "upheld" ? "danger" : "primary"} onClose={() => setTarget(null)}
        request={target ? (body) => bo.post(`/reputation/contests/${target.c.id}/resolve/`, { outcome: target.outcome, reason: body.reason }) : async () => undefined}
        onDone={() => { setTarget(null); onNotice("Contestation traitée et journalisée."); void list.reload(); }} />
    </Section>
  );
}

/** Surveillance : dossiers proposés par la détection (décision humaine, recours, historique) et contestations des évaluations reçues. */
export function WatchTab() {
  const [notice, setNotice] = useNotice();
  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <CasesSection onNotice={setNotice} />
      <ContestsSection onNotice={setNotice} />
    </>
  );
}
