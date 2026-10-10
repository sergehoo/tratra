"use client";
import { useState } from "react";
import { FilePenLine } from "lucide-react";
import { Alert, Badge, Button, Card, CardHeader, EmptyState, SelectField, TextField, TextareaField } from "@/components/ds";
import { AMENDMENT_KIND_FR, dateFr, eng, errFields, fcfa, type Amendment, type ContractDetail } from "@/lib/engagements";
import { ActionModal, LoadState, useIntent, useLoad } from "../../../_components/common";
import { ScheduleEditor } from "../../../_components/common";
import { AmendmentBanner, describeChanges } from "./Summary";

const STATUS: Record<string, { label: string; tone: "accent" | "info" | "success" | "gray" | "danger" }> = {
  proposed: { label: "À valider", tone: "accent" }, accepted: { label: "Accepté", tone: "info" }, applied: { label: "En vigueur", tone: "success" },
  rejected: { label: "Refusé", tone: "danger" }, withdrawn: { label: "Retiré", tone: "gray" },
};

export function AmendmentModal({ c, open, onClose, onDone }: { c: ContractDetail; open: boolean; onClose: () => void; onDone: () => void }) {
  const intent = useIntent("amend");
  const kinds = [
    ["change", AMENDMENT_KIND_FR.change], ["suspend", AMENDMENT_KIND_FR.suspend], ["end", AMENDMENT_KIND_FR.end],
    ...(c.status === "notice" ? [["cancel_notice", AMENDMENT_KIND_FR.cancel_notice]] : []), ...(c.end_date ? [["renewal", AMENDMENT_KIND_FR.renewal]] : []),
  ];
  const [kind, setKind] = useState("change");
  const [amount, setAmount] = useState("");
  const [notice, setNotice] = useState("");
  const [payDay, setPayDay] = useState("");
  const [overtime, setOvertime] = useState("");
  const [conditions, setConditions] = useState("");
  const [schedule, setSchedule] = useState(c.schedule);
  const [editSchedule, setEditSchedule] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [endDate, setEndDate] = useState("");
  const [effective, setEffective] = useState("");
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const changes: Record<string, unknown> = {};
  if (kind === "change" || kind === "renewal") {
    if (kind === "change") {
      if (amount.trim()) changes.amount = amount.trim();
      if (notice.trim()) changes.notice_period_days = Number(notice);
      if (payDay.trim()) changes.payment_day = Number(payDay);
      if (overtime.trim()) changes.overtime_hourly_rate = overtime.trim();
      if (conditions.trim()) changes.conditions = conditions.trim();
      if (editSchedule) changes.schedule = schedule;
    }
    if (endDate) changes.end_date = endDate;
  } else if (kind === "suspend") {
    if (from) changes.starts_on = from;
    if (to) changes.ends_on = to;
  } else if (kind === "end") {
    if (endDate) changes.end_date = endDate;
  }
  const body = { kind, changes, reason: reason.trim(), effective_date: effective || undefined, expected_version: c.version };
  const ready = reason.trim().length >= 5 && (kind === "cancel_notice" || Object.keys(changes).length > 0);
  const other = c.my_role === "principal" ? c.worker.name : c.principal.name;
  return (
    <ActionModal open={open} size="lg" title="Proposer un avenant" confirmLabel="Envoyer l’avenant" disabled={!ready} onClose={onClose} onError={(e) => setErrors(errFields(e))}
      description={`${other} doit l’accepter. Un avenant n’est jamais rétroactif : les périodes déjà commencées ne changent pas, et l’historique garde toutes les versions.`}
      onSubmit={async () => { await eng.post(`/contracts/${c.id}/amendments/`, body, intent.key(body)); intent.reset(); setReason(""); onDone(); }}>
      <SelectField label="Nature" value={kind} onChange={(e) => setKind(e.target.value)}>
        {kinds.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </SelectField>
      {kind === "change" ? (
        <div className="space-y-4">
          <p className="text-xs text-ash">Renseignez uniquement ce qui change.</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField label={`Montant (actuel : ${fcfa(c.amount, c.currency)})`} inputMode="decimal" value={amount} error={errors.amount} onChange={(e) => setAmount(e.target.value)} />
            <TextField label={`Préavis en jours (actuel : ${c.notice_period_days})`} inputMode="numeric" value={notice} error={errors.notice_period_days} onChange={(e) => setNotice(e.target.value)} />
            <TextField label="Jour de paiement" inputMode="numeric" value={payDay} error={errors.payment_day} onChange={(e) => setPayDay(e.target.value)} />
            <TextField label="Taux horaire des heures supplémentaires" inputMode="decimal" value={overtime} error={errors.overtime_hourly_rate} onChange={(e) => setOvertime(e.target.value)} />
          </div>
          {c.end_date || endDate ? <TextField label="Nouvelle date de fin" type="date" value={endDate} error={errors.end_date} onChange={(e) => setEndDate(e.target.value)} /> : null}
          <TextareaField label="Conditions particulières (remplacent les actuelles)" rows={3} value={conditions} onChange={(e) => setConditions(e.target.value)} />
          {editSchedule ? <ScheduleEditor value={schedule} onChange={setSchedule} error={errors.schedule} /> : <Button type="button" size="sm" variant="outline" onClick={() => setEditSchedule(true)}>Modifier le planning</Button>}
        </div>
      ) : null}
      {kind === "suspend" ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Début de la suspension" type="date" required value={from} error={errors.starts_on} onChange={(e) => setFrom(e.target.value)} />
          <TextField label="Fin (vide = jusqu’à reprise)" type="date" optional value={to} error={errors.ends_on} onChange={(e) => setTo(e.target.value)} />
        </div>
      ) : null}
      {kind === "end" || kind === "renewal" ? <TextField label={kind === "end" ? "Date de fin convenue" : "Nouvelle date de fin"} type="date" required value={endDate} error={errors.end_date} onChange={(e) => setEndDate(e.target.value)} /> : null}
      {kind !== "suspend" ? <TextField label="Date d’effet" type="date" optional value={effective} error={errors.effective_date} onChange={(e) => setEffective(e.target.value)} hint="Par défaut : aujourd’hui, dès acceptation." /> : null}
      <TextareaField label="Motif" required rows={3} value={reason} error={errors.reason} onChange={(e) => setReason(e.target.value)} />
      {errors.changes ? <p role="alert" className="text-xs font-medium text-dangerInk">{errors.changes}</p> : null}
    </ActionModal>
  );
}

