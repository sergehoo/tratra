"use client";
import { useCallback, useEffect, useState } from "react";
import { CheckCheck, Eye, Trash2 } from "lucide-react";
import { Alert, Badge, Button, Modal, type BadgeTone } from "@/components/ds";
import { bo, boError } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useCounts, useManagedList } from "@/lib/useBoList";
import { DateRange, FilterBar, KV, ListView, ReasonModal, SearchBox, StatusChips, dd, dt, postTo, useNotice, type BoColumn, type RowAction } from "../_components/ui";

interface Row {
  id: number; status: number; kind: "text" | "photo" | "video"; text: string; state: "active" | "expired" | "deleted_by_author" | "removed_by_staff";
  has_media: boolean; author: { id: number; name: string }; reporter: string; reason: string; created_at: string; resolved: boolean;
}
interface Detail {
  id: number; kind: Row["kind"]; state: Row["state"]; audience: string; created_at: string; expires_at: string; text: string;
  author: { id: number; name: string; active: boolean }; media: { url: string | null; mime: string; duration?: number } | null;
  reports: { id: number; reporter: string; reason: string; created_at: string; resolved: boolean }[];
}

const KIND_FR = { text: "Texte", photo: "Photo", video: "Vidéo" } as const;
const STATE_FR: Record<Row["state"], { label: string; tone: BadgeTone }> = {
  active: { label: "Visible", tone: "warning" }, expired: { label: "Expiré", tone: "gray" },
  deleted_by_author: { label: "Supprimé par l’auteur", tone: "gray" }, removed_by_staff: { label: "Retiré par la modération", tone: "danger" },
};

/** Contenu du statut signalé : la consultation d'un contenu privé est journalisée côté serveur (une trace par ouverture). */
function ContentPanel({ id, onClose, onRemove }: { id: number | null; onClose: () => void; onRemove: (id: number) => void }) {
  const { can } = useBo();
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    if (id === null) return;
    setError("");
    try { setD(await bo.get<Detail>(`/statuses/${id}/`)); } catch (e) { setError(boError(e, "Ce statut n’a pas pu être chargé.")); }
  }, [id]);
  useEffect(() => { setD(null); void load(); }, [load]);
  const live = d?.state === "active";
  return (
    <Modal open={id !== null} onClose={onClose} size="lg" title={d ? `Statut #${d.id} signalé` : "Statut signalé"}>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {d ? (
        <div className="space-y-4">
          <KV items={[["Auteur", d.author.name], ["Type", KIND_FR[d.kind]], ["Publié le", dt(d.created_at)], ["Expire le", dt(d.expires_at)], ["Visibilité", d.audience === "extended" ? "Tous les membres" : "Contacts"], ["État", <Badge key="s" tone={STATE_FR[d.state].tone}>{STATE_FR[d.state].label}</Badge>]]} />
          {d.media?.url ? (
            d.kind === "photo"
              // eslint-disable-next-line @next/next/no-img-element
              ? <img src={d.media.url} alt="Photo du statut signalé" className="max-h-80 w-full rounded-panel bg-night object-contain" />
              : <video src={d.media.url} controls preload="metadata" className="max-h-80 w-full rounded-panel bg-night" />
          ) : null}
          {d.text ? <p className="whitespace-pre-line rounded-panel bg-canvas p-3 text-sm text-inkSoft">{d.text}</p>
            : !d.media ? <p className="rounded-panel bg-canvas p-3 text-sm text-ash">Le contenu n’est plus conservé ({d.state === "deleted_by_author" ? "supprimé par son auteur" : d.state === "removed_by_staff" ? "retiré par la modération" : "expiré"}). Seuls les signalements restent.</p> : null}
          <div>
            <h3 className="mb-1 text-sm font-bold text-ink">Signalements ({d.reports.length})</h3>
            <ul className="space-y-1.5 text-sm">{d.reports.map((r) => <li key={r.id}>{r.reporter} · {dt(r.created_at)} — {r.reason} {r.resolved ? <Badge tone="gray">Traité</Badge> : <Badge tone="warning">À traiter</Badge>}</li>)}</ul>
          </div>
          {can("reviews.moderate") && live ? <Button variant="danger" leftIcon={<Trash2 aria-hidden className="h-4 w-4" />} onClick={() => onRemove(d.id)}>Retirer ce statut</Button> : null}
          <p className="text-xs text-ash">Retirer supprime le texte et le média ; l’auteur en est informé et tous les signalements du statut sont clos. Chaque décision est motivée et journalisée.</p>
        </div>
      ) : !error ? <p className="text-sm text-inkSoft" role="status">Chargement…</p> : null}
    </Modal>
  );
}

