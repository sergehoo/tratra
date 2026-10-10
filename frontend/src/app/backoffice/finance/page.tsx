"use client";
import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Modal, PageHeader, SkeletonStats, Stat, Tabs, type Column } from "@/components/ds";
import { bo, boError, moneyLabel } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useBoList, useDebounced } from "@/lib/useBoList";
import { DateRange, FilterBar, FilterSelect, KV, ListView, ReasonModal, SearchBox, Section, STATUS_FR, Tag, dt, useNotice, useTabParam } from "../_components/ui";

interface Summary { gmv: string; commission_earned: string; commission_in_escrow: string; escrow_held: string; refunded: string; payouts: Record<string, { count: number; amount: string }>; by_status: Record<string, { count: number; amount: string }> }
interface Payment { id: number; booking_id: number; client: string; artisan: string; amount: string; platform_fee: string; net: string; method: string; status: string; refunded_amount: string; created_at: string; payment_date: string | null }
interface PaymentDetail extends Payment { booking_status: string; discount: string; can_refund: boolean; logs: { previous_status: string; new_status: string; at: string; notes: string }[]; history: { action: string; at: string; by: string; reason: string }[] }
interface Payout { id: number; artisan_id: number; artisan: string; amount: string; status: string; requested_at: string; processed_at: string | null; notes: string }
interface Invoice { id: number; number: string; booking_id: number; client: string; artisan: string; amount: string; fee: string; total: string }

const METHOD_FR: Record<string, string> = { card: "Carte", transfer: "Virement", cash: "Espèces", check: "Chèque", om: "Orange Money", mtn: "MTN MoMo", moov: "Moov Money", wave: "Wave" };

function PaymentPanel({ id, onClose, onChanged }: { id: number | null; onClose: () => void; onChanged: () => void }) {
  const [d, setD] = useState<PaymentDetail | null>(null);
  const [error, setError] = useState("");
  const [refund, setRefund] = useState(false);
  const load = useCallback(async () => {
    if (id === null) return;
    setError("");
    try { setD(await bo.get<PaymentDetail>(`/finance/payments/${id}/`)); } catch (e) { setError(boError(e, "Ce paiement n’a pas pu être chargé.")); }
  }, [id]);
  useEffect(() => { setD(null); void load(); }, [load]);
  return (
    <>
      <Modal open={id !== null && !refund} onClose={onClose} size="lg" title={d ? `Paiement #${d.id} — réservation #${d.booking_id}` : "Paiement"}>
        {error ? <Alert tone="danger">{error}</Alert> : null}
        {!d && !error ? <p className="text-sm text-inkSoft" role="status">Chargement…</p> : null}
        {d ? (
          <div className="space-y-5">
            <KV items={[["Statut", <Tag key="s" value={d.status} label={STATUS_FR[d.status]} />], ["Moyen", METHOD_FR[d.method] ?? d.method], ["Montant", moneyLabel(d.amount)], ["Commission", moneyLabel(d.platform_fee)], ["Net artisan", moneyLabel(d.net)],
              ["Remboursé", moneyLabel(d.refunded_amount)], ["Remise", moneyLabel(d.discount)], ["Client", d.client], ["Artisan", d.artisan], ["Statut de la réservation", STATUS_FR[d.booking_status] ?? d.booking_status]]} />
            <div><h3 className="mb-1.5 text-sm font-bold text-ink">Journal du paiement</h3>
              <ul className="divide-y divide-lineSoft text-sm">{d.logs.map((l, i) => <li key={i} className="py-1.5">{STATUS_FR[l.previous_status] ?? l.previous_status} → <strong>{STATUS_FR[l.new_status] ?? l.new_status}</strong> · {dt(l.at)}{l.notes ? <span className="block text-inkSoft">{l.notes}</span> : null}</li>)}</ul></div>
            {d.can_refund ? <div><Button variant="danger" onClick={() => setRefund(true)}>Rembourser le client</Button><p className="mt-2 text-xs text-ash">Le remboursement passe par l’escrow existant : il ne crée ni ne valide aucun paiement.</p></div> : <p className="text-xs text-ash">Aucun remboursement possible dans l’état actuel (ou droit insuffisant).</p>}
          </div>
        ) : null}
      </Modal>
      <ReasonModal open={refund} title="Rembourser ce paiement ?" description="Laissez le montant vide pour un remboursement total. Un montant partiel conserve le solde comme pénalité." confirmLabel="Rembourser" tone="danger"
        fields={[{ key: "amount", label: "Montant à rembourser (FCFA)", hint: `Maximum : ${d ? moneyLabel(d.amount) : ""}`, type: "number" }]} onClose={() => setRefund(false)}
        request={(b) => bo.post(`/finance/payments/${id}/refund/`, { reason: b.reason, ...(b.amount ? { amount: b.amount.replace(",", ".") } : {}) })}
        onDone={() => { setRefund(false); void load(); onChanged(); }} />
    </>
  );
}

