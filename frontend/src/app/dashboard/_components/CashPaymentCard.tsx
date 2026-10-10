"use client";
import { useCallback, useEffect, useState } from "react";
import { Banknote, Paperclip } from "lucide-react";
import { Alert, Badge, Button, Card, CardHeader, SkeletonPage, TextField, TextareaField } from "@/components/ds";
import { apiErrorMessage, privateFileUrl } from "@/lib/api";
import { CASH_STATE_FR, CASH_STATUS_FR, cashApi, type BookingPayment, type CashDeclaration, type CashSummary } from "@/lib/cash";
import { dateFr, errFields, fcfa } from "@/lib/engagements";
import { ActionModal, useIntent } from "../engagements/_components/common";

const FILE_HINT = "Image ou PDF, 5 Mo maximum. La pièce reste privée : seules les deux parties la voient.";
const TONE: Record<CashDeclaration["status"], "accent" | "success" | "danger"> = { declared: "accent", confirmed: "success", rejected: "danger" };

function ReceiptLink({ url }: { url: string }) {
  const [error, setError] = useState("");
  return (
    <>
      <button type="button" className="inline-flex items-center gap-1 text-xs font-semibold text-primaryDark underline underline-offset-2"
        onClick={async () => {
          setError("");
          try {
            const blob = await privateFileUrl(url);
            window.open(blob, "_blank", "noopener");
            setTimeout(() => URL.revokeObjectURL(blob), 60000);
          } catch (e) {
            setError(apiErrorMessage(e, "Pièce indisponible."));
          }
        }}>
        <Paperclip aria-hidden className="h-3.5 w-3.5" />Voir le justificatif
      </button>
      {error ? <span role="alert" className="ml-2 text-xs text-dangerInk">{error}</span> : null}
    </>
  );
}

function DeclareCash({ bookingId, cash, open, onClose, onDone }: { bookingId: number; cash: CashSummary; open: boolean; onClose: () => void; onDone: (c: CashSummary) => void }) {
  const intent = useIntent("cash");
  const today = new Date().toISOString().slice(0, 10);
  const [amount, setAmount] = useState(cash.remaining ?? "");
  const [paidOn, setPaidOn] = useState(today);
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  useEffect(() => {
    if (open) {
      setAmount(cash.remaining ?? "");
      setErrors({});
    }
  }, [open, cash.remaining]);
  const other = cash.my_role === "client" ? "l’artisan" : "le client";
  const fields = { amount: String(amount).trim(), paid_on: paidOn, note: note.trim() };
  return (
    <ActionModal open={open} title={cash.my_role === "client" ? "Déclarer un paiement en espèces remis" : "Déclarer des espèces reçues"} confirmLabel="Déclarer" disabled={!String(amount).trim() || !paidOn}
      onClose={onClose} onError={(e) => setErrors(errFields(e))}
      description={`Cette déclaration ne comptera qu’une fois confirmée par ${other}. Les espèces ne passent pas par Tratra : déclarez uniquement un montant réellement remis en main propre.`}
      onSubmit={async () => {
        const r = await cashApi.declare(bookingId, fields, file, intent.key({ ...fields, f: file?.name, s: file?.size }));
        intent.reset();
        setFile(null);
        setNote("");
        onDone(r.cash);
      }}>
      <TextField label="Montant (FCFA)" inputMode="decimal" required value={amount} error={errors.amount} onChange={(e) => setAmount(e.target.value)}
        hint={cash.remaining != null ? `Solde restant à régler : ${fcfa(cash.remaining, cash.currency)}.` : "Indiquez le montant réellement remis."} />
      <TextField label="Date de la remise" type="date" required max={today} value={paidOn} error={errors.paid_on} onChange={(e) => setPaidOn(e.target.value)} />
      <TextareaField label="Précision" optional maxLength={200} value={note} error={errors.note} onChange={(e) => setNote(e.target.value)} hint="Ex. remis à la fin de l’intervention." />
      <label className="block text-sm font-semibold text-ink">
        Justificatif <span className="font-normal text-ash">(facultatif)</span>
        <input type="file" accept="image/*,application/pdf" className="mt-1.5 block w-full text-sm text-inkSoft file:mr-3 file:rounded-full file:border-0 file:bg-primarySoft file:px-4 file:py-2 file:text-sm file:font-semibold file:text-primaryDark"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        {errors.receipt ? <span role="alert" className="mt-1 block text-xs font-normal text-dangerInk">{errors.receipt}</span> : <span className="mt-1 block text-xs font-normal text-ash">{FILE_HINT}</span>}
      </label>
    </ActionModal>
  );
}

function ContestCash({ decl, open, onClose, onDone }: { decl: CashDeclaration | null; open: boolean; onClose: () => void; onDone: (c: CashSummary) => void }) {
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  useEffect(() => {
    if (open) {
      setReason("");
      setErrors({});
    }
  }, [open]);
  return (
    <ActionModal open={open} title="Contester cette déclaration" confirmLabel="Contester" tone="danger" disabled={reason.trim().length < 5} onClose={onClose} onError={(e) => setErrors(errFields(e))}
      description="Le motif est transmis à l’autre partie et conservé dans l’historique. Vous pourrez ensuite déclarer le montant exact."
      onSubmit={async () => {
        if (!decl) return;
        const r = await cashApi.respond(decl.id, false, reason.trim());
        onDone(r.cash);
      }}>
      <TextareaField label="Motif de la contestation" required maxLength={500} value={reason} error={errors.reason} onChange={(e) => setReason(e.target.value)} hint="5 caractères au minimum." />
    </ActionModal>
  );
}

