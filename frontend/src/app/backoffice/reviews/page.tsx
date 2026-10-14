"use client";
import { useCallback, useEffect, useState } from "react";
import { CalendarCheck, CheckCheck, Eye, EyeOff, Undo2 } from "lucide-react";
import { StatusesTab } from "./StatusesTab";
import { WatchTab } from "./WatchTab";
import { Alert, Badge, Button, Modal, PageHeader, Tabs } from "@/components/ds";
import { bo, boError } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useCounts, useManagedList } from "@/lib/useBoList";
import { DateRange, ExportButton, FilterBar, FilterSelect, KV, ListView, ReasonModal, SearchBox, StatusChips, Tag, dd, dt, postTo, useNotice, useTabParam, type BoColumn, type BulkAction, type RowAction } from "../_components/ui";

interface Review { id: number; booking_id: number; rating: number; comment: string; author: string; artisan: string; is_hidden: boolean; reports: number; has_reply: boolean; created_at: string }
interface ReviewDetail extends Review { reply: string; reply_at: string | null; criteria: Record<string, number>; photos: number; history: { action: string; at: string; by: string; reason: string }[]; }
interface ReportRow { id: number; type: string; reason: string; reporter: string; created_at: string; is_resolved: boolean; review_id: number | null; excerpt: string }
const CRITERIA_FR: Record<string, string> = { quality: "Qualité", punctuality: "Ponctualité", professionalism: "Professionnalisme", communication: "Communication", price: "Prix" };

function ReviewPanel({ id, onClose, onChanged }: { id: number | null; onClose: () => void; onChanged: () => void }) {
  const { can } = useBo();
  const [d, setD] = useState<(ReviewDetail & { reports: { id: number; reason: string; reporter: string; is_resolved: boolean; created_at: string }[] }) | null>(null);
  const [error, setError] = useState("");
  const [hide, setHide] = useState(false);
  const [restore, setRestore] = useState(false);
  const load = useCallback(async () => {
    if (id === null) return;
    setError("");
    try { setD(await bo.get(`/reviews/${id}/`)); } catch (e) { setError(boError(e, "Cet avis n’a pas pu être chargé.")); }
  }, [id]);
  useEffect(() => { setD(null); void load(); }, [load]);
  return (
    <>
      <Modal open={id !== null && !hide && !restore} onClose={onClose} size="lg" title={d ? `Avis #${d.id} — réservation #${d.booking_id}` : "Avis"}>
        {error ? <Alert tone="danger">{error}</Alert> : null}
        {d ? (
          <div className="space-y-4">
            <KV items={[["Note", `${d.rating} / 5`], ["Auteur", d.author], ["Artisan", d.artisan], ["Publié le", dt(d.created_at)], ["Visibilité", d.is_hidden ? <Badge key="h" tone="danger">Masqué</Badge> : <Badge key="v" tone="success">Publié</Badge>], ["Photos", d.photos]]} />
            <p className="whitespace-pre-line rounded-panel bg-canvas p-3 text-sm text-inkSoft">{d.comment || "Sans commentaire."}</p>
            {Object.keys(d.criteria).length ? <p className="flex flex-wrap gap-1.5 text-xs">{Object.entries(d.criteria).map(([k, v]) => <span key={k} className="rounded-full bg-canvas px-2.5 py-0.5">{CRITERIA_FR[k] ?? k} : {v}/5</span>)}</p> : null}
            {d.reply ? <div><h3 className="text-sm font-bold text-ink">Réponse de l’artisan ({dt(d.reply_at)})</h3><p className="mt-1 rounded-panel bg-primarySoft/60 p-3 text-sm text-inkSoft">{d.reply}</p></div> : null}
            {d.reports.length ? (
              <div>
                <h3 className="mb-1 text-sm font-bold text-ink">Signalements</h3>
                <ul className="space-y-1.5 text-sm">{d.reports.map((r) => <li key={r.id}>{r.reporter} · {dt(r.created_at)} — {r.reason} {r.is_resolved ? <Badge tone="gray">Traité</Badge> : <Badge tone="warning">Ouvert</Badge>}</li>)}</ul>
              </div>
            ) : null}
            {can("reviews.moderate") ? (
              <div className="flex gap-2">{d.is_hidden ? <Button variant="outline" onClick={() => setRestore(true)}>Republier l’avis</Button> : <Button variant="danger" onClick={() => setHide(true)}>Masquer l’avis</Button>}</div>
            ) : null}
            <p className="text-xs text-ash">Masquer retire l’avis de la page de l’artisan et du calcul de sa note ; le texte n’est jamais modifié ni supprimé.</p>
          </div>
        ) : !error ? <p className="text-sm text-inkSoft" role="status">Chargement…</p> : null}
      </Modal>
      <ReasonModal open={hide} title="Masquer cet avis ?" description="Les signalements ouverts sur cet avis sont clos. La note de l’artisan est recalculée." confirmLabel="Masquer" tone="danger" onClose={() => setHide(false)}
        request={postTo(`/reviews/${id}/hide/`)} onDone={() => { setHide(false); void load(); onChanged(); }} />
      <ReasonModal open={restore} title="Republier cet avis ?" confirmLabel="Republier" onClose={() => setRestore(false)} request={postTo(`/reviews/${id}/restore/`)}
        onDone={() => { setRestore(false); void load(); onChanged(); }} />
    </>
  );
}

