"use client";
import { useState } from "react";
import { ArrowDownToLine, Wallet } from "lucide-react";
import { apiErrorMessage, post } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard";
import { formatFCFA } from "@/lib/format";
import { useData } from "@/lib/useData";
import type { Paginated } from "@/lib/types";
import {
  Alert, Button, Card, ConfirmDialog, EmptyState, PageHeader, SkeletonList, StatusBadge, Tabs, TextField,
} from "@/components/ds";
import { formatDateTimeShort } from "../_components/dates";

interface Payment {
  id: number;
  amount: string;
  status: string;
  method: string | null;
  payment_date: string | null;
  created_at: string;
  booking_detail?: { service_title?: string | null; service_detail?: { title?: string } | null } | null;
}
interface Payout { id: number; amount: string; status: string; requested_at: string; processed_at: string | null }

function paymentTitle(p: Payment): string {
  return p.booking_detail?.service_detail?.title || p.booking_detail?.service_title || `Réservation n° ${p.id}`;
}

export default function WalletPage() {
  const dash = useDashboard();
  const isProvider = dash.data?.capabilities.provider ?? false;
  const payments = useData<Paginated<Payment>>("/payments/?ordering=-created_at", "Vos paiements ne peuvent pas être chargés.");
  const payouts = useData<Paginated<Payout>>(isProvider ? "/payouts/" : null, "Vos retraits ne peuvent pas être chargés.");
  const available = useData<{ available: string }>(isProvider ? "/payouts/available/" : null);
  const [tab, setTab] = useState<"payments" | "payouts">("payments");
  const [amount, setAmount] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [done, setDone] = useState("");

  const availableValue = Number(available.data?.available ?? 0);
  const requested = Number(amount.replace(/\s/g, "").replace(",", "."));
  const amountError =
    amount && (!Number.isFinite(requested) || requested <= 0)
      ? "Saisissez un montant valide."
      : amount && requested > availableValue
        ? "Ce montant dépasse vos gains disponibles."
        : "";
  const canRequest = Boolean(amount) && !amountError;

  async function requestPayout() {
    setBusy(true);
    setFailure("");
    try {
      await post("/payouts/", { amount: String(requested) });
      setConfirm(false);
      setAmount("");
      setDone("Votre demande de retrait a bien été enregistrée.");
      setTab("payouts");
      await Promise.all([payouts.reload(), available.reload(), dash.reload()]);
    } catch (e) {
      setConfirm(false);
      setFailure(apiErrorMessage(e, "La demande de retrait a échoué."));
    } finally {
      setBusy(false);
    }
  }

  const tabs = [
    { id: "payments" as const, label: "Paiements", count: payments.data?.count },
    ...(isProvider ? [{ id: "payouts" as const, label: "Retraits", count: payouts.data?.count }] : []),
  ];

  return (
    <>
      <PageHeader title="Portefeuille" description="Vos paiements de prestations et, si vous êtes artisan, vos gains et retraits." />

      {isProvider ? (
        <Card variant="night" radius="panel" className="mb-6 grid gap-5 sm:grid-cols-[1fr_auto] sm:items-end">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-white/60">Gains disponibles</p>
            <p className="mt-1 font-display text-3xl font-extrabold text-white">
              {available.loading ? "…" : formatFCFA(availableValue) ?? "0 FCFA"}
            </p>
            <p className="mt-1 text-xs text-white/60">Montants versés après la fin des prestations, hors retraits déjà demandés.</p>
          </div>
          <div className="flex flex-col gap-2 sm:w-72">
            <TextField
              label={<span className="text-white">Montant à retirer (FCFA)</span>}
              inputMode="numeric"
              value={amount}
              onChange={(e) => { setAmount(e.target.value); setDone(""); }}
              error={amountError || undefined}
              disabled={availableValue <= 0}
              placeholder={availableValue > 0 ? `Max. ${formatFCFA(availableValue)}` : "Aucun gain disponible"}
            />
            <Button variant="accent" disabled={!canRequest} leftIcon={<ArrowDownToLine aria-hidden className="h-4 w-4" />} onClick={() => setConfirm(true)}>
              Demander un retrait
            </Button>
          </div>
        </Card>
      ) : null}

      {done ? <Alert tone="success" className="mb-4">{done}</Alert> : null}
      {failure ? <Alert tone="danger" className="mb-4">{failure}</Alert> : null}

      <Tabs ariaLabel="Portefeuille" value={tab} onChange={setTab} items={tabs} className="mb-5" />

      {tab === "payments" ? (
        payments.loading ? (
          <SkeletonList count={3} />
        ) : payments.error ? (
          <Alert tone="danger" title="Paiements indisponibles" action={<Button size="sm" variant="outline" onClick={() => void payments.reload()}>Réessayer</Button>}>{payments.error}</Alert>
        ) : (payments.data?.results ?? []).length === 0 ? (
          <EmptyState icon={<Wallet />} title="Aucun paiement" description="Vos paiements apparaîtront ici dès votre première réservation payée." />
        ) : (
          <ul className="grid grid-cols-1 gap-3">
            {payments.data!.results.map((p) => (
              <li key={p.id}>
                <Card padding="sm" radius="panel" className="flex flex-wrap items-center gap-3 sm:flex-nowrap">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-display text-[15px] font-bold text-ink">{paymentTitle(p)}</p>
                    <p className="text-xs text-ash">{formatDateTimeShort(p.payment_date ?? p.created_at)}{p.method ? ` · ${p.method}` : ""}</p>
                  </div>
                  <p className="font-display text-base font-extrabold text-ink">{formatFCFA(p.amount) ?? "0 FCFA"}</p>
                  <StatusBadge kind="payment" status={p.status} />
                </Card>
              </li>
            ))}
          </ul>
        )
      ) : payouts.loading ? (
        <SkeletonList count={3} />
      ) : payouts.error ? (
        <Alert tone="danger" title="Retraits indisponibles" action={<Button size="sm" variant="outline" onClick={() => void payouts.reload()}>Réessayer</Button>}>{payouts.error}</Alert>
      ) : (payouts.data?.results ?? []).length === 0 ? (
        <EmptyState icon={<ArrowDownToLine />} title="Aucun retrait" description="Vos demandes de retrait et leur traitement apparaîtront ici." />
      ) : (
        <ul className="grid grid-cols-1 gap-3">
          {payouts.data!.results.map((p) => (
            <li key={p.id}>
              <Card padding="sm" radius="panel" className="flex flex-wrap items-center gap-3 sm:flex-nowrap">
                <div className="min-w-0 flex-1">
                  <p className="font-display text-[15px] font-bold text-ink">Retrait n° {p.id}</p>
                  <p className="text-xs text-ash">
                    Demandé le {formatDateTimeShort(p.requested_at)}{p.processed_at ? ` · traité le ${formatDateTimeShort(p.processed_at)}` : ""}
                  </p>
                </div>
                <p className="font-display text-base font-extrabold text-ink">{formatFCFA(p.amount) ?? "0 FCFA"}</p>
                <StatusBadge kind="payout" status={p.status} />
              </Card>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={confirm}
        onClose={() => setConfirm(false)}
        onConfirm={() => void requestPayout()}
        loading={busy}
        title="Confirmer le retrait"
        description={`Vous demandez le retrait de ${formatFCFA(requested) ?? ""}. Cette demande sera traitée par l’équipe Tratra.`}
        confirmLabel="Confirmer"
        cancelLabel="Annuler"
      />
    </>
  );
}
