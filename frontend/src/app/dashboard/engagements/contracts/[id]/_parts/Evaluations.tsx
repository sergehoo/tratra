"use client";
import { useState } from "react";
import { Star } from "lucide-react";
import { Alert, Badge, Button, Card, CardHeader, EmptyState, SelectField, TextareaField } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api";
import { dateFr, eng, errFields, type ContractDetail, type Evaluation } from "@/lib/engagements";
import { ActionModal, LoadState, useIntent, useLoad } from "../../../_components/common";

const CRITERIA: [string, string][] = [["quality", "Qualité du travail"], ["punctuality", "Ponctualité"], ["communication", "Communication"], ["respect", "Respect"]];

function Stars({ value }: { value: number }) {
  return (
    <span role="img" aria-label={`${value} sur 5`} className="inline-flex gap-0.5 text-accentDark">
      {[1, 2, 3, 4, 5].map((n) => <Star key={n} aria-hidden className={`h-4 w-4 ${n <= value ? "fill-current" : "text-line"}`} />)}
    </span>
  );
}

function RatingPicker({ value, onChange, label }: { value: number; onChange: (n: number) => void; label: string }) {
  return (
    <fieldset>
      <legend className="text-sm font-semibold text-ink">{label}</legend>
      <div className="mt-1.5 flex gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" aria-pressed={value === n} aria-label={`${n} sur 5`} onClick={() => onChange(n)}
            className={`grid h-11 w-11 place-items-center rounded-xl border text-sm font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${value === n ? "border-primaryDark bg-primaryDark text-white" : "border-line bg-white text-inkSoft hover:border-primary/50"}`}>
            {n}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

function EvaluateModal({ c, open, onClose, onDone, ended }: { c: ContractDetail; open: boolean; onClose: () => void; onDone: () => void; ended: boolean }) {
  const intent = useIntent("eval");
  const [kind, setKind] = useState<"periodic" | "final">(ended ? "final" : "periodic");
  const [rating, setRating] = useState(0);
  const [criteria, setCriteria] = useState<Record<string, string>>({});
  const [comment, setComment] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const body = { kind, rating, criteria: Object.fromEntries(Object.entries(criteria).filter(([, v]) => v).map(([k, v]) => [k, Number(v)])), comment: comment.trim() };
  return (
    <ActionModal open={open} size="lg" title={`Évaluer ${c.counterpart.name}`} description="Votre avis est publié sur le profil de la personne évaluée. Il doit refléter votre expérience réelle de ce contrat." confirmLabel="Publier mon évaluation" disabled={rating < 1}
      onClose={onClose} onError={(e) => setErrors(errFields(e))}
      onSubmit={async () => { await eng.post(`/contracts/${c.id}/evaluations/`, body, intent.key(body)); intent.reset(); setRating(0); setComment(""); onDone(); }}>
      <SelectField label="Type d’évaluation" value={kind} onChange={(e) => setKind(e.target.value as "periodic" | "final")}>
        <option value="periodic" disabled={ended}>Évaluation périodique (pendant le contrat)</option>
        <option value="final" disabled={!ended}>Évaluation finale (après la fin du contrat)</option>
      </SelectField>
      <RatingPicker label="Note globale" value={rating} onChange={setRating} />
      {errors.rating ? <p role="alert" className="text-xs font-medium text-dangerInk">{errors.rating}</p> : null}
      <div className="grid gap-3 sm:grid-cols-2">
        {CRITERIA.map(([k, l]) => (
          <SelectField key={k} label={l} optional value={criteria[k] ?? ""} onChange={(e) => setCriteria({ ...criteria, [k]: e.target.value })}>
            <option value="">Non évalué</option>
            {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n} / 5</option>)}
          </SelectField>
        ))}
      </div>
      <TextareaField label="Commentaire" optional rows={4} maxLength={2000} value={comment} error={errors.comment} onChange={(e) => setComment(e.target.value)}
        hint="Sans lien, adresse e-mail ni numéro de téléphone. Une évaluation périodique est possible tous les 90 jours au plus." />
    </ActionModal>
  );
}

