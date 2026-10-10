"use client";
import { useState } from "react";
import { Banknote, FileDown, Paperclip, Scale } from "lucide-react";
import { Alert, Badge, Button, Card, CardHeader, EmptyState, Modal, SelectField, StatusBadge, TextField, TextareaField } from "@/components/ds";
import { apiErrorMessage, privateFileUrl } from "@/lib/api";
import {
  LINE_KIND_FR, PAYMENT_METHOD_FR, dateFr, dateShortFr, eng, errFields, fcfa, type ContractDetail, type Evidence, type Installment, type Line, type Payment,
} from "@/lib/engagements";
import { ActionModal, LoadState, useIntent, useLoad } from "../../../_components/common";

const FILE_HINT = "Image ou PDF, 5 Mo maximum. La pièce reste privée : seules les deux parties la voient.";

function EvidenceLink({ e }: { e: Evidence }) {
  const [error, setError] = useState("");
  return (
    <>
      <button type="button" className="inline-flex items-center gap-1 text-xs font-semibold text-primaryDark underline underline-offset-2"
        onClick={async () => {
          setError("");
          try {
            const url = await privateFileUrl(e.url);
            window.open(url, "_blank", "noopener");
            setTimeout(() => URL.revokeObjectURL(url), 60000);
          } catch (err) {
            setError(apiErrorMessage(err, "Pièce indisponible."));
          }
        }}>
        <Paperclip aria-hidden className="h-3.5 w-3.5" />Voir la pièce jointe
      </button>
      {error ? <span role="alert" className="ml-2 text-xs text-dangerInk">{error}</span> : null}
    </>
  );
}