function ReviewsTab({ onOpen, onChanged, version }: { onOpen: (id: number) => void; onChanged: () => void; version: number }) {
  const { can } = useBo();
  const manage = can("reviews.moderate");
  const m = useManagedList<Review, { hidden: string; reported: string; rating: string; from: string; to: string }>("/reviews/", { hidden: "", reported: "", rating: "", from: "", to: "" });
  const { values: f, list } = m;
  const counts = useCounts("/reviews/", { _all: "", false: "hidden=false", true: "hidden=true" }, `${list.version}-${version}`);
  const [target, setTarget] = useState<{ row: Review; op: "hide" | "restore" } | null>(null);
  const [notice, setNotice] = useNotice();

  const columns: BoColumn<Review>[] = [
    { key: "rating", header: "Note", primary: true, sort: "rating", cell: (r) => <span className="font-semibold text-ink">{r.rating} / 5 <span className="font-normal text-ash">· avis #{r.id}</span></span> },
    { key: "comment", header: "Commentaire", wrap: true, cell: (r) => <span className="text-inkSoft">{r.comment || "—"}</span> },
    { key: "who", header: "Auteur → artisan", hideOnMobile: true, from: "xl", cell: (r) => `${r.author} → ${r.artisan}` },
    { key: "state", header: "État", cell: (r) => <span className="flex flex-wrap gap-1.5">{r.is_hidden ? <Badge tone="danger">Masqué</Badge> : <Badge tone="success">Publié</Badge>}{r.reports ? <Badge tone="warning">{r.reports} signalement(s)</Badge> : null}</span> },
    { key: "date", header: "Publié le", sort: "created_at", hideOnMobile: true, from: "lg", cell: (r) => dd(r.created_at) },
  ];
  const rowActions = (r: Review): RowAction[] => [
    { label: "Examiner l’avis", icon: Eye, onClick: () => onOpen(r.id) },
    { label: "Masquer l’avis", icon: EyeOff, tone: "danger", onClick: () => setTarget({ row: r, op: "hide" }), hidden: !manage || r.is_hidden },
    { label: "Republier l’avis", icon: Undo2, onClick: () => setTarget({ row: r, op: "restore" }), hidden: !manage || !r.is_hidden },
    { label: "Ouvrir la réservation", icon: CalendarCheck, href: `/backoffice/bookings/${r.booking_id}`, hidden: !can("bookings.view") },
  ];
  const bulk: BulkAction<Review>[] | undefined = manage
    ? [
        { id: "hide", label: "Masquer", icon: EyeOff, tone: "danger", title: "Masquer les avis sélectionnés ?", confirmLabel: "Masquer", description: "Les signalements ouverts sont clos et la note de chaque artisan est recalculée.", eligible: (r) => !r.is_hidden, run: (r, b) => bo.post(`/reviews/${r.id}/hide/`, b) },
        { id: "restore", label: "Republier", icon: Undo2, title: "Republier les avis sélectionnés ?", confirmLabel: "Republier", eligible: (r) => r.is_hidden, run: (r, b) => bo.post(`/reviews/${r.id}/restore/`, b) },
      ]
    : undefined;

  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <StatusChips items={[["", "Tous"], ["false", "Publiés"], ["true", "Masqués"]]} value={f.hidden} onChange={(v) => m.set({ hidden: v })} counts={counts} label="Visibilité" />
      <FilterBar
        search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="Texte de l’avis ou nom de l’artisan…" />}
        activeCount={m.activeCount}
        onReset={m.reset}
        onRefresh={() => void list.reload()}
        refreshing={list.loading}
        actions={<ExportButton dataset="reviews" from={f.from} to={f.to} />}
      >
        <FilterSelect label="Signalements" value={f.reported} onChange={(v) => m.set({ reported: v })} options={[["", "Tous"], ["true", "Signalés"]]} />
        <FilterSelect label="Note" value={f.rating} onChange={(v) => m.set({ rating: v })} options={[["", "Toutes"], ["1", "1"], ["2", "2"], ["3", "3"], ["4", "4"], ["5", "5"]]} />
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
      </FilterBar>
      <ListView
        list={list}
        columns={columns}
        rowKey={(r) => r.id}
        rowLabel={(r) => `avis #${r.id}`}
        caption="Avis"
        empty="Aucun avis ne correspond."
        emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : "Par défaut, les avis les plus signalés passent en premier."}
        ordering={f.ordering}
        onOrdering={(v) => m.set({ ordering: v })}
        rowActions={rowActions}
        bulk={bulk}
        pageSize={m.pageSize}
        onPageSize={(n) => m.set({ size: String(n) })}
      />
      <ReasonModal open={target?.op === "hide"} title="Masquer cet avis ?" description="Les signalements ouverts sur cet avis sont clos. La note de l’artisan est recalculée." confirmLabel="Masquer" tone="danger" onClose={() => setTarget(null)}
        request={target ? postTo(`/reviews/${target.row.id}/hide/`) : async () => undefined} onDone={() => { setTarget(null); setNotice("Avis masqué."); void list.reload(); onChanged(); }} />
      <ReasonModal open={target?.op === "restore"} title="Republier cet avis ?" confirmLabel="Republier" onClose={() => setTarget(null)}
        request={target ? postTo(`/reviews/${target.row.id}/restore/`) : async () => undefined} onDone={() => { setTarget(null); setNotice("Avis republié."); void list.reload(); onChanged(); }} />
    </>
  );
}

