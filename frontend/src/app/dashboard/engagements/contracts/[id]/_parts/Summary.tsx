"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Eye, FileText, Gavel, Hourglass, ShieldAlert } from "lucide-react";
import { Alert, Badge, Button, ButtonLink, Card, CardHeader, Checkbox, ConfirmDialog, SelectField, TextField, TextareaField } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api";
import {
  AMENDMENT_KIND_FR, DISPUTE_KIND_FR, MISSION_TYPE_FR, PERIOD_FR, RELATIONSHIP_FR, ROLE_FR, dateFr, dateTimeFr, durationLabel, eng, errFields, fcfa, scheduleLabel, type Amendment, type ContractDetail,
} from "@/lib/engagements";
import { ActionModal, Facts, useIntent } from "../../../_components/common";
import { ArticlesCard, DocumentsCard, SignCard } from "./Sealed";

interface Doc { terms_hash: string; terms_version: number; acceptances: { role: string; user: { name: string } | null; terms_version: number; terms_hash: string; accepted_at: string }[]; amendments: Amendment[]; notice: string }

export function AmendmentBanner({ a, onChanged }: { a: Amendment; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function go(path: string, body?: unknown) {
    setBusy(true);
    setError("");
    try {
      await eng.post(path, body);
      onChanged();
    } catch (e) {
      setError(apiErrorMessage(e, "Action impossible."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Alert tone="info" title={`Avenant ${a.status === "accepted" ? "accepté, en attente de sa date d’effet" : "à valider"} : ${AMENDMENT_KIND_FR[a.kind] ?? a.kind}`} icon={<Hourglass />}>
      <p>{describeChanges(a)} · effet le {dateFr(a.effective_date)}</p>
      <p className="mt-1 text-xs">Motif : {a.reason}</p>
      {error ? <p role="alert" className="mt-1 text-xs font-medium text-dangerInk">{error}</p> : null}
      <div className="mt-3 flex flex-wrap gap-2">
        {a.can_respond ? (
          <>
            <Button size="sm" loading={busy} onClick={() => void go(`/amendments/${a.id}/respond/`, { accept: true })}>Accepter l’avenant</Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void go(`/amendments/${a.id}/respond/`, { accept: false })}>Refuser</Button>
          </>
        ) : null}
        {a.can_withdraw ? <Button size="sm" variant="outline" loading={busy} onClick={() => void go(`/amendments/${a.id}/withdraw/`)}>Retirer ma proposition</Button> : null}
      </div>
    </Alert>
  );
}

const CHANGE_LABEL: Record<string, string> = {
  amount: "Montant", end_date: "Fin", notice_period_days: "Préavis (jours)", conditions: "Conditions", payment_day: "Jour de paiement", overtime_hourly_rate: "Taux heures supplémentaires",
  schedule: "Planning", description: "Missions", starts_on: "Début de suspension", ends_on: "Fin de suspension", auto_renew: "Renouvellement automatique", renewal_term_months: "Durée de renouvellement",
  location_address: "Adresse", location_city: "Ville", proration_mode: "Prorata", hours_per_week: "Heures par semaine",
};
export function describeChanges(a: Amendment): string {
  const parts = Object.entries(a.changes ?? {}).map(([k, v]) => {
    const label = CHANGE_LABEL[k] ?? k;
    if (k === "amount" || k === "overtime_hourly_rate") return `${label} : ${fcfa(String(v))}`;
    if (k === "schedule") return `${label} modifié`;
    if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v)) return `${label} : ${dateFr(v)}`;
    if (typeof v === "boolean") return `${label} : ${v ? "oui" : "non"}`;
    return `${label} : ${String(v).slice(0, 80)}`;
  });
  return parts.join(" · ") || (AMENDMENT_KIND_FR[a.kind] ?? a.kind);
}

/** Acceptation : liée à l'empreinte EXACTE des conditions affichées — si elles ont changé entre-temps, le serveur refuse. */
function AcceptCard({ c, onChanged }: { c: ContractDetail; onChanged: () => void }) {
  const intent = useIntent("accept");
  const [read, setRead] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [back, setBack] = useState(false);
  const [decline, setDecline] = useState(false);
  const [note, setNote] = useState("");
  const accept = async () => {
    setBusy(true);
    setError("");
    try {
      await eng.post(`/contracts/${c.id}/accept/`, { terms_hash: c.terms_hash }, intent.key({ h: c.terms_hash }));
      onChanged();
    } catch (e) {
      setError(apiErrorMessage(e, "Acceptation impossible. Rien n’a été enregistré."));
      onChanged();
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card variant="accent" padding="md" className="mb-6">
      <CardHeader title="Ce contrat attend votre réponse" description={`${c.counterpart.name} vous propose ces conditions. Relisez-les en entier : votre acceptation porte sur cette version exacte.`} icon={<FileText className="h-5 w-5" />} />
      <Checkbox checked={read} onChange={(e) => setRead(e.target.checked)} label={`J’ai lu les conditions ci-dessous (version ${c.terms_version}, empreinte ${c.terms_hash.slice(0, 8)}) et j’accepte ce contrat.`} />
      {error ? <Alert tone="danger" className="mt-3">{error}</Alert> : null}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button disabled={!read} loading={busy} onClick={() => void accept()}>Accepter le contrat</Button>
        <Button variant="outline" onClick={() => setBack(true)}>Demander une modification</Button>
        <Button variant="ghost" onClick={() => setDecline(true)}>Refuser</Button>
      </div>
      <ActionModal open={back} title="Demander une modification" description="Le contrat repasse en brouillon chez son auteur, avec votre demande." confirmLabel="Envoyer la demande" disabled={note.trim().length < 5} onClose={() => setBack(false)}
        onSubmit={async () => { await eng.post(`/contracts/${c.id}/send-back/`, { note: note.trim() }); setBack(false); onChanged(); }}>
        <TextareaField label="Ce que vous souhaitez changer" required rows={4} value={note} onChange={(e) => setNote(e.target.value)} />
      </ActionModal>
      <ActionModal open={decline} tone="danger" title="Refuser ce contrat ?" description="Il est annulé ; l’autre partie en est informée." confirmLabel="Refuser le contrat" onClose={() => setDecline(false)}
        onSubmit={async () => { await eng.post(`/contracts/${c.id}/decline/`, { reason: note.trim() }); setDecline(false); onChanged(); }}>
        <TextareaField label="Motif (facultatif)" optional rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
      </ActionModal>
    </Card>
  );
}

function NoticeModal({ c, open, onClose, onDone }: { c: ContractDetail; open: boolean; onClose: () => void; onDone: () => void }) {
  const intent = useIntent("notice");
  const [last, setLast] = useState("");
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const min = new Date(Date.now() + c.notice_period_days * 86400000).toISOString().slice(0, 10);
  const body = { last_day: last, reason: reason.trim(), expected_version: c.version };
  return (
    <ActionModal open={open} title="Donner un préavis" description={`Le contrat prévoit ${c.notice_period_days} jours de préavis. Le contrat se termine à la date choisie ; les échéances postérieures sont annulées.`}
      confirmLabel="Donner le préavis" tone="danger" disabled={!last || reason.trim().length < 5} onClose={onClose} onError={(e) => setErrors(errFields(e))}
      onSubmit={async () => { await eng.post(`/contracts/${c.id}/notice/`, body, intent.key(body)); onDone(); }}>
      <TextField label="Dernier jour du contrat" type="date" required min={min} value={last} error={errors.last_day} onChange={(e) => setLast(e.target.value)} hint={`Au plus tôt le ${dateFr(min)}.`} />
      <TextareaField label="Motif" required rows={3} value={reason} error={errors.reason} onChange={(e) => setReason(e.target.value)} />
    </ActionModal>
  );
}

function DisputeModal({ c, open, onClose, onDone }: { c: ContractDetail; open: boolean; onClose: () => void; onDone: () => void }) {
  const intent = useIntent("dispute");
  const [kind, setKind] = useState("conditions");
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const body = { kind, reason: reason.trim() };
  return (
    <ActionModal open={open} title="Signaler un désaccord" description="Un litige est examiné par l’équipe Tratra, qui peut médier, suspendre ou résilier le contrat. Il ne modifie aucun montant." confirmLabel="Ouvrir le litige"
      disabled={reason.trim().length < 10} onClose={onClose} onError={(e) => setErrors(errFields(e))}
      onSubmit={async () => { await eng.post(`/contracts/${c.id}/disputes/`, body, intent.key(body)); intent.reset(); setReason(""); onDone(); }}>
      <SelectField label="Nature" value={kind} onChange={(e) => setKind(e.target.value)}>
        {Object.entries(DISPUTE_KIND_FR).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </SelectField>
      <TextareaField label="Décrivez le désaccord" required rows={5} maxLength={2000} value={reason} error={errors.reason} onChange={(e) => setReason(e.target.value)} hint="Faits, dates, ce que vous attendez (10 caractères minimum)." />
    </ActionModal>
  );
}

function DocumentModal({ c, open, onClose }: { c: ContractDetail; open: boolean; onClose: () => void }) {
  const [doc, setDoc] = useState<Doc | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setDoc(null);
    setError("");
    eng.get<Doc>(`/contracts/${c.id}/document/`).then((d) => { if (alive) setDoc(d); }).catch((e) => { if (alive) setError(apiErrorMessage(e, "Document indisponible.")); });
    return () => { alive = false; };
  }, [open, c.id, c.version]);
  return (
    <ActionModal open={open} size="lg" title="Document du contrat" description="Trace des acceptations de chaque version des conditions." confirmLabel="Fermer" onClose={onClose} onSubmit={async () => onClose()}>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {doc ? (
        <div className="space-y-4 text-sm">
          <p className="rounded-panel bg-canvas p-3 text-xs text-ash">{doc.notice}</p>
          <p>Version <strong>{doc.terms_version}</strong> · empreinte <code className="break-all rounded bg-canvas px-1.5 py-0.5 text-xs">{doc.terms_hash}</code></p>
          <div>
            <h3 className="mb-1 font-bold text-ink">Acceptations</h3>
            <ul className="space-y-1">
              {doc.acceptances.map((a, i) => <li key={i}>{ROLE_FR[a.role]} — {a.user?.name ?? "—"} · version {a.terms_version} · {dateTimeFr(a.accepted_at)}</li>)}
            </ul>
          </div>
          {doc.amendments.length ? (
            <div>
              <h3 className="mb-1 font-bold text-ink">Avenants</h3>
              <ul className="space-y-1">{doc.amendments.map((a) => <li key={a.id}>{AMENDMENT_KIND_FR[a.kind]} — {describeChanges(a)} · effet le {dateFr(a.effective_date)} <Badge tone="gray">{a.status}</Badge></li>)}</ul>
            </div>
          ) : null}
        </div>
      ) : !error ? <p role="status" className="text-sm text-ash">Chargement…</p> : null}
    </ActionModal>
  );
}

export function Summary({ c, reload, goTab, openAmend }: { c: ContractDetail; reload: () => void; goTab: (t: "pay" | "planning" | "amendments" | "evaluations" | "history") => void; openAmend: () => void }) {
  const [notice, setNotice] = useState(false);
  const [dispute, setDispute] = useState(false);
  const [doc, setDoc] = useState(false);
  const [confirm, setConfirm] = useState<"resume" | "non_renewal" | "close" | "cancel" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const has = (a: string) => c.actions.includes(a);
  const iAccepted = c.accepted_by.includes(c.my_role);

  async function confirmed() {
    if (!confirm) return;
    setBusy(true);
    setError("");
    const path = { resume: "resume", non_renewal: "non-renewal", close: "close", cancel: "decline" }[confirm];
    try {
      await eng.post(`/contracts/${c.id}/${path}/`, confirm === "cancel" ? { reason: "Annulé par son auteur avant acceptation." } : undefined);
      setConfirm(null);
      reload();
    } catch (e) {
      setError(apiErrorMessage(e, "Action impossible."));
      setConfirm(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {c.status === "pending_acceptance" && has("accept") ? <AcceptCard c={c} onChanged={reload} /> : null}
      <SignCard c={c} onChanged={reload} />
      {c.status === "pending_acceptance" && iAccepted ? (
        <Alert tone="info" className="mb-6" title="En attente de l’autre partie">{c.counterpart.name} doit relire et accepter ces conditions. Vous serez prévenu(e) dès sa réponse.</Alert>
      ) : null}
      {c.quality_warnings?.length ? (
        <Alert tone="warning" className="mb-6" title="À vérifier avant de proposer" icon={<ShieldAlert />}>
          <ul className="list-disc space-y-1 pl-5">{c.quality_warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </Alert>
      ) : null}
      {c.status === "draft" ? <Alert tone="brand" className="mb-6" title="Brouillon">Ce contrat n’est visible que de vous. « Proposer » l’envoie à {c.worker.name}, qui peut l’accepter, demander une modification ou le refuser.</Alert> : null}
      {c.pending_amendment ? <div className="mb-6"><AmendmentBanner a={c.pending_amendment} onChanged={reload} /></div> : null}
      {c.status === "notice" ? <Alert tone="warning" className="mb-6" icon={<Hourglass />} title={`Préavis en cours : fin le ${dateFr(c.ends_on)}`}>{c.end_reason}</Alert> : null}
      {c.suspensions.some((s) => s.source === "admin" && !s.ends_on) ? <Alert tone="danger" className="mb-6" icon={<ShieldAlert />} title="Contrat suspendu par Tratra">La plateforme a suspendu ce contrat. Elle seule peut lever la suspension ; vous serez informé(e) de la suite.</Alert> : null}
      {error ? <Alert tone="danger" className="mb-6">{error}</Alert> : null}

      <Card padding="md">
        <CardHeader title="Conditions" action={<Button size="sm" variant="outline" leftIcon={<Eye aria-hidden className="h-4 w-4" />} onClick={() => setDoc(true)}>Document et acceptations</Button>} />
        <Facts items={[
          ["Donneur d’ordre", `${c.principal.name}${c.organization ? ` (${c.organization.name})` : ""}`], ["Prestataire", c.worker.name], ["Nature", RELATIONSHIP_FR[c.work_relationship]], ["Type", MISSION_TYPE_FR[c.mission_type]],
          ["Rémunération", `${fcfa(c.amount, c.currency)} ${PERIOD_FR[c.period]}`], ["Paiement", c.payment_day ? `le ${c.payment_day} qui suit la fin de chaque période` : "—"],
          ["Début", dateFr(c.start_date)], ["Fin", c.end_date ? `${dateFr(c.end_date)} (${durationLabel(c)})` : "Durée indéterminée"], ["Planning", scheduleLabel(c.schedule)], ["Heures par semaine", c.hours_per_week ? `${Number(c.hours_per_week)} h` : "—"],
          ["Préavis", `${c.notice_period_days} jours`], ["Lieu", [c.location_address, c.location_city].filter(Boolean).join(", ")],
          ["Renouvellement", c.auto_renew && c.end_date ? `Automatique (${c.renewal_term_months} mois)${c.non_renewal_at ? " — refusé" : c.non_renewal_deadline ? `, non-renouvellement possible jusqu’au ${dateFr(c.non_renewal_deadline)}` : ""}${c.renewal_count ? ` · renouvelé ${c.renewal_count} fois` : ""}` : "Non"],
          ["Heures supplémentaires", c.overtime_hourly_rate ? `${fcfa(c.overtime_hourly_rate)} / h` : "Non valorisées"], ["Prorata dernière période", c.proration_mode === "calendar_days" ? "Jours calendaires" : "Aucun"],
          ["Avantages", c.benefits || "—"], ["Référence", c.reference ?? "—"],
          ["Réservations", c.bookings_mode === "per_occurrence" ? "Une réservation Tratra par intervention" : "Aucune"],
        ]} />
        {c.description ? <div className="mt-5"><h3 className="text-sm font-bold text-ink">Missions confiées</h3><p className="mt-1 whitespace-pre-line text-sm text-inkSoft">{c.description}</p></div> : null}
        {c.conditions ? <div className="mt-4"><h3 className="text-sm font-bold text-ink">Conditions particulières</h3><p className="mt-1 whitespace-pre-line text-sm text-inkSoft">{c.conditions}</p></div> : null}
        {c.suspensions.length ? (
          <div className="mt-4">
            <h3 className="text-sm font-bold text-ink">Suspensions</h3>
            <ul className="mt-1 space-y-0.5 text-sm text-inkSoft">{c.suspensions.map((s, i) => <li key={i}>Du {dateFr(s.starts_on)} {s.ends_on ? `au ${dateFr(s.ends_on)}` : "(sans date de fin)"} — {s.source === "admin" ? "décision de Tratra" : "d’un commun accord"} : {s.reason}</li>)}</ul>
          </div>
        ) : null}
        <p className="mt-5 rounded-panel bg-canvas p-3 text-xs text-ash">{c.legal_notice} Les paiements sont déclarés par une partie et ne comptent qu’une fois confirmés par l’autre : Tratra ne verse ni n’encaisse la rémunération.</p>
      </Card>
      <ArticlesCard c={c} />
      <DocumentsCard c={c} />

      {["accepted", "signed", "active", "suspended", "notice", "terminated", "completed"].includes(c.status) && !(c.status === "accepted" && c.signature_required) ? (
        <Card padding="md" className="mt-6">
          <CardHeader title="Actions" icon={<Gavel className="h-5 w-5" />} />
          <div className="flex flex-wrap gap-2">
            {has("propose_amendment") && !c.pending_amendment ? <Button variant="outline" onClick={openAmend}>Proposer un avenant</Button> : null}
            {has("give_notice") ? <Button variant="outline" onClick={() => setNotice(true)}>Donner un préavis</Button> : null}
            {has("declare_non_renewal") ? <Button variant="outline" onClick={() => setConfirm("non_renewal")}>Refuser le renouvellement</Button> : null}
            {has("resume") ? <Button variant="outline" onClick={() => setConfirm("resume")}>Reprendre le contrat</Button> : null}
            {has("evaluate") ? <Button variant="soft" onClick={() => goTab("evaluations")}>Évaluer</Button> : null}
            {has("close") ? <Button variant="outline" onClick={() => setConfirm("close")}>Clôturer le contrat</Button> : null}
            {has("dispute") ? <Button variant="ghost" onClick={() => setDispute(true)}>Signaler un désaccord</Button> : null}
          </div>
          {c.status === "terminated" || c.status === "completed" ? <p className="mt-3 text-xs text-ash">La clôture fige l’historique financier ; elle n’est possible que lorsque plus aucune échéance n’est due. Les évaluations restent possibles dans les 60 jours.</p> : null}
        </Card>
      ) : null}

      <NoticeModal c={c} open={notice} onClose={() => setNotice(false)} onDone={() => { setNotice(false); reload(); }} />
      <DisputeModal c={c} open={dispute} onClose={() => setDispute(false)} onDone={() => { setDispute(false); goTab("history"); reload(); }} />
      <DocumentModal c={c} open={doc} onClose={() => setDoc(false)} />
      <ConfirmDialog open={confirm !== null} loading={busy} onClose={() => setConfirm(null)} onConfirm={() => void confirmed()}
        confirmLabel={{ resume: "Reprendre", non_renewal: "Refuser le renouvellement", close: "Clôturer", cancel: "Annuler le contrat" }[confirm ?? "resume"]}
        title={{ resume: "Reprendre ce contrat ?", non_renewal: "Refuser le renouvellement ?", close: "Clôturer ce contrat ?", cancel: "Annuler ce contrat ?" }[confirm ?? "resume"]}
        description={{ resume: "La suspension convenue prend fin aujourd’hui.", non_renewal: `Le contrat prendra fin à son terme, le ${dateFr(c.end_date)}. L’autre partie en est informée.`, close: "L’historique financier est figé.", cancel: "L’autre partie est informée." }[confirm ?? "resume"]} />
      {c.status === "draft" ? <p className="mt-6 text-xs text-ash"><Link href="/dashboard/engagements" className="underline">Retour aux engagements</Link></p> : null}
    </>
  );
}
