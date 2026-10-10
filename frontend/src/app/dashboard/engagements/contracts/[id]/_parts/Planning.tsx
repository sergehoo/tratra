"use client";
import { useMemo, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, MapPinOff, Repeat } from "lucide-react";
import { Alert, Badge, Button, Card, CardHeader, EmptyState, SelectField, TextField, TextareaField } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api";
import { ATTENDANCE_FR, EVENT_KIND_FR, EVENT_STATUS_FR, dateShortFr, eng, errFields, timeFr, type ContractDetail, type ScheduleEvent } from "@/lib/engagements";
import { ActionModal, LoadState, useIntent, useLoad } from "../../../_components/common";
import { WorkerPicker, type PickedWorker } from "../../../_components/WorkerPicker";

const iso = (d: Date) => d.toISOString().slice(0, 10);
const addDays = (d: Date, n: number) => new Date(d.getTime() + n * 86400000);

function RequestModal({ c, kind, onClose, onDone }: { c: ContractDetail; kind: "leave" | "overtime" | null; onClose: () => void; onDone: () => void }) {
  const intent = useIntent("event");
  const [sub, setSub] = useState<string>("leave");
  const [date, setDate] = useState("");
  const [end, setEnd] = useState("");
  const [hours, setHours] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const type = kind === "overtime" ? "overtime" : sub;
  const body = { kind: type, date, end_date: type === "overtime" ? undefined : end || undefined, hours: type === "overtime" ? hours : undefined, note: note.trim() };
  const other = c.my_role === "worker" ? c.principal.name : c.worker.name;
  return (
    <ActionModal open={kind !== null} title={kind === "overtime" ? "Déclarer des heures supplémentaires" : "Demander un congé, une absence ou un repos"} confirmLabel="Envoyer la demande" disabled={!date || (type === "overtime" && !hours)}
      description={`${other} doit la valider. ${kind === "overtime" ? (c.overtime_hourly_rate ? "Une fois validées, elles sont ajoutées à l’échéance au taux du contrat." : "Le contrat ne fixe aucun taux : elles sont enregistrées mais Tratra ne les valorise pas.") : "Les interventions couvertes sont retirées du planning une fois la demande validée."}`}
      onClose={onClose} onError={(e) => setErrors(errFields(e))}
      onSubmit={async () => { await eng.post(`/contracts/${c.id}/events/`, body, intent.key(body)); intent.reset(); setNote(""); setDate(""); setEnd(""); setHours(""); onDone(); }}>
      {kind === "leave" ? (
        <SelectField label="Nature" value={sub} onChange={(e) => setSub(e.target.value)}>
          <option value="leave">Congé</option>
          <option value="absence">Absence</option>
          <option value="rest">Repos</option>
        </SelectField>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label={type === "overtime" ? "Jour" : "Du"} type="date" required value={date} error={errors.date} onChange={(e) => setDate(e.target.value)} />
        {type === "overtime" ? (
          <TextField label="Nombre d’heures" inputMode="decimal" required value={hours} error={errors.hours} onChange={(e) => setHours(e.target.value)} hint="12 heures au maximum par demande." />
        ) : (
          <TextField label="Au (inclus)" type="date" optional min={date || undefined} value={end} error={errors.end_date} onChange={(e) => setEnd(e.target.value)} />
        )}
      </div>
      <TextareaField label="Motif" optional rows={3} maxLength={500} value={note} error={errors.note} onChange={(e) => setNote(e.target.value)} />
    </ActionModal>
  );
}

function ReplacementModal({ c, open, shifts, onClose, onDone }: { c: ContractDetail; open: boolean; shifts: ScheduleEvent[]; onClose: () => void; onDone: () => void }) {
  const intent = useIntent("replace");
  const [shift, setShift] = useState("");
  const [worker, setWorker] = useState<PickedWorker | null>(null);
  const [note, setNote] = useState("");
  const body = { shift: Number(shift), replacement_worker: worker?.id, note: note.trim() };
  return (
    <ActionModal open={open} title="Proposer un remplaçant" description="Le remplaçant doit être un professionnel vérifié ; il accepte, puis le donneur d’ordre valide. Le remplaçant déclare lui-même sa présence." confirmLabel="Proposer le remplacement"
      disabled={!shift || !worker} onClose={onClose}
      onSubmit={async () => { await eng.post(`/contracts/${c.id}/replacements/`, body, intent.key(body)); intent.reset(); setNote(""); setShift(""); setWorker(null); onDone(); }}>
      <SelectField label="Intervention à remplacer" required value={shift} onChange={(e) => setShift(e.target.value)}>
        <option value="">Choisir</option>
        {shifts.map((s) => <option key={s.id} value={s.id}>{dateShortFr(s.date)} · {timeFr(s.start_time)} – {timeFr(s.end_time)}</option>)}
      </SelectField>
      <WorkerPicker label="Remplaçant" picked={worker} onPick={setWorker} />
      <TextareaField label="Motif" optional rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
    </ActionModal>
  );
}

function EventRow({ e, c, onDone }: { e: ScheduleEvent; c: ContractDetail; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [declare, setDeclare] = useState(false);
  const [contest, setContest] = useState(false);
  const [start, setStart] = useState("");
  const [stop, setStop] = useState("");
  const [note, setNote] = useState("");
  const intent = useIntent("attend");
  async function go(path: string, body?: unknown) {
    setBusy(true);
    setError("");
    try {
      await eng.post(path, body);
      onDone();
    } catch (err) {
      setError(apiErrorMessage(err, "Action impossible."));
    } finally {
      setBusy(false);
    }
  }
  const tone = e.status === "approved" || e.status === "planned" ? "primary" : e.status === "requested" ? "accent" : "gray";
  const hours = e.start_time ? `${timeFr(e.start_time)} – ${timeFr(e.end_time)}` : e.hours ? `${Number(e.hours)} h` : "";
  return (
    <li className="rounded-panel border border-lineSoft bg-white p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold text-ink">
          {EVENT_KIND_FR[e.kind] ?? e.kind}{hours ? ` · ${hours}` : ""}{e.end_date ? ` · jusqu’au ${dateShortFr(e.end_date)}` : ""}
          {e.kind === "replacement" && e.replacement_worker ? ` · ${e.replacement_worker.name}` : ""}
        </span>
        <span className="flex flex-wrap gap-1.5">
          <Badge tone={tone}>{EVENT_STATUS_FR[e.status] ?? e.status}</Badge>
          {e.attendance_status !== "none" ? <Badge tone={e.attendance_status === "confirmed" ? "success" : e.attendance_status === "disputed" ? "danger" : "info"}>{ATTENDANCE_FR[e.attendance_status]}</Badge> : null}
          {e.booking_id ? <Badge tone="gray">Réservation n° {e.booking_id}</Badge> : null}
        </span>
      </div>
      {e.note ? <p className="mt-1 text-xs text-ash">{e.note}</p> : null}
      {e.actual_start ? <p className="mt-1 text-xs text-ash">Heures déclarées : {timeFr(e.actual_start)} – {timeFr(e.actual_end)}</p> : null}
      {error ? <p role="alert" className="mt-1 text-xs text-dangerInk">{error}</p> : null}
      <div className="mt-2 flex flex-wrap gap-2">
        {e.can_respond ? (
          <>
            <Button size="sm" loading={busy} onClick={() => void go(`/events/${e.id}/respond/`, { approve: true })}>Valider</Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void go(`/events/${e.id}/respond/`, { approve: false })}>Refuser</Button>
          </>
        ) : null}
        {e.can_cancel ? <Button size="sm" variant="outline" loading={busy} onClick={() => void go(`/events/${e.id}/cancel/`)}>Annuler ma demande</Button> : null}
        {e.can_declare_attendance ? <Button size="sm" variant="soft" onClick={() => setDeclare(true)}>Déclarer ma présence</Button> : null}
        {e.can_confirm_attendance ? (
          <>
            <Button size="sm" loading={busy} onClick={() => void go(`/events/${e.id}/attendance/respond/`, { confirm: true })}>Confirmer la présence</Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => setContest(true)}>Contester</Button>
          </>
        ) : null}
      </div>
      <ActionModal open={declare} title="Déclarer ma présence" description="Sans position GPS : vous indiquez seulement vos heures. Le donneur d’ordre confirme ensuite." confirmLabel="Déclarer" onClose={() => setDeclare(false)}
        onSubmit={async () => { const body = start || stop ? { actual_start: start, actual_end: stop } : {}; await eng.post(`/events/${e.id}/attendance/`, body, intent.key({ ...body, e: e.id })); setDeclare(false); onDone(); }}>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Arrivée réelle" type="time" optional value={start} onChange={(ev) => setStart(ev.target.value)} />
          <TextField label="Départ réel" type="time" optional value={stop} onChange={(ev) => setStop(ev.target.value)} />
        </div>
        <p className="text-xs text-ash">Laissez vide pour déclarer les heures prévues au planning.</p>
      </ActionModal>
      <ActionModal open={contest} tone="danger" title="Contester cette présence" confirmLabel="Contester" disabled={note.trim().length < 5} onClose={() => setContest(false)}
        onSubmit={async () => { await eng.post(`/events/${e.id}/attendance/respond/`, { confirm: false, note: note.trim() }); setContest(false); setNote(""); onDone(); }}>
        <TextareaField label="Motif" required rows={3} value={note} onChange={(ev) => setNote(ev.target.value)} />
      </ActionModal>
    </li>
  );
}

export function Planning({ c, onChanged }: { c: ContractDetail; onChanged: () => void }) {
  const [start, setStart] = useState(() => addDays(new Date(), -7));
  const end = addDays(start, 37);
  const { data, error, loading, reload } = useLoad(() => eng.get<{ events: ScheduleEvent[] }>(`/contracts/${c.id}/calendar/?start=${iso(start)}&end=${iso(end)}`), [c.id, iso(start)]);
  const [request, setRequest] = useState<"leave" | "overtime" | null>(null);
  const [replace, setReplace] = useState(false);
  const events = data?.events ?? [];
  const byDay = useMemo(() => {
    const m = new Map<string, ScheduleEvent[]>();
    for (const e of events) m.set(e.date, [...(m.get(e.date) ?? []), e]);
    return Array.from(m.entries());
  }, [events]);
  const upcomingShifts = events.filter((e) => e.kind === "shift" && ["planned", "approved"].includes(e.status) && e.date >= iso(new Date()));
  const live = ["active", "notice", "suspended"].includes(c.status);
  const refresh = () => { void reload(); onChanged(); };
  return (
    <>
      <Alert tone="brand" className="mb-5" icon={<MapPinOff />} title="Aucun suivi de position">
        Le planning vient des conditions du contrat. La présence est <strong>déclarée</strong> par le prestataire puis <strong>confirmée</strong> par le donneur d’ordre : Tratra ne localise jamais le prestataire.
      </Alert>
      <Card padding="md">
        <CardHeader title="Calendrier" icon={<CalendarDays className="h-5 w-5" />}
          action={
            <div className="flex items-center gap-1">
              <Button size="sm" variant="ghost" aria-label="Période précédente" onClick={() => setStart(addDays(start, -30))}><ChevronLeft aria-hidden className="h-4 w-4" /></Button>
              <span className="text-xs font-semibold text-inkSoft">{dateShortFr(iso(start))} → {dateShortFr(iso(end))}</span>
              <Button size="sm" variant="ghost" aria-label="Période suivante" onClick={() => setStart(addDays(start, 30))}><ChevronRight aria-hidden className="h-4 w-4" /></Button>
            </div>
          } />
        {c.actions.includes("request_event") ? (
          <div className="mb-4 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => setRequest("leave")}>Congé, absence ou repos</Button>
            <Button size="sm" variant="outline" onClick={() => setRequest("overtime")}>Heures supplémentaires</Button>
            {c.actions.includes("propose_replacement") ? <Button size="sm" variant="outline" leftIcon={<Repeat aria-hidden className="h-4 w-4" />} onClick={() => setReplace(true)}>Proposer un remplaçant</Button> : null}
          </div>
        ) : null}
        <LoadState loading={loading} error={error} hasData={Boolean(data)} reload={() => void reload()}>
          {byDay.length === 0 ? (
            <EmptyState compact title="Rien de prévu sur cette période" description={live ? (c.schedule.length ? "Le calendrier se génère au fil du temps (60 jours à l’avance)." : "Ce contrat n’a pas de planning fixe : les demandes validées apparaissent ici.") : "Le calendrier est généré une fois le contrat en cours."} />
          ) : (
            <ol className="space-y-4">
              {byDay.map(([day, list]) => (
                <li key={day}>
                  <h3 className="mb-1.5 text-xs font-bold uppercase tracking-wide text-ash">{dateShortFr(day)}</h3>
                  <ul className="space-y-2">{list.map((e) => <EventRow key={e.id} e={e} c={c} onDone={refresh} />)}</ul>
                </li>
              ))}
            </ol>
          )}
        </LoadState>
      </Card>
      <RequestModal c={c} kind={request} onClose={() => setRequest(null)} onDone={() => { setRequest(null); refresh(); }} />
      <ReplacementModal c={c} open={replace} shifts={upcomingShifts} onClose={() => setReplace(false)} onDone={() => { setReplace(false); refresh(); }} />
    </>
  );
}
