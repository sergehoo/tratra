"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { CalendarClock, FilePenLine, FileSignature, Send, UserCheck } from "lucide-react";
import { Alert, Badge, Button, ButtonLink, Card, CardHeader, ConfirmDialog, EmptyState, PageHeader, SelectField, StatusBadge, TextField, TextareaField } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api";
import {
  INTERVIEW_MODE_FR, MISSION_TYPE_FR, PERIOD_FR, RELATIONSHIP_FR, dateFr, dateTimeFr, eng, errFields, fcfa, scheduleLabel, type Application, type Interview, type Page, type Posting,
} from "@/lib/engagements";
import { ActionModal, Facts, LoadState, useIntent, useLoad } from "../../_components/common";
import { InvitePanel } from "../../_components/Invitations";

const INTERVIEW_STATUS_FR: Record<string, string> = { proposed: "Proposé", confirmed: "Confirmé", declined: "Refusé", cancelled: "Annulé", done: "Effectué" };

/** Entretien proposé : l'autre partie confirme ou refuse ; l'auteur peut annuler ; le donneur d'ordre marque « effectué ». */
function InterviewLine({ i, owner, onDone }: { i: Interview; owner: boolean; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function op(name: "confirm" | "decline" | "cancel" | "done") {
    setBusy(true);
    setError("");
    try {
      await eng.post(`/interviews/${i.id}/respond/`, { op: name });
      onDone();
    } catch (e) {
      setError(apiErrorMessage(e, "Action impossible."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <li className="rounded-panel bg-canvas p-3 text-sm">
      <p className="font-semibold text-ink">
        <CalendarClock aria-hidden className="mr-1.5 inline h-4 w-4 text-primary" />
        {dateTimeFr(i.scheduled_at)} · {i.duration_minutes} min · {INTERVIEW_MODE_FR[i.mode] ?? i.mode} <Badge tone={i.status === "confirmed" ? "success" : i.status === "proposed" ? "accent" : "gray"}>{INTERVIEW_STATUS_FR[i.status] ?? i.status}</Badge>
      </p>
      {i.place_note ? <p className="mt-1 text-ash">{i.place_note}</p> : null}
      {i.status === "proposed" || i.status === "confirmed" ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {i.status === "proposed" && !i.proposed_by_me ? (
            <>
              <Button size="sm" loading={busy} onClick={() => void op("confirm")}>Confirmer</Button>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => void op("decline")}>Refuser</Button>
            </>
          ) : null}
          {i.proposed_by_me && i.status === "proposed" ? <Button size="sm" variant="outline" disabled={busy} onClick={() => void op("cancel")}>Annuler la proposition</Button> : null}
          {owner && i.status === "confirmed" ? <Button size="sm" variant="soft" disabled={busy} onClick={() => void op("done")}>Marquer comme effectué</Button> : null}
        </div>
      ) : null}
      {error ? <p role="alert" className="mt-1 text-xs font-medium text-dangerInk">{error}</p> : null}
    </li>
  );
}

function InterviewModal({ app, onClose, onDone }: { app: Application | null; onClose: () => void; onDone: () => void }) {
  const intent = useIntent("interview");
  const [when, setWhen] = useState("");
  const [duration, setDuration] = useState("30");
  const [mode, setMode] = useState("phone");
  const [place, setPlace] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const body = { scheduled_at: when ? new Date(when).toISOString() : "", duration_minutes: Number(duration), mode, place_note: place.trim() };
  return (
    <ActionModal open={Boolean(app)} title={`Entretien avec ${app?.applicant?.name ?? "le candidat"}`} description="Le candidat reçoit la proposition et la confirme ou la refuse." confirmLabel="Proposer l’entretien"
      disabled={!when} onClose={onClose} onError={(e) => setErrors(errFields(e))}
      onSubmit={async () => {
        await eng.post(`/applications/${app?.id}/interviews/`, body, intent.key({ ...body, app: app?.id }));
        intent.reset();
        setWhen("");
        onDone();
      }}>
      <TextField label="Date et heure" type="datetime-local" required value={when} error={errors.scheduled_at} onChange={(e) => setWhen(e.target.value)} />
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField label="Durée" value={duration} onChange={(e) => setDuration(e.target.value)}>
          {[15, 30, 45, 60, 90].map((m) => <option key={m} value={m}>{m} minutes</option>)}
        </SelectField>
        <SelectField label="Mode" value={mode} onChange={(e) => setMode(e.target.value)}>
          {Object.entries(INTERVIEW_MODE_FR).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </SelectField>
      </div>
      <TextField label="Précisions" optional value={place} onChange={(e) => setPlace(e.target.value)} hint="Lieu de rendez-vous ou lien d’appel. Évitez les données personnelles sensibles." />
    </ActionModal>
  );
}

function ApplicationCard({ a, onChanged }: { a: Application; onChanged: () => void }) {
  const [interview, setInterview] = useState<Application | null>(null);
  const [confirm, setConfirm] = useState<"select" | "reject" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const open = a.status === "submitted" || a.status === "shortlisted" || a.status === "interview";
  async function decide(decision: "shortlist" | "reject" | "select") {
    setBusy(true);
    setError("");
    try {
      await eng.post(`/applications/${a.id}/decision/`, { decision });
      setConfirm(null);
      onChanged();
    } catch (e) {
      setError(apiErrorMessage(e, "Décision impossible."));
    } finally {
      setBusy(false);
    }
  }
  const xp = a.experience;
  return (
    <li className="rounded-card border border-lineSoft bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-display text-base font-bold text-ink">{a.applicant?.name}</p>
          {xp ? (
            <p className="mt-0.5 text-xs text-ash">
              Expérience vérifiée sur Tratra : {xp.contracts_completed} contrat(s) terminé(s), {xp.months_total} mois{xp.evaluations.average ? `, note ${xp.evaluations.average.toLocaleString("fr-FR")}/5 (${xp.evaluations.count})` : ""}
            </p>
          ) : null}
        </div>
        <StatusBadge kind="application" status={a.status} />
      </div>
      {a.message ? <p className="mt-2 whitespace-pre-line text-sm text-inkSoft">{a.message}</p> : null}
      <p className="mt-2 text-xs text-ash">
        Reçue le {dateFr(a.created_at.slice(0, 10))}{a.proposed_amount ? ` · propose ${fcfa(a.proposed_amount)}` : ""}{a.available_from ? ` · disponible dès le ${dateFr(a.available_from)}` : ""}
      </p>
      {a.interviews.length ? <ul className="mt-3 space-y-2">{a.interviews.map((i) => <InterviewLine key={i.id} i={i} owner onDone={onChanged} />)}</ul> : null}
      {error ? <p role="alert" className="mt-2 text-xs font-medium text-dangerInk">{error}</p> : null}
      <div className="mt-3 flex flex-wrap gap-2">
        {open ? (
          <>
            {a.status === "submitted" ? <Button size="sm" variant="soft" disabled={busy} onClick={() => void decide("shortlist")}>Présélectionner</Button> : null}
            <Button size="sm" variant="outline" onClick={() => setInterview(a)}>Proposer un entretien</Button>
            <Button size="sm" leftIcon={<UserCheck aria-hidden className="h-4 w-4" />} onClick={() => setConfirm("select")}>Retenir</Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirm("reject")}>Refuser</Button>
          </>
        ) : null}
        {a.status === "selected" ? (
          a.contract_id ? (
            <ButtonLink size="sm" href={`/dashboard/engagements/contracts/${a.contract_id}`} leftIcon={<FileSignature aria-hidden className="h-4 w-4" />}>Ouvrir le contrat</ButtonLink>
          ) : (
            <ButtonLink size="sm" href={`/dashboard/engagements/contracts/new?application=${a.id}&posting=${a.posting}`} leftIcon={<FilePenLine aria-hidden className="h-4 w-4" />}>Préparer le contrat</ButtonLink>
          )
        ) : null}
      </div>
      <InterviewModal app={interview} onClose={() => setInterview(null)} onDone={() => { setInterview(null); onChanged(); }} />
      <ConfirmDialog open={confirm !== null} onClose={() => setConfirm(null)} loading={busy} tone={confirm === "reject" ? "danger" : "primary"} confirmLabel={confirm === "reject" ? "Refuser la candidature" : "Retenir ce candidat"}
        title={confirm === "reject" ? "Refuser cette candidature ?" : `Retenir ${a.applicant?.name} ?`} onConfirm={() => void decide(confirm === "reject" ? "reject" : "select")}
        description={confirm === "reject" ? "Le candidat est prévenu. Cette décision est définitive pour cette candidature." : "Vous préparerez ensuite le contrat : rien ne vous engage tant que les deux parties ne l’ont pas accepté."} />
    </li>
  );
}

function Applications({ posting }: { posting: Posting }) {
  const { data, error, loading, reload } = useLoad(() => eng.get<Page<Application>>(`/postings/${posting.id}/applications/?limit=50`), [posting.id]);
  return (
    <Card padding="md" className="mt-6">
      <CardHeader title="Candidatures" description="Les candidats sont des professionnels vérifiés. Vous choisissez, puis vous préparez le contrat." icon={<UserCheck className="h-5 w-5" />} />
      <LoadState loading={loading} error={error} hasData={Boolean(data)} reload={() => void reload()}>
        {data && data.results.length === 0 ? (
          <EmptyState compact title="Aucune candidature pour le moment" description={posting.status === "open" ? "Elles apparaîtront ici dès qu’un professionnel postulera." : "Publiez le besoin pour recevoir des candidatures."} />
        ) : (
          <ul className="space-y-3">{data?.results.map((a) => <ApplicationCard key={a.id} a={a} onChanged={() => void reload()} />)}</ul>
        )}
      </LoadState>
    </Card>
  );
}

function ApplyCard({ posting, mine, onChanged }: { posting: Posting; mine: Application | null; onChanged: () => void }) {
  const intent = useIntent("apply");
  const [message, setMessage] = useState("");
  const [amount, setAmount] = useState("");
  const [from, setFrom] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (mine) {
    return (
      <Card padding="md" className="mt-6">
        <CardHeader title="Ma candidature" action={<StatusBadge kind="application" status={mine.status} />} icon={<Send className="h-5 w-5" />} />
        {mine.message ? <p className="whitespace-pre-line text-sm text-inkSoft">{mine.message}</p> : null}
        {mine.interviews.length ? <ul className="mt-3 space-y-2">{mine.interviews.map((i) => <InterviewLine key={i.id} i={i} owner={false} onDone={onChanged} />)}</ul> : null}
        {mine.status === "selected" ? (
          <Alert tone="success" className="mt-3">
            Votre candidature est retenue. {mine.contract_id ? <Link href={`/dashboard/engagements/contracts/${mine.contract_id}`}>Ouvrir le contrat</Link> : "Le donneur d’ordre prépare le contrat : vous serez prévenu(e) pour le relire et l’accepter."}
          </Alert>
        ) : null}
        {mine.status === "submitted" || mine.status === "shortlisted" || mine.status === "interview" ? (
          <Button className="mt-3" variant="outline" size="sm" onClick={async () => { try { await eng.post(`/applications/${mine.id}/withdraw/`); onChanged(); } catch (e) { setError(apiErrorMessage(e, "Retrait impossible.")); } }}>Retirer ma candidature</Button>
        ) : null}
        {error ? <p role="alert" className="mt-2 text-xs font-medium text-dangerInk">{error}</p> : null}
      </Card>
    );
  }
  if (!posting.can_apply) {
    return (
      <Alert tone="info" className="mt-6" title="Postuler">
        {posting.status !== "open" ? "Ce besoin n’accepte plus de candidatures." : <>Postuler demande un profil professionnel vérifié par Tratra. <Link href="/dashboard/profile/kyc">Ouvrir mon dossier</Link>.</>}
      </Alert>
    );
  }
  const body = { message: message.trim(), proposed_amount: amount.trim() || undefined, available_from: from || undefined };
  async function submit() {
    setBusy(true);
    setError("");
    setErrors({});
    try {
      await eng.post(`/postings/${posting.id}/apply/`, body, intent.key(body));
      intent.reset();
      onChanged();
    } catch (e) {
      setErrors(errFields(e));
      setError(apiErrorMessage(e, "Candidature impossible. Rien n’a été envoyé."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card padding="md" className="mt-6">
      <CardHeader title="Postuler" description="Présentez-vous en quelques lignes. Votre nom public et votre expérience vérifiée sur Tratra sont partagés ; jamais votre téléphone." icon={<Send className="h-5 w-5" />} />
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <TextareaField label="Message" rows={4} maxLength={2000} value={message} error={errors.message} onChange={(e) => setMessage(e.target.value)} hint="Expérience utile, disponibilités, questions." />
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Votre montant proposé (FCFA)" optional inputMode="decimal" value={amount} error={errors.proposed_amount} onChange={(e) => setAmount(e.target.value)} hint={`Offre : ${fcfa(posting.amount, posting.currency)} ${PERIOD_FR[posting.period]}`} />
          <TextField label="Disponible à partir du" type="date" optional value={from} error={errors.available_from} onChange={(e) => setFrom(e.target.value)} />
        </div>
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <Button type="submit" loading={busy}>Envoyer ma candidature</Button>
      </form>
    </Card>
  );
}

export default function PostingPage() {
  const { id } = useParams<{ id: string }>();
  const posting = useLoad(() => eng.get<Posting>(`/postings/${id}/`), [id]);
  const mine = useLoad(async () => (await eng.get<Page<Application>>("/applications/mine/?limit=50")).results.find((a) => String(a.posting) === id) ?? null, [id]);
  const [busy, setBusy] = useState(false);
  const [closing, setClosing] = useState(false);
  const [error, setError] = useState("");
  const p = posting.data;

  async function act(path: string, body?: unknown) {
    setBusy(true);
    setError("");
    try {
      await eng.post(path, body);
      setClosing(false);
      await posting.reload();
    } catch (e) {
      setError(apiErrorMessage(e, "Action impossible."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <LoadState loading={posting.loading} error={posting.error} hasData={Boolean(p)} reload={() => void posting.reload()}>
      {p ? (
        <>
          <PageHeader back={{ href: p.mine ? "/dashboard/engagements" : "/dashboard/engagements/offers", label: p.mine ? "Engagements" : "Offres" }} title={p.title}
            eyebrow={<StatusBadge kind="posting" status={p.status} />}
            description={`${p.category.name} · ${p.city} · ${MISSION_TYPE_FR[p.mission_type]} · publié par ${p.organization?.name ?? p.publisher?.name ?? "un utilisateur Tratra"}`}
            actions={p.mine ? (
              <>
                {p.status === "draft" || p.status === "open" ? <ButtonLink href={`/dashboard/engagements/postings/${p.id}/edit`} variant="outline">Modifier</ButtonLink> : null}
                {p.status === "draft" ? <Button loading={busy} onClick={() => void act(`/postings/${p.id}/publish/`)}>Publier</Button> : null}
                {p.status === "open" ? <Button variant="outline" onClick={() => setClosing(true)}>Clore le besoin</Button> : null}
              </>
            ) : undefined} />
          {error ? <Alert tone="danger" className="mb-4">{error}</Alert> : null}
          {p.work_relationship === "employment" && p.legal_notice ? <Alert tone="warning" className="mb-4" title={RELATIONSHIP_FR.employment}>{p.legal_notice}</Alert> : null}
          <Card padding="md">
            <Facts items={[
              ["Rémunération", `${fcfa(p.amount, p.currency)} ${PERIOD_FR[p.period]}`], ["Nature", RELATIONSHIP_FR[p.work_relationship]], ["Début souhaité", dateFr(p.start_date)],
              ["Fin souhaitée", p.end_date ? dateFr(p.end_date) : "Durée indéterminée"], ["Planning", scheduleLabel(p.schedule)], ["Heures par semaine", p.hours_per_week ? `${Number(p.hours_per_week)} h` : "—"],
              ["Candidatures jusqu’au", p.application_deadline ? dateFr(p.application_deadline) : "Sans date limite"], ["Zone", p.location_note],
              ["Durée", p.duration_months ? `${p.duration_months} mois` : "—"], ["Avantages", p.benefits || "—"],
            ]} />
            {p.description ? <div className="mt-5"><h2 className="text-sm font-bold text-ink">Mission</h2><p className="mt-1 whitespace-pre-line text-sm text-inkSoft">{p.description}</p></div> : null}
            {p.conditions ? <div className="mt-4"><h2 className="text-sm font-bold text-ink">Conditions</h2><p className="mt-1 whitespace-pre-line text-sm text-inkSoft">{p.conditions}</p></div> : null}
          </Card>
          {p.mine && p.status === "open" ? <InvitePanel postingId={p.id} /> : null}
          {p.mine ? <Applications posting={p} /> : <LoadState loading={mine.loading} error={mine.error} hasData={!mine.loading && !mine.error} reload={() => void mine.reload()}><ApplyCard posting={p} mine={mine.data} onChanged={() => { void mine.reload(); void posting.reload(); }} /></LoadState>}
          <ConfirmDialog open={closing} onClose={() => setClosing(false)} loading={busy} confirmLabel="Clore le besoin" tone="danger" title="Clore ce besoin ?" onConfirm={() => void act(`/postings/${p.id}/close/`)}
            description="Il n’accepte plus de candidatures. Les candidatures déjà reçues restent consultables." />
        </>
      ) : null}
    </LoadState>
  );
}