function Row({ d, currency, onConfirmed, onContest }: { d: CashDeclaration; currency: string; onConfirmed: (c: CashSummary) => void; onContest: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const who = d.mine ? "vous" : d.declared_by_role === "artisan" ? "l’artisan" : "le client";
  return (
    <li className="rounded-panel bg-canvas p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold text-ink">{fcfa(d.amount, currency)}</span>
        <Badge tone={TONE[d.status]}>{CASH_STATUS_FR[d.status]}</Badge>
      </div>
      <p className="mt-1 text-xs text-ash">Déclaré par {who} · remis le {dateFr(d.paid_on)}{d.note ? ` · ${d.note}` : ""}</p>
      {d.status === "rejected" && d.rejection_reason ? <p className="mt-1 text-xs text-dangerInk">Motif de contestation : {d.rejection_reason}</p> : null}
      {d.receipt ? <div className="mt-1"><ReceiptLink url={d.receipt.url} /></div> : null}
      {d.status === "declared" && d.mine ? <p className="mt-1 text-xs text-ash">En attente de confirmation de l’autre partie : un paiement ne se confirme jamais soi-même.</p> : null}
      {d.can_respond ? (
        <div className="mt-2 flex flex-wrap gap-2">
          <Button size="sm" loading={busy} onClick={async () => { setBusy(true); setError(""); try { onConfirmed((await cashApi.respond(d.id, true)).cash); } catch (e) { setError(apiErrorMessage(e, "Confirmation impossible.")); } finally { setBusy(false); } }}>
            Je confirme avoir {d.declared_by_role === "artisan" ? "payé" : "reçu"} ce montant
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={onContest}>Contester</Button>
        </div>
      ) : null}
      {error ? <p role="alert" className="mt-1 text-xs text-dangerInk">{error}</p> : null}
    </li>
  );
}

/** Carte « Paiement » d'une réservation : état, historique, déclaration et confirmation des espèces. Rien n'est présenté comme vérifié par un prestataire. */
export function CashPaymentCard({ bookingId, bookingStatus }: { bookingId: number; bookingStatus: string }) {
  const [data, setData] = useState<BookingPayment | null>(null);
  const [cash, setCash] = useState<CashSummary | null>(null);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [declare, setDeclare] = useState(false);
  const [contest, setContest] = useState<CashDeclaration | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await cashApi.get(bookingId);
      setData(r);
      setCash(r.cash);
      setError("");
    } catch (e) {
      setError(apiErrorMessage(e, "Le paiement ne peut pas être chargé pour le moment."));
    } finally {
      setLoaded(true);
    }
  }, [bookingId]);

  // Recharge quand la prestation change d'état (démarrée, terminée) : c'est ce qui ouvre ou ferme la déclaration.
  useEffect(() => {
    void load();
  }, [load, bookingStatus]);

  if (!loaded) return <SkeletonPage />;
  if (error && !data) return <Alert tone="danger">{error}</Alert>;
  // Règlement par un prestataire (Orange Money, MTN, carte) : pas de carte « espèces ».
  if (!cash) return null;
  const waitingForMe = cash.history.some((d) => d.can_respond);
  return (
    <Card>
      <CardHeader title="Paiement en espèces" description="Déclaré par une partie, confirmé par l’autre." icon={<Banknote className="h-5 w-5" />} />
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={cash.state === "paid" ? "success" : cash.state === "contested" ? "danger" : cash.state === "none" ? "gray" : "accent"}>{CASH_STATE_FR[cash.state]}</Badge>
        {cash.due ? <span className="text-sm text-inkSoft">Convenu : <strong>{fcfa(cash.due, cash.currency)}</strong> · confirmé : <strong>{fcfa(cash.confirmed, cash.currency)}</strong></span> : null}
      </div>
      {cash.history.length ? (
        <ul className="mt-3 space-y-2" aria-label="Historique des déclarations">
          {cash.history.map((d) => <Row key={d.id} d={d} currency={cash.currency} onConfirmed={setCash} onContest={() => setContest(d)} />)}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-ash">
          {["in_progress", "completed"].includes(bookingStatus) ? "Aucun paiement déclaré pour l’instant." : "Le paiement se déclare une fois la prestation commencée."}
        </p>
      )}
      {waitingForMe ? <Alert tone="info" className="mt-3">Une déclaration attend votre confirmation.</Alert> : null}
      {cash.can_declare ? (
        <div className="mt-4"><Button leftIcon={<Banknote aria-hidden className="h-4 w-4" />} onClick={() => setDeclare(true)}>Déclarer un paiement en espèces</Button></div>
      ) : null}
      <p className="mt-4 text-xs text-ash">{cash.note}</p>
      <DeclareCash bookingId={bookingId} cash={cash} open={declare} onClose={() => setDeclare(false)} onDone={(c) => { setCash(c); setDeclare(false); }} />
      <ContestCash decl={contest} open={Boolean(contest)} onClose={() => setContest(null)} onDone={(c) => { setCash(c); setContest(null); }} />
    </Card>
  );
}
