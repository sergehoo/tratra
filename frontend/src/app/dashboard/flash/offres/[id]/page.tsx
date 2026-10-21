"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Alert, Badge, Button, Card, PageHeader, SelectField, SkeletonList, TextField } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api";
import { acceptOffer, declineOffer, getOffer, quoteOffer, type FlashOffer } from "@/lib/flash";

/* Proposition Tratra Flash (professionnel, site) : mêmes actions que l'alerte de l'application — accepter (prix ferme), proposer un devis,
   refuser sans conséquence. Avant acceptation : ni nom, ni téléphone, ni adresse du client. */
export default function OfferPage() {
  const { id } = useParams<{ id: string }>();
  const oid = Number(id);
  const [o, setO] = useState<FlashOffer | null>(null);
  const [left, setLeft] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [amount, setAmount] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try { const d = await getOffer(oid); setO(d); setLeft(d.seconds_left); } catch (e) { setError(apiErrorMessage(e, "Cette proposition n’existe pas sur ce compte.")); }
  }, [oid]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!o || o.status !== "pending") return;
    const t = setInterval(() => setLeft((s) => (s > 0 ? s - 1 : 0)), 1000);
    return () => clearInterval(t);
  }, [o]);

  async function run(call: () => Promise<FlashOffer>) {
    setBusy(true);
    setError("");
    try { setO(await call()); } catch (e) { setError(apiErrorMessage(e, "Action impossible.")); void load(); } finally { setBusy(false); }
  }

  if (!o) return error ? <Alert tone="danger">{error}</Alert> : <SkeletonList />;
  const pending = o.status === "pending" && left > 0;
  const quote = o.mode === "quote";
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <PageHeader title={o.category} description={`${o.zone} · ${o.when_label}${o.distance_km ? ` · ${o.distance_km.replace(".", ",")} km` : ""}`} />
      <Card variant="night" className="space-y-2 text-white">
        <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-accent">{o.direct === "1" ? "Un client vous a choisi" : "Nouvelle mission"}</p>
        <p className="font-display text-3xl font-extrabold">{quote ? "Sur devis" : o.amount_label}</p>
        {pending ? <Badge tone="accent">{Math.floor(left / 60)} min {String(left % 60).padStart(2, "0")} pour répondre</Badge> : <Badge tone="gray">{o.status_label}</Badge>}
      </Card>
      {o.description ? <Card><p className="text-sm text-inkSoft">{o.description}</p></Card> : null}
      <Card><p className="text-sm text-inkSoft">Réputation du client : {o.client_reputation.average != null ? `${String(o.client_reputation.average).replace(".", ",")}/5 sur ${o.client_reputation.count} évaluation(s)` : o.client_reputation.count ? "pas encore assez d’évaluations" : "nouveau client"}</p></Card>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {o.status === "accepted" ? (
        <Alert tone="success">Mission confirmée. Client : {o.client_name} — Adresse : {o.address}. {o.booking ? <Link className="font-semibold underline" href={`/dashboard/provider/missions/${o.booking}`}>Ouvrir la mission</Link> : null}</Alert>
      ) : null}
      {o.status === "declined" ? <Alert tone="info">Refus enregistré. Aucune conséquence sur votre réputation.</Alert> : null}
      {o.status === "quoted" ? <Alert tone="success">Devis envoyé. Le client choisit : vous serez prévenu.</Alert> : null}
      {pending ? (
        <Card className="space-y-3">
          {quote ? (
            <>
              <TextField label="Votre prix (FCFA, déplacement compris)" inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value)} />
              <TextField label="Message au client" optional value={message} onChange={(e) => setMessage(e.target.value)} maxLength={500} />
              <Button block loading={busy} onClick={() => void run(() => quoteOffer(oid, Number(amount.replace(/\D/g, "")), message))}>Envoyer le devis</Button>
            </>
          ) : (
            <Button block size="lg" loading={busy} onClick={() => void run(() => acceptOffer(oid))}>Accepter la mission</Button>
          )}
          <SelectField label="Motif du refus (facultatif)" value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="">Sans motif</option>
            {o.decline_reasons.map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}
          </SelectField>
          <Button block variant="outline" loading={busy} onClick={() => void run(() => declineOffer(oid, reason))}>Refuser (sans conséquence)</Button>
        </Card>
      ) : null}
    </div>
  );
}