function EvalCard({ e, onDone }: { e: Evaluation; onDone: () => void }) {
  const [reply, setReply] = useState(false);
  const [edit, setEdit] = useState(false);
  const [report, setReport] = useState(false);
  const [text, setText] = useState("");
  const [rating, setRating] = useState(e.rating);
  const [comment, setComment] = useState(e.comment);
  const [notice, setNotice] = useState("");
  return (
    <li className="rounded-panel border border-lineSoft p-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2"><Stars value={e.rating} /><span className="font-semibold text-ink">{e.mine ? "Votre évaluation" : `De ${e.author.name}`}</span></span>
        <span className="flex gap-1.5">{e.kind === "final" ? <Badge tone="primary">Finale</Badge> : <Badge tone="gray">Périodique</Badge>}{e.is_hidden ? <Badge tone="danger">Masquée par Tratra</Badge> : null}</span>
      </div>
      <p className="mt-0.5 text-xs text-ash">{e.mine ? `Pour ${e.subject.name}` : "Pour vous"} · {dateFr(e.created_at.slice(0, 10))}</p>
      {e.comment ? <p className="mt-2 whitespace-pre-line text-inkSoft">{e.comment}</p> : null}
      {Object.keys(e.criteria).length ? <p className="mt-2 flex flex-wrap gap-1.5 text-xs">{CRITERIA.filter(([k]) => e.criteria[k]).map(([k, l]) => <span key={k} className="rounded-full bg-canvas px-2.5 py-0.5">{l} : {e.criteria[k]}/5</span>)}</p> : null}
      {e.reply ? <div className="mt-3 rounded-panel bg-primarySoft/60 p-3"><p className="text-xs font-bold text-primaryDark">Réponse de {e.subject.name}</p><p className="mt-1 text-inkSoft">{e.reply}</p></div> : null}
      {notice ? <p role="status" className="mt-2 text-xs font-medium text-successInk">{notice}</p> : null}
      <div className="mt-3 flex flex-wrap gap-2">
        {e.editable ? <Button size="sm" variant="outline" onClick={() => setEdit(true)}>Modifier</Button> : null}
        {e.can_reply ? <Button size="sm" variant="soft" onClick={() => setReply(true)}>Répondre</Button> : null}
        {!e.mine ? <Button size="sm" variant="ghost" onClick={() => setReport(true)}>Signaler</Button> : null}
      </div>
      <ActionModal open={reply} title="Répondre à cette évaluation" description="Une seule réponse, publique, sans lien ni coordonnées." confirmLabel="Publier ma réponse" disabled={text.trim().length < 2} onClose={() => setReply(false)}
        onSubmit={async () => { await eng.post(`/evaluations/${e.id}/reply/`, { reply: text.trim() }); setReply(false); onDone(); }}>
        <TextareaField label="Votre réponse" required rows={4} maxLength={1000} value={text} onChange={(ev) => setText(ev.target.value)} />
      </ActionModal>
      <ActionModal open={report} tone="danger" title="Signaler cette évaluation" description="L’équipe Tratra l’examine ; elle peut la masquer si elle est fausse ou abusive." confirmLabel="Signaler" disabled={text.trim().length < 5} onClose={() => setReport(false)}
        onSubmit={async () => { await eng.post(`/evaluations/${e.id}/report/`, { reason: text.trim() }); setReport(false); setNotice("Signalement transmis à Tratra."); }}>
        <TextareaField label="Motif" required rows={3} value={text} onChange={(ev) => setText(ev.target.value)} />
      </ActionModal>
      <ActionModal open={edit} title="Modifier mon évaluation" description="Possible pendant quelques jours seulement après la publication." confirmLabel="Enregistrer" onClose={() => setEdit(false)}
        onSubmit={async () => { await eng.patch(`/evaluations/${e.id}/`, { rating, comment: comment.trim() }); setEdit(false); onDone(); }}>
        <RatingPicker label="Note globale" value={rating} onChange={setRating} />
        <TextareaField label="Commentaire" optional rows={4} value={comment} onChange={(ev) => setComment(ev.target.value)} />
      </ActionModal>
    </li>
  );
}

export function Evaluations({ c }: { c: ContractDetail }) {
  const { data, error, loading, reload } = useLoad(() => eng.get<{ results: Evaluation[] }>(`/contracts/${c.id}/evaluations/`), [c.id]);
  const [open, setOpen] = useState(false);
  const ended = c.status === "terminated" || c.status === "completed";
  return (
    <>
      <Alert tone="brand" className="mb-5" title="Des évaluations fiables">
        Seules les deux parties d’un contrat réellement commencé peuvent s’évaluer : une évaluation périodique après {c.rules.min_days_for_evaluation} jours puis tous les {c.rules.evaluation_interval_days} jours au plus, une évaluation finale dans les 60 jours après la fin. Pas de lien ni de coordonnées dans un commentaire.
      </Alert>
      <Card padding="md">
        <CardHeader title="Évaluations" icon={<Star className="h-5 w-5" />} action={c.actions.includes("evaluate") ? <Button size="sm" onClick={() => setOpen(true)}>Évaluer {c.counterpart.name}</Button> : undefined} />
        <LoadState loading={loading} error={error} hasData={Boolean(data)} reload={() => void reload()}>
          {data && data.results.length === 0 ? <EmptyState compact title="Aucune évaluation pour le moment" description="Elles apparaissent ici pour les deux parties." /> : <ul className="space-y-3">{data?.results.map((e) => <EvalCard key={`${e.id}-${e.rating}-${e.reply}`} e={e} onDone={() => void reload()} />)}</ul>}
        </LoadState>
      </Card>
      <EvaluateModal key={`${ended}`} c={c} ended={ended} open={open} onClose={() => setOpen(false)} onDone={() => { setOpen(false); void reload(); }} />
    </>
  );
}
