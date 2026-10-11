"use client";
import { useState } from "react";
import { Scale, Star } from "lucide-react";
import { useData } from "@/lib/useData";
import { contestEvaluation, evaluationError, submitEvaluation, type Evaluations, type PendingEvaluation, type Score } from "@/lib/evaluations";
import { Alert, Badge, Button, Card, CardHeader, Modal, SkeletonList, TextareaField } from "@/components/ds";
import { StarPicker } from "./StarPicker";

const ROLE_FR = { client: "le prestataire", provider: "le demandeur" } as const;
const day = (iso: string) => new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "long" });

function ScoreBox({ label, s, hint }: { label: string; s: Score; hint: string }) {
  return (
    <div className="rounded-panel border border-lineSoft p-3">
      <p className="text-xs font-semibold text-ash">{label}</p>
      <p className="mt-1 flex items-center gap-1.5 font-display text-xl font-extrabold text-ink">
        {s.public && s.average !== null ? <><Star aria-hidden className="h-5 w-5 fill-accent text-accent" />{s.average.toFixed(1)}<span className="text-sm font-semibold text-ash">/ 5</span></> : "—"}
      </p>
      <p className="text-xs text-inkSoft">{s.count} note{s.count > 1 ? "s" : ""}{!s.public && s.count > 0 ? ` · ${hint}` : ""}</p>
    </div>
  );
}