function ReportsTab({ onOpen, version }: { onOpen: (id: number) => void; version: number }) {
  const { can } = useBo();
  const manage = can("reviews.moderate");
  const m = useManagedList<ReportRow, { resolved: string; from: string; to: string }>("/reviews/reports/", { resolved: "false", from: "", to: "" });
  const { values: f, list } = m;
  const counts = useCounts("/reviews/reports/", { false: "resolved=false", true: "resolved=true" }, `${list.version}-${version}`);
  const [resolve, setResolve] = useState<ReportRow | null>(null);
  const [notice, setNotice] = useNotice();

  const columns: BoColumn<ReportRow>[] = [
    { key: "type", header: "Signalement", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.type === "review" ? "Avis" : "Message"} · #{r.id}</span> },
    { key: "reason", header: "Motif", wrap: true, cell: (r) => <span className="text-inkSoft">{r.reason}</span> },
    { key: "excerpt", header: "Contenu signalé", wrap: true, hideOnMobile: true, from: "xl", cell: (r) => <span className="text-inkSoft">{r.excerpt || "—"}</span> },
    { key: "who", header: "Signalé par", hideOnMobile: true, from: "xl", cell: (r) => r.reporter },
    { key: "state", header: "État", cell: (r) => (r.is_resolved ? <Tag value="true" label="Traité" /> : <Badge tone="warning">À traiter</Badge>) },
    { key: "date", header: "Le", hideOnMobile: true, from: "lg", cell: (r) => dd(r.created_at) },
  ];
  const rowActions = (r: ReportRow): RowAction[] => [
    { label: "Voir l’avis signalé", icon: Eye, onClick: () => onOpen(r.review_id as number), hidden: !r.review_id },
    { label: "Clore le signalement", icon: CheckCheck, onClick: () => setResolve(r), hidden: !manage || r.is_resolved },
  ];
  const bulk: BulkAction<ReportRow>[] | undefined = manage
    ? [{ id: "resolve", label: "Clore", icon: CheckCheck, title: "Clore les signalements sélectionnés ?", confirmLabel: "Clore", description: "Notez la décision prise : elle est conservée dans le journal de chaque signalement.", eligible: (r) => !r.is_resolved, run: (r, b) => bo.post(`/reviews/reports/${r.id}/resolve/`, b) }]
    : undefined;

  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <StatusChips items={[["false", "À traiter"], ["true", "Traités"]]} value={f.resolved} onChange={(v) => m.set({ resolved: v })} counts={counts} label="État du signalement" />
      <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="Motif, contenu ou auteur du signalement…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
      </FilterBar>
      <ListView
        list={list}
        columns={columns}
        rowKey={(r) => r.id}
        rowLabel={(r) => `signalement #${r.id}`}
        caption="Signalements"
        empty="Aucun signalement dans cet état."
        emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        rowActions={rowActions}
        bulk={bulk}
        pageSize={m.pageSize}
        onPageSize={(n) => m.set({ size: String(n) })}
      />
      <ReasonModal open={Boolean(resolve)} title="Clore ce signalement ?" description="Notez la décision prise (conservée dans le journal)." confirmLabel="Clore" reasonLabel="Décision prise" onClose={() => setResolve(null)}
        request={resolve ? postTo(`/reviews/reports/${resolve.id}/resolve/`) : async () => undefined} onDone={() => { setResolve(null); setNotice("Signalement clos."); void list.reload(); }} />
    </>
  );
}

export default function ReviewsPage() {
  const [tab, setTab] = useTabParam(["reviews", "reports", "statuses", "watch"] as const, "reviews");
  const [open, setOpen] = useState<number | null>(null);
  const [version, setVersion] = useState(0);
  const bump = () => setVersion((v) => v + 1);

  return (
    <>
      <PageHeader title="Avis et signalements" description="Modération : on masque, on ne réécrit jamais. Chaque décision est motivée et journalisée." />
      <Tabs ariaLabel="Sections" value={tab} onChange={setTab} className="mb-4" items={[{ id: "reviews", label: "Avis" }, { id: "reports", label: "Signalements" }, { id: "statuses", label: "Statuts signalés" }, { id: "watch", label: "Surveillance" }]} />
      {tab === "reviews" ? <ReviewsTab key={version} onOpen={setOpen} onChanged={bump} version={version} /> : tab === "reports" ? <ReportsTab key={version} onOpen={setOpen} version={version} /> : tab === "statuses" ? <StatusesTab /> : <WatchTab />}
      <ReviewPanel id={open} onClose={() => setOpen(null)} onChanged={bump} />
    </>
  );
}
