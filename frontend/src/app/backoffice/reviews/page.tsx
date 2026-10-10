"use client";
import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Modal, PageHeader, Tabs, type Column } from "@/components/ds";
import { bo, boError } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useBoList, useDebounced } from "@/lib/useBoList";
import { FilterBar, FilterSelect, KV, ListView, ReasonModal, SearchBox, Tag, dt, postTo, useNotice, useTabParam } from "../_components/ui";

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

export default function ReviewsPage() {
  const { can } = useBo();
  const [tab, setTab] = useTabParam(["reviews", "reports"] as const, "reviews");
  const [notice, setNotice] = useNotice();
  const [q, setQ] = useState("");
  const [hidden, setHidden] = useState("");
  const [reported, setReported] = useState("");
  const [rating, setRating] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [resolve, setResolve] = useState<ReportRow | null>(null);
  const [resolved, setResolved] = useState("false");
  const reviews = useBoList<Review>("/reviews/", { q: useDebounced(q), hidden, reported, rating });
  const reports = useBoList<ReportRow>("/reviews/reports/", { resolved });

  const rColumns: Column<Review>[] = [
    { key: "rating", header: "Note", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.rating} / 5 <span className="font-normal text-ash">· avis #{r.id}</span></span> },
    { key: "comment", header: "Commentaire", cell: (r) => <span className="text-inkSoft">{r.comment || "—"}</span> },
    { key: "who", header: "Auteur → artisan", hideOnMobile: true, cell: (r) => `${r.author} → ${r.artisan}` },
    { key: "state", header: "État", cell: (r) => <span className="flex flex-wrap gap-1.5">{r.is_hidden ? <Badge tone="danger">Masqué</Badge> : <Badge tone="success">Publié</Badge>}{r.reports ? <Badge tone="warning">{r.reports} signalement(s)</Badge> : null}</span> },
    { key: "date", header: "Publié le", hideOnMobile: true, cell: (r) => dt(r.created_at) },
    { key: "act", header: "", align: "right", cell: (r) => <Button size="sm" variant="outline" onClick={() => setOpen(r.id)}>Examiner</Button> },
  ];
  const pColumns: Column<ReportRow>[] = [
    { key: "type", header: "Signalement", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.type === "review" ? "Avis" : "Message"} · #{r.id}</span> },
    { key: "reason", header: "Motif", cell: (r) => <span className="text-inkSoft">{r.reason}</span> },
    { key: "excerpt", header: "Contenu signalé", hideOnMobile: true, cell: (r) => <span className="text-inkSoft">{r.excerpt || "—"}</span> },
    { key: "who", header: "Signalé par", hideOnMobile: true, cell: (r) => r.reporter },
    { key: "date", header: "Le", hideOnMobile: true, cell: (r) => dt(r.created_at) },
    { key: "act", header: "", align: "right", cell: (r) => <span className="flex justify-end gap-2">{r.review_id ? <Button size="sm" variant="outline" onClick={() => setOpen(r.review_id)}>Voir l’avis</Button> : null}{!r.is_resolved && can("reviews.moderate") ? <Button size="sm" onClick={() => setResolve(r)}>Clore</Button> : <Tag value="true" label="Traité" />}</span> },
  ];

  return (
    <>
      <PageHeader title="Avis et signalements" description="Modération : on masque, on ne réécrit jamais. Chaque décision est motivée et journalisée." />
      {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}
      <Tabs ariaLabel="Sections" value={tab} onChange={setTab} className="mb-4" items={[{ id: "reviews", label: "Avis" }, { id: "reports", label: "Signalements" }]} />
      {tab === "reviews" ? (
        <>
          <FilterBar>
            <SearchBox value={q} onChange={setQ} placeholder="Texte de l’avis ou nom de l’artisan…" />
            <FilterSelect label="Visibilité" value={hidden} onChange={setHidden} options={[["", "Tous"], ["false", "Publiés"], ["true", "Masqués"]]} />
            <FilterSelect label="Signalements" value={reported} onChange={setReported} options={[["", "Tous"], ["true", "Signalés"]]} />
            <FilterSelect label="Note" value={rating} onChange={setRating} options={[["", "Toutes"], ["1", "1"], ["2", "2"], ["3", "3"], ["4", "4"], ["5", "5"]]} />
          </FilterBar>
          <ListView list={reviews} columns={rColumns} rowKey={(r) => r.id} caption="Avis" empty="Aucun avis ne correspond." />
        </>
      ) : (
        <>
          <FilterBar><FilterSelect label="État" value={resolved} onChange={setResolved} options={[["false", "À traiter"], ["true", "Traités"]]} /></FilterBar>
          <ListView list={reports} columns={pColumns} rowKey={(r) => r.id} caption="Signalements" empty="Aucun signalement dans cet état." />
        </>
      )}
      <ReviewPanel id={open} onClose={() => setOpen(null)} onChanged={() => { reviews.reload(); reports.reload(); }} />
      <ReasonModal open={Boolean(resolve)} title="Clore ce signalement ?" description="Notez la décision prise (conservée dans le journal)." confirmLabel="Clore" reasonLabel="Décision prise" onClose={() => setResolve(null)}
        request={postTo(`/reviews/reports/${resolve?.id}/resolve/`)} onDone={() => { setResolve(null); setNotice("Signalement clos."); reports.reload(); }} />
    </>
  );
}