/** Évaluation réciproque : notes rapides (étoiles, commentaire facultatif), critères adaptés à la personne évaluée, réputation réelle. */
export function MutualEvaluations({ onChanged }: { onChanged?: () => void }) {
  const { data, loading, error, reload } = useData<Evaluations>("/me/evaluations/", "Vos évaluations ne peuvent pas être chargées.");
  const [target, setTarget] = useState<PendingEvaluation | null>(null);
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [criteria, setCriteria] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [notice, setNotice] = useState("");
  const [contest, setContest] = useState<{ id: number } | null>(null);
  const [reason, setReason] = useState("");

  function open(p: PendingEvaluation) { setTarget(p); setRating(0); setComment(""); setCriteria({}); setFailure(""); }

  async function send() {
    if (!target || !rating) return;
    setBusy(true); setFailure("");
    try {
      await submitEvaluation(target.booking_id, { rating, comment: comment.trim() || undefined, criteria: Object.keys(criteria).length ? criteria : undefined });
      setTarget(null);
      setNotice(target.other_party_evaluated ? "Merci ! Les deux évaluations sont maintenant visibles." : `Merci ! Votre note sera visible quand ${ROLE_FR[target.evaluated_role]} aura évalué à son tour, ou dans ${data?.rules.reveal_days ?? 7} jours.`);
      await reload(); onChanged?.();
    } catch (e) { setFailure(evaluationError(e, "L’évaluation n’a pas pu être enregistrée.")); } finally { setBusy(false); }
  }

  async function sendContest() {
    if (!contest) return;
    setBusy(true); setFailure("");
    try { await contestEvaluation(contest.id, reason); setContest(null); setReason(""); setNotice("Contestation envoyée : l’équipe Tratra l’examine."); await reload(); }
    catch (e) { setFailure(evaluationError(e, "La contestation n’a pas pu être envoyée.")); } finally { setBusy(false); }
  }

  if (loading) return <SkeletonList count={1} />;
  if (error || !data) return <Alert tone="danger" className="mb-5" action={<Button size="sm" variant="outline" onClick={() => void reload()}>Réessayer</Button>}>{error}</Alert>;
  const providerPending = data.pending.filter((p) => p.role === "provider");
  const hasAnything = data.provider_score.count || data.requester_score.count || providerPending.length || data.received_as_requester.length;
  if (!hasAnything && !notice) return null;

  return (
    <Card className="mb-6">
      <CardHeader title="Évaluations réciproques" description="Après chaque mission, les deux parties se notent. Les notes restent masquées jusqu’à ce que chacun ait évalué (ou après un délai) pour éviter les représailles." icon={<Scale className="h-5 w-5" />} />
      {notice ? <Alert tone="success" className="mt-3">{notice}</Alert> : null}
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <ScoreBox label="Comme prestataire" s={data.provider_score} hint={`moyenne publiée dès ${data.rules.min_public_count} notes`} />
        <ScoreBox label="Comme demandeur" s={data.requester_score} hint={`moyenne publiée dès ${data.rules.min_public_count} notes`} />
        <div className="rounded-panel border border-lineSoft p-3"><p className="text-xs font-semibold text-ash">Missions évaluées</p><p className="mt-1 font-display text-xl font-extrabold text-ink">{data.missions_evaluated}</p><p className="text-xs text-inkSoft">notes réellement visibles</p></div>
      </div>

      {providerPending.length ? (
        <>
          <h3 className="mt-5 text-sm font-bold text-ink">Évaluer vos clients</h3>
          <ul className="mt-2 space-y-2">
            {providerPending.map((p) => (
              <li key={p.booking_id} className="flex flex-wrap items-center justify-between gap-3 rounded-panel border border-lineSoft p-3">
                <div className="min-w-0"><p className="truncate text-sm font-semibold text-ink">{p.service}</p><p className="text-xs text-ash">Jusqu’au {day(p.deadline)} · {p.other_party_evaluated ? "le client a déjà évalué : vos deux notes seront visibles" : "sa note restera masquée tant que vous n’avez pas évalué"}</p></div>
                <Button size="sm" onClick={() => open(p)}>Évaluer le client</Button>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {data.received_as_requester.length ? (
        <>
          <h3 className="mt-5 text-sm font-bold text-ink">Notes reçues comme demandeur</h3>
          <ul className="mt-2 space-y-2">
            {data.received_as_requester.map((r) => (
              <li key={r.id} className="flex flex-wrap items-start justify-between gap-3 rounded-panel border border-lineSoft p-3">
                <div className="min-w-0"><p className="flex items-center gap-1.5 text-sm font-semibold text-ink"><Star aria-hidden className="h-4 w-4 fill-accent text-accent" />{r.rating} / 5 <Badge tone="gray">par {r.from}</Badge></p>{r.comment ? <p className="mt-1 break-words text-sm text-inkSoft">{r.comment}</p> : null}</div>
                {r.can_contest ? <Button size="sm" variant="ghost" onClick={() => { setContest({ id: r.id }); setReason(""); setFailure(""); }}>Contester</Button> : <Badge tone="gray">Contestation envoyée</Badge>}
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <Modal open={Boolean(target)} onClose={() => !busy && setTarget(null)} title={target ? `Évaluer ${ROLE_FR[target.evaluated_role]}` : ""} description={target?.service} size="md"
        footer={<><Button variant="outline" onClick={() => setTarget(null)} disabled={busy}>Annuler</Button><Button onClick={() => void send()} loading={busy} disabled={!rating}>Envoyer</Button></>}>
        <div className="space-y-4">
          <div><p className="mb-1 text-sm font-semibold text-ink">Votre note</p><StarPicker label="Note globale" value={rating} onChange={setRating} /></div>
          <TextareaField label="Commentaire" optional rows={3} maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} hint="Pas de lien, d’e-mail ni de numéro de téléphone." />
          {target ? (
            <details className="rounded-panel bg-canvas p-3">
              <summary className="cursor-pointer text-sm font-semibold text-ink">Détailler par critère (facultatif)</summary>
              <ul className="mt-2 space-y-1">
                {target.criteria.map((c) => (
                  <li key={c.key} className="flex flex-wrap items-center justify-between gap-2 text-sm text-inkSoft"><span>{c.label}</span><StarPicker size="sm" clearable label={c.label} value={criteria[c.key] ?? 0} onChange={(v) => setCriteria((cur) => { const n = { ...cur }; if (v) n[c.key] = v; else delete n[c.key]; return n; })} /></li>
                ))}
              </ul>
            </details>
          ) : null}
          {failure ? <Alert tone="danger">{failure}</Alert> : null}
        </div>
      </Modal>

      <Modal open={Boolean(contest)} onClose={() => !busy && setContest(null)} title="Contester cette évaluation" description="Expliquez pourquoi elle vous semble injustifiée. L’équipe Tratra l’examine ; seule une décision humaine peut la masquer." size="md"
        footer={<><Button variant="outline" onClick={() => setContest(null)} disabled={busy}>Annuler</Button><Button onClick={() => void sendContest()} loading={busy} disabled={reason.trim().length < 10}>Envoyer</Button></>}>
        <div className="space-y-3"><TextareaField label="Votre explication" rows={4} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />{failure ? <Alert tone="danger">{failure}</Alert> : null}</div>
      </Modal>
    </Card>
  );
}