function DeclarePayment({ i, c, open, onClose, onDone }: { i: Installment; c: ContractDetail; open: boolean; onClose: () => void; onDone: () => void }) {
  const intent = useIntent("pay");
  const today = new Date().toISOString().slice(0, 10);
  // Période en cours : le paiement est une avance plafonnée — le montant proposé respecte déjà ce plafond.
  const limit = i.advance_remaining != null ? Math.min(Number(i.remaining_to_declare), Number(i.advance_remaining)) : Number(i.remaining_to_declare);
  const [amount, setAmount] = useState(limit > 0 ? String(limit) : "");
  const [method, setMethod] = useState("mobile_money");
  const [reference, setReference] = useState("");
  const [paidOn, setPaidOn] = useState(today);
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const fields = { amount: amount.trim(), method, reference: reference.trim(), paid_on: paidOn };
  const other = c.my_role === "principal" ? c.worker.name : c.principal.name;
  return (
    <ActionModal open={open} title="Déclarer un paiement" confirmLabel="Déclarer le paiement" disabled={!amount.trim() || !paidOn} onClose={onClose} onError={(e) => setErrors(errFields(e))}
      description={`Il ne comptera qu’une fois confirmé par ${other} — Tratra n’encaisse ni ne verse rien : déclarez uniquement un paiement réellement effectué.`}
      onSubmit={async () => { await eng.form(`/installments/${i.id}/payments/`, fields, file, intent.key({ ...fields, f: file?.name, s: file?.size })); intent.reset(); onDone(); }}>
      <TextField label="Montant (FCFA)" inputMode="decimal" required value={amount} error={errors.amount} onChange={(e) => setAmount(e.target.value)} hint={i.advance_remaining != null ? `Période en cours : avance limitée à ${fcfa(i.advance_remaining, i.currency)} (règle de la catégorie). Solde de l’échéance : ${fcfa(i.remaining_to_declare, i.currency)}.` : `Solde restant à déclarer : ${fcfa(i.remaining_to_declare, i.currency)}.`} />
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField label="Moyen de paiement" value={method} error={errors.method} onChange={(e) => setMethod(e.target.value)}>
          {Object.entries(PAYMENT_METHOD_FR).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </SelectField>
        <TextField label="Date du paiement" type="date" required max={today} value={paidOn} error={errors.paid_on} onChange={(e) => setPaidOn(e.target.value)} />
      </div>
      <TextField label="Référence" optional value={reference} error={errors.reference} onChange={(e) => setReference(e.target.value)} hint="Numéro de transaction, de virement ou de reçu." />
      <label className="block text-sm font-semibold text-ink">
        Justificatif <span className="font-normal text-ash">(facultatif)</span>
        <input type="file" accept="image/*,application/pdf" className="mt-1.5 block w-full text-sm text-inkSoft file:mr-3 file:rounded-full file:border-0 file:bg-primarySoft file:px-4 file:py-2 file:text-sm file:font-semibold file:text-primaryDark"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <span className="mt-1 block text-xs font-normal text-ash">{FILE_HINT}</span>
      </label>
    </ActionModal>
  );
}

function ProposeLine({ i, open, onClose, onDone }: { i: Installment; open: boolean; onClose: () => void; onDone: () => void }) {
  const intent = useIntent("line");
  const [kind, setKind] = useState("bonus");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const fields = { kind, amount: amount.trim(), description: description.trim() };
  return (
    <ActionModal open={open} title="Proposer un ajustement" description="Prime, frais, retenue ou correction : il ne compte qu’une fois accepté par l’autre partie." confirmLabel="Proposer"
      disabled={!amount.trim() || description.trim().length < 3} onClose={onClose} onError={(e) => setErrors(errFields(e))}
      onSubmit={async () => { await eng.form(`/installments/${i.id}/lines/`, fields, file, intent.key({ ...fields, f: file?.name })); intent.reset(); setAmount(""); setDescription(""); onDone(); }}>
      <SelectField label="Nature" value={kind} onChange={(e) => setKind(e.target.value)}>
        {Object.entries(LINE_KIND_FR).filter(([k]) => k !== "overtime").map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </SelectField>
      <TextField label="Montant (FCFA)" inputMode="decimal" required value={amount} error={errors.amount} onChange={(e) => setAmount(e.target.value)} hint="Une retenue est saisie en positif : elle est déduite." />
      <TextField label="Description" required value={description} error={errors.description} onChange={(e) => setDescription(e.target.value)} maxLength={300} />
      <label className="block text-sm font-semibold text-ink">
        Justificatif <span className="font-normal text-ash">(facultatif)</span>
        <input type="file" accept="image/*,application/pdf" className="mt-1.5 block w-full text-sm text-inkSoft file:mr-3 file:rounded-full file:border-0 file:bg-primarySoft file:px-4 file:py-2 file:text-sm file:font-semibold file:text-primaryDark"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <span className="mt-1 block text-xs font-normal text-ash">{FILE_HINT}</span>
      </label>
    </ActionModal>
  );
}

function Contest({ target, onClose, onDone }: { target: { kind: "payment"; id: number } | null; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  return (
    <ActionModal open={Boolean(target)} tone="danger" title="Contester ce paiement" description="Expliquez pourquoi il est inexact : l’autre partie en est informée. Un désaccord persistant peut être signalé à Tratra." confirmLabel="Contester"
      disabled={reason.trim().length < 5} onClose={onClose}
      onSubmit={async () => { await eng.post(`/payments/${target?.id}/respond/`, { confirm: false, reason: reason.trim() }); setReason(""); onDone(); }}>
      <TextareaField label="Motif" required rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
    </ActionModal>
  );
}

function Waive({ i, open, onClose, onDone }: { i: Installment; open: boolean; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  return (
    <ActionModal open={open} tone="danger" title="Abandonner le solde ?" description={`Vous renoncez au solde de ${fcfa(i.balance, i.currency)} de l’échéance ${i.number}. C’est définitif et seul le prestataire peut le décider.`} confirmLabel="Abandonner le solde"
      disabled={reason.trim().length < 5} onClose={onClose} onSubmit={async () => { await eng.post(`/installments/${i.id}/waive/`, { reason: reason.trim() }); setReason(""); onDone(); }}>
      <TextareaField label="Motif" required rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
    </ActionModal>
  );
}

function LineRow({ l, onDone }: { l: Line; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function answer(accept: boolean) {
    setBusy(true);
    setError("");
    try {
      await eng.post(`/lines/${l.id}/respond/`, { accept });
      onDone();
    } catch (e) {
      setError(apiErrorMessage(e, "Action impossible."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <li className="rounded-panel bg-canvas p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold text-ink">{LINE_KIND_FR[l.kind] ?? l.kind} · {fcfa(l.amount)}</span>
        <Badge tone={l.status === "accepted" ? "success" : l.status === "proposed" ? "accent" : "gray"}>{l.status === "accepted" ? "Accepté" : l.status === "proposed" ? "À valider" : "Refusé"}</Badge>
      </div>
      <p className="mt-1 text-inkSoft">{l.description}</p>
      {l.evidence ? <div className="mt-1"><EvidenceLink e={l.evidence} /></div> : null}
      {l.can_respond ? (
        <div className="mt-2 flex gap-2">
          <Button size="sm" loading={busy} onClick={() => void answer(true)}>Accepter</Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void answer(false)}>Refuser</Button>
        </div>
      ) : null}
      {error ? <p role="alert" className="mt-1 text-xs text-dangerInk">{error}</p> : null}
    </li>
  );
}

function PaymentRow({ p, c, onDone, onContest }: { p: Payment; c: ContractDetail; onDone: () => void; onContest: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const tone = p.status === "confirmed" ? "success" : p.status === "declared" ? "accent" : "danger";
  const label = p.status === "confirmed" ? "Confirmé" : p.status === "declared" ? "À confirmer" : "Contesté";
  return (
    <li className="rounded-panel bg-canvas p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold text-ink">{fcfa(p.amount, c.currency)} · {PAYMENT_METHOD_FR[p.method] ?? p.method}{p.is_advance ? " · avance" : ""}</span>
        <Badge tone={tone}>{label}</Badge>
      </div>
      <p className="mt-1 text-xs text-ash">Déclaré par {p.mine ? "vous" : p.declared_by_role === "principal" ? c.principal.name : c.worker.name} · versé le {dateFr(p.paid_on)}{p.reference ? ` · réf. ${p.reference}` : ""}</p>
      {p.status === "confirmed" && p.trust?.note ? <p className="mt-1 text-xs text-ash">{p.trust.note}</p> : null}
      {p.status === "rejected" && p.rejection_reason ? <p className="mt-1 text-xs text-dangerInk">Motif de contestation : {p.rejection_reason}</p> : null}
      {p.evidence ? <div className="mt-1"><EvidenceLink e={p.evidence} /></div> : null}
      {p.status === "declared" && p.mine ? <p className="mt-1 text-xs text-ash">En attente de confirmation de l’autre partie : un paiement ne se confirme jamais soi-même.</p> : null}
      {p.can_respond ? (
        <div className="mt-2 flex flex-wrap gap-2">
          <Button size="sm" loading={busy} onClick={async () => { setBusy(true); setError(""); try { await eng.post(`/payments/${p.id}/respond/`, { confirm: true }); onDone(); } catch (e) { setError(apiErrorMessage(e, "Confirmation impossible.")); } finally { setBusy(false); } }}>Je confirme avoir {c.my_role === "worker" ? "reçu" : "payé"} ce montant</Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={onContest}>Contester</Button>
        </div>
      ) : null}
      {error ? <p role="alert" className="mt-1 text-xs text-dangerInk">{error}</p> : null}
    </li>
  );
}

function InstallmentModal({ id, c, onClose, onChanged }: { id: number | null; c: ContractDetail; onClose: () => void; onChanged: () => void }) {
  const { data: i, error, loading, reload } = useLoad(async () => (id ? eng.get<Installment>(`/installments/${id}/`) : null), [id]);
  const [declare, setDeclare] = useState(false);
  const [line, setLine] = useState(false);
  const [waive, setWaive] = useState(false);
  const [contest, setContest] = useState<{ kind: "payment"; id: number } | null>(null);
  const refresh = () => { void reload(); onChanged(); };
  const open = id !== null && !declare && !line && !waive && !contest;
  const canMoney = i && !["waived", "cancelled", "paid"].includes(i.status);
  return (
    <>
      <Modal open={open} onClose={onClose} size="lg" title={i ? `Échéance ${i.number} · ${dateShortFr(i.period_start)} → ${dateShortFr(i.period_end)}` : "Échéance"}>
        <LoadState loading={loading} error={error} hasData={Boolean(i)} reload={() => void reload()}>
          {i ? (
            <div className="space-y-5">
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded-panel bg-canvas p-3"><p className="text-xs font-semibold uppercase text-ash">Montant dû</p><p className="mt-1 font-display text-lg font-bold text-ink">{i.computed ? fcfa(i.total, i.currency) : "Calculé fin de période"}</p></div>
                <div className="rounded-panel bg-canvas p-3"><p className="text-xs font-semibold uppercase text-ash">Confirmé</p><p className="mt-1 font-display text-lg font-bold text-ink">{fcfa(i.confirmed, i.currency)}</p></div>
                <div className="rounded-panel bg-canvas p-3"><p className="text-xs font-semibold uppercase text-ash">Solde</p><p className="mt-1 font-display text-lg font-bold text-ink">{i.computed ? fcfa(i.balance, i.currency) : "—"}</p></div>
              </div>
              <p className="text-sm text-inkSoft">Échéance le {dateFr(i.due_date)} <StatusBadge kind="installment" status={i.status} className="ml-1" />{Number(i.declared) > 0 ? ` · ${fcfa(i.declared, i.currency)} déclaré(s), en attente de confirmation` : ""}</p>
              {!i.computed ? <Alert tone="info">Rémunération {c.period === "hourly" ? "à l’heure" : "à l’intervention"} : le montant est calculé à la fin de la période à partir des présences confirmées par le donneur d’ordre.</Alert> : null}
              {i.note ? <p className="text-xs text-ash">{i.note}</p> : null}
              {Number(i.platform_fee) > 0 ? <p className="text-xs text-ash">Commission Tratra : {fcfa(i.platform_fee, i.currency)}, à la charge du {i.platform_fee_payer === "worker" ? "prestataire" : "donneur d’ordre"} — distincte de la rémunération.</p> : null}

              <div>
                <h3 className="mb-2 text-sm font-bold text-ink">Paiements</h3>
                {i.payments && i.payments.length ? <ul className="space-y-2">{i.payments.map((p) => <PaymentRow key={p.id} p={p} c={c} onDone={refresh} onContest={() => setContest({ kind: "payment", id: p.id })} />)}</ul> : <p className="text-sm text-ash">Aucun paiement déclaré.</p>}
              </div>
              <div>
                <h3 className="mb-2 text-sm font-bold text-ink">Ajustements</h3>
                {i.lines && i.lines.length ? <ul className="space-y-2">{i.lines.map((l) => <LineRow key={l.id} l={l} onDone={refresh} />)}</ul> : <p className="text-sm text-ash">Aucun ajustement (prime, frais, retenue, heures supplémentaires).</p>}
              </div>
              {canMoney ? (
                <div className="flex flex-wrap gap-2 border-t border-lineSoft pt-4">
                  {i.computed && Number(i.remaining_to_declare) > 0 ? <Button leftIcon={<Banknote aria-hidden className="h-4 w-4" />} onClick={() => setDeclare(true)}>Déclarer un paiement</Button> : null}
                  <Button variant="outline" onClick={() => setLine(true)}>Proposer un ajustement</Button>
                  {i.can_waive ? <Button variant="ghost" onClick={() => setWaive(true)}>Abandonner le solde</Button> : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </LoadState>
      </Modal>
      {i ? (
        <>
          <DeclarePayment key={`d${i.id}-${i.remaining_to_declare}`} i={i} c={c} open={declare} onClose={() => setDeclare(false)} onDone={() => { setDeclare(false); refresh(); }} />
          <ProposeLine i={i} open={line} onClose={() => setLine(false)} onDone={() => { setLine(false); refresh(); }} />
          <Waive i={i} open={waive} onClose={() => setWaive(false)} onDone={() => { setWaive(false); refresh(); }} />
        </>
      ) : null}
      <Contest target={contest} onClose={() => setContest(null)} onDone={() => { setContest(null); refresh(); }} />
    </>
  );
}

export function Pay({ c, onChanged, initialOpen }: { c: ContractDetail; onChanged: () => void; initialOpen?: number | null }) {
  const { data, error, loading, reload } = useLoad(() => eng.get<{ results: Installment[] }>(`/contracts/${c.id}/installments/`), [c.id, c.version]);
  const [open, setOpen] = useState<number | null>(initialOpen ?? null);
  const rows = data?.results ?? [];
  return (
    <>
      <Alert tone="brand" className="mb-5" icon={<Scale />} title="Comment fonctionne la rémunération">
        Les échéances sont générées automatiquement. Tratra ne verse ni n’encaisse rien : un paiement est <strong>déclaré</strong> par une partie puis <strong>confirmé</strong> par l’autre. Aucun montant légal (cotisations, impôts) n’est calculé.
      </Alert>
      <LoadState loading={loading} error={error} hasData={Boolean(data)} reload={() => void reload()}>
        {rows.length === 0 ? (
          <EmptyState icon={<Banknote aria-hidden />} title="Aucune échéance pour le moment" description="Les échéances sont créées à l’acceptation du contrat, période après période." />
        ) : (
          <Card padding="none">
            <CardHeader className="p-5 pb-0" title="Échéances" description="Touchez une échéance pour voir le détail, déclarer ou confirmer un paiement." />
            <ul className="divide-y divide-lineSoft">
              {rows.map((i) => (
                <li key={i.id}>
                  <button type="button" onClick={() => setOpen(i.id)} className="flex w-full flex-wrap items-center justify-between gap-x-4 gap-y-1 px-5 py-3.5 text-left hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary">
                    <span className="min-w-0">
                      <span className="block text-sm font-semibold text-ink">Échéance {i.number} · {dateShortFr(i.period_start)} → {dateShortFr(i.period_end)}</span>
                      <span className="block text-xs text-ash">À régler le {dateFr(i.due_date)}</span>
                    </span>
                    <span className="flex items-center gap-3">
                      <span className="text-sm font-semibold text-ink">{i.computed ? fcfa(i.total, i.currency) : "—"}</span>
                      <StatusBadge kind="installment" status={i.status} />
                      {Number(i.declared) > 0 ? <Badge tone="accent">À confirmer</Badge> : null}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </LoadState>
      <InstallmentModal id={open} c={c} onClose={() => setOpen(null)} onChanged={() => { void reload(); onChanged(); }} />
      <p className="mt-4 flex items-center gap-1.5 text-xs text-ash"><FileDown aria-hidden className="h-3.5 w-3.5" />Reçus : joignez un justificatif à chaque paiement déclaré ; il reste privé entre les deux parties.</p>
    </>
  );
}