export default function FinancePage() {
  const { can } = useBo();
  const [tab, setTab] = useTabParam(["payments", "payouts", "invoices"] as const, "payments");
  const [notice, setNotice] = useNotice();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [summaryError, setSummaryError] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [method, setMethod] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [pStatus, setPStatus] = useState("pending");
  const [open, setOpen] = useState<number | null>(null);
  const [approve, setApprove] = useState<Payout | null>(null);
  const [reject, setReject] = useState<Payout | null>(null);
  const payments = useBoList<Payment>("/finance/payments/", { q: useDebounced(q), status, method, from, to });
  const payouts = useBoList<Payout>("/finance/payouts/", { status: pStatus });
  const invoices = useBoList<Invoice>("/finance/invoices/", {});

  const loadSummary = useCallback(() => {
    setSummaryError("");
    void bo.get<Summary>("/finance/summary/").then(setSummary).catch((e) => { setSummary(null); setSummaryError(boError(e, "La synthèse financière n’a pas pu être chargée.")); });
  }, []);
  useEffect(loadSummary, [loadSummary]);

  const payCols: Column<Payment>[] = [
    { key: "id", header: "Paiement", primary: true, cell: (r) => <span className="font-semibold text-ink">#{r.id} · réservation #{r.booking_id}</span> },
    { key: "status", header: "Statut", cell: (r) => <Tag value={r.status} label={STATUS_FR[r.status]} /> },
    { key: "method", header: "Moyen", hideOnMobile: true, cell: (r) => METHOD_FR[r.method] ?? r.method },
    { key: "amount", header: "Montant", align: "right", cell: (r) => moneyLabel(r.amount) },
    { key: "fee", header: "Commission", align: "right", hideOnMobile: true, cell: (r) => moneyLabel(r.platform_fee) },
    { key: "parties", header: "Client → artisan", hideOnMobile: true, cell: (r) => `${r.client} → ${r.artisan}` },
    { key: "date", header: "Créé le", hideOnMobile: true, cell: (r) => dt(r.created_at) },
    { key: "act", header: "", align: "right", cell: (r) => <Button size="sm" variant="outline" onClick={() => setOpen(r.id)}>Détail</Button> },
  ];
  const outCols: Column<Payout>[] = [
    { key: "id", header: "Retrait", primary: true, cell: (r) => <span className="font-semibold text-ink">#{r.id} · {r.artisan}</span> },
    { key: "amount", header: "Montant", align: "right", cell: (r) => moneyLabel(r.amount) },
    { key: "status", header: "Statut", cell: (r) => <Tag value={r.status} label={STATUS_FR[r.status]} /> },
    { key: "req", header: "Demandé le", hideOnMobile: true, cell: (r) => dt(r.requested_at) },
    { key: "note", header: "Référence / note", hideOnMobile: true, cell: (r) => <span className="text-inkSoft">{r.notes || "—"}</span> },
    { key: "act", header: "", align: "right", cell: (r) => (r.status === "pending" && can("finance.manage") ? <span className="flex justify-end gap-2"><Button size="sm" onClick={() => setApprove(r)}>Valider</Button><Button size="sm" variant="danger" onClick={() => setReject(r)}>Rejeter</Button></span> : null) },
  ];
  const invCols: Column<Invoice>[] = [
    { key: "n", header: "Facture", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.number}</span> },
    { key: "b", header: "Réservation", cell: (r) => `#${r.booking_id}` },
    { key: "p", header: "Client → artisan", hideOnMobile: true, cell: (r) => `${r.client} → ${r.artisan}` },
    { key: "amount", header: "Montant", align: "right", cell: (r) => moneyLabel(r.amount) },
    { key: "fee", header: "Commission", align: "right", hideOnMobile: true, cell: (r) => moneyLabel(r.fee) },
    { key: "total", header: "Total", align: "right", cell: (r) => moneyLabel(r.total) },
  ];

  return (
    <>
      <PageHeader title="Finances" description="Paiements sous séquestre, commissions, remboursements et retraits. Aucun paiement ne se crée ni ne se valide à la main : les montants viennent des réservations." />
      {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}
      {summary ? (
        <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Volume payé" value={moneyLabel(summary.gmv)} />
          <Stat label="Commissions gagnées" value={moneyLabel(summary.commission_earned)} hint={`${moneyLabel(summary.commission_in_escrow)} encore sous séquestre`} tone="accent" />
          <Stat label="Sous séquestre" value={moneyLabel(summary.escrow_held)} tone="night" />
          <Stat label="Remboursé" value={moneyLabel(summary.refunded)} hint={`Retraits en attente : ${summary.payouts.pending?.count ?? 0} (${moneyLabel(summary.payouts.pending?.amount ?? "0")})`} />
        </div>
      ) : summaryError ? <Alert tone="danger" className="mb-6" action={<Button size="sm" variant="outline" onClick={loadSummary}>Réessayer</Button>}>{summaryError}</Alert> : <SkeletonStats count={4} className="mb-6 sm:grid-cols-2 lg:grid-cols-4" />}
      <Tabs ariaLabel="Sections" value={tab} onChange={setTab} className="mb-4" items={[{ id: "payments", label: "Paiements" }, { id: "payouts", label: "Retraits" }, { id: "invoices", label: "Factures" }]} />
      {tab === "payments" ? (
        <>
          <FilterBar>
            <SearchBox value={q} onChange={setQ} placeholder="N° de paiement ou de réservation…" />
            <FilterSelect label="Statut" value={status} onChange={setStatus} options={[["", "Tous"], ["pending", "En attente"], ["held", "Séquestre"], ["released", "Versé"], ["refunded", "Remboursé"], ["failed", "Échoué"]]} />
            <FilterSelect label="Moyen" value={method} onChange={setMethod} options={[["", "Tous"], ...Object.entries(METHOD_FR)]} />
            <DateRange from={from} to={to} onFrom={setFrom} onTo={setTo} />
          </FilterBar>
          <ListView list={payments} columns={payCols} rowKey={(r) => r.id} caption="Paiements" empty="Aucun paiement ne correspond." />
        </>
      ) : null}
      {tab === "payouts" ? (
        <>
          <FilterBar><FilterSelect label="Statut" value={pStatus} onChange={setPStatus} options={[["pending", "En attente"], ["sent", "Envoyés"], ["failed", "Rejetés"], ["", "Tous"]]} /></FilterBar>
          <ListView list={payouts} columns={outCols} rowKey={(r) => r.id} caption="Retraits" empty="Aucun retrait dans cet état." />
        </>
      ) : null}
      {tab === "invoices" ? <Section title="Factures de plateforme"><ListView list={invoices} columns={invCols} rowKey={(r) => r.id} caption="Factures" empty="Aucune facture." /></Section> : null}

      <PaymentPanel id={open} onClose={() => setOpen(null)} onChanged={() => { payments.reload(); loadSummary(); }} />
      <ReasonModal open={Boolean(approve)} title={`Valider le retrait #${approve?.id ?? ""} ?`} description={`Confirmez que le virement de ${approve ? moneyLabel(approve.amount) : ""} à ${approve?.artisan ?? ""} a RÉELLEMENT été effectué, et saisissez sa référence. L’artisan en est informé.`}
        confirmLabel="Marquer comme envoyé" reasonKey="reference" reasonLabel="Référence du virement" onClose={() => setApprove(null)}
        request={(b) => bo.post(`/finance/payouts/${approve?.id}/approve/`, { reference: b.reference })} onDone={() => { setApprove(null); setNotice("Retrait marqué comme envoyé."); payouts.reload(); loadSummary(); }} />
      <ReasonModal open={Boolean(reject)} title={`Rejeter le retrait #${reject?.id ?? ""} ?`} description="Les gains redeviennent disponibles pour l’artisan, qui est informé du motif." confirmLabel="Rejeter" tone="danger" onClose={() => setReject(null)}
        request={(b) => bo.post(`/finance/payouts/${reject?.id}/reject/`, { reason: b.reason })} onDone={() => { setReject(null); setNotice("Retrait rejeté."); payouts.reload(); loadSummary(); }} />
    </>
  );
}