export function Amendments({ c, onChanged, openNew, setOpenNew }: { c: ContractDetail; onChanged: () => void; openNew: boolean; setOpenNew: (v: boolean) => void }) {
  const { data, error, loading, reload } = useLoad(() => eng.get<{ results: Amendment[] }>(`/contracts/${c.id}/amendments/`), [c.id, c.version]);
  const refresh = () => { void reload(); onChanged(); };
  return (
    <>
      <Card padding="md">
        <CardHeader title="Avenants" description="Chaque évolution du contrat est proposée, acceptée par l’autre partie et datée." icon={<FilePenLine className="h-5 w-5" />}
          action={c.actions.includes("propose_amendment") && !c.pending_amendment ? <Button size="sm" onClick={() => setOpenNew(true)}>Proposer un avenant</Button> : undefined} />
        {c.pending_amendment ? <div className="mb-4"><AmendmentBanner a={c.pending_amendment} onChanged={refresh} /></div> : null}
        <LoadState loading={loading} error={error} hasData={Boolean(data)} reload={() => void reload()}>
          {data && data.results.length === 0 ? (
            <EmptyState compact title="Aucun avenant" description="Le contrat est encore dans sa version d’origine." />
          ) : (
            <ul className="space-y-3">
              {data?.results.map((a) => (
                <li key={a.id} className="rounded-panel border border-lineSoft p-3 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-semibold text-ink">{AMENDMENT_KIND_FR[a.kind] ?? a.kind}</span>
                    <Badge tone={STATUS[a.status]?.tone ?? "gray"}>{STATUS[a.status]?.label ?? a.status}</Badge>
                  </div>
                  <p className="mt-1 text-inkSoft">{describeChanges(a)}</p>
                  <p className="mt-1 text-xs text-ash">Proposé par {a.mine ? "vous" : a.proposed_by?.name ?? "—"} · effet le {dateFr(a.effective_date)} · motif : {a.reason}</p>
                </li>
              ))}
            </ul>
          )}
        </LoadState>
      </Card>
      <AmendmentModal key={c.version} c={c} open={openNew} onClose={() => setOpenNew(false)} onDone={() => { setOpenNew(false); refresh(); }} />
      <Alert tone="info" className="mt-4">Les conditions d’origine et chaque version acceptée restent consultables dans « Document et acceptations » (onglet Résumé).</Alert>
    </>
  );
}