export function StatusesTab() {
  const { can } = useBo();
  const manage = can("reviews.moderate");
  const m = useManagedList<Row, { resolved: string; from: string; to: string }>("/statuses/reports/", { resolved: "false", from: "", to: "" });
  const { values: f, list } = m;
  const counts = useCounts("/statuses/reports/", { false: "resolved=false", true: "resolved=true" }, `${list.version}`);
  const [viewing, setViewing] = useState<number | null>(null);
  const [removing, setRemoving] = useState<number | null>(null);
  const [dismiss, setDismiss] = useState<Row | null>(null);
  const [notice, setNotice] = useNotice();

  const columns: BoColumn<Row>[] = [
    { key: "status", header: "Statut signalé", primary: true, wrap: true, cell: (r) => <span className="font-semibold text-ink">{KIND_FR[r.kind]} #{r.status}<span className="block font-normal text-inkSoft">{r.text || (r.has_media ? "Média sans légende" : "Contenu non conservé")}</span></span> },
    { key: "author", header: "Auteur", hideOnMobile: true, from: "lg", cell: (r) => r.author.name },
    { key: "reason", header: "Motif", wrap: true, cell: (r) => <span className="text-inkSoft">{r.reason}</span> },
    { key: "reporter", header: "Signalé par", hideOnMobile: true, from: "xl", cell: (r) => r.reporter },
    { key: "state", header: "État", cell: (r) => <span className="flex flex-wrap gap-1.5">{r.resolved ? <Badge tone="gray">Traité</Badge> : <Badge tone="warning">À traiter</Badge>}<Badge tone={STATE_FR[r.state].tone}>{STATE_FR[r.state].label}</Badge></span> },
    { key: "date", header: "Le", hideOnMobile: true, from: "lg", cell: (r) => dd(r.created_at) },
  ];
  const rowActions = (r: Row): RowAction[] => [
    { label: "Voir le contenu", icon: Eye, onClick: () => setViewing(r.status) },
    { label: "Retirer le statut", icon: Trash2, tone: "danger", onClick: () => setRemoving(r.status), hidden: !manage || r.state !== "active" },
    { label: "Classer sans suite", icon: CheckCheck, onClick: () => setDismiss(r), hidden: !manage || r.resolved },
  ];
  const done = (msg: string) => { setNotice(msg); setViewing(null); setRemoving(null); setDismiss(null); void list.reload(); };

  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <StatusChips items={[["false", "À traiter"], ["true", "Traités"]]} value={f.resolved} onChange={(v) => m.set({ resolved: v })} counts={counts} label="État du signalement" />
      <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="Texte du statut, motif ou nom…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
      </FilterBar>
      <ListView
        list={list}
        columns={columns}
        rowKey={(r) => r.id}
        rowLabel={(r) => `signalement du statut #${r.status}`}
        caption="Statuts signalés"
        empty="Aucun statut signalé dans cet état."
        emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : "Les statuts signalés par les membres apparaissent ici."}
        rowActions={rowActions}
        pageSize={m.pageSize}
        onPageSize={(n) => m.set({ size: String(n) })}
      />
      <ContentPanel id={removing === null ? viewing : null} onClose={() => setViewing(null)} onRemove={(id) => { setViewing(null); setRemoving(id); }} />
      <ReasonModal open={removing !== null} title="Retirer ce statut ?" description="Le texte et le média sont supprimés, l’auteur est prévenu et les signalements du statut sont clos."
        confirmLabel="Retirer" tone="danger" onClose={() => setRemoving(null)} request={removing !== null ? postTo(`/statuses/${removing}/remove/`) : async () => undefined}
        onDone={() => done("Statut retiré.")} />
      <ReasonModal open={Boolean(dismiss)} title="Classer ce signalement sans suite ?" description="Le statut reste visible. Notez la décision prise (conservée dans le journal)." confirmLabel="Classer" reasonLabel="Décision prise"
        onClose={() => setDismiss(null)} request={dismiss ? postTo(`/statuses/reports/${dismiss.id}/dismiss/`) : async () => undefined} onDone={() => done("Signalement classé.")} />
    </>
  );
}
