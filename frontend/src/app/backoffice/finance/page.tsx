"use client";
import { CashBlock } from "../_components/CashBlock";
import type { CashSummary } from "@/lib/cash";
import { useCallback, useEffect, useState } from "react";
import { Banknote, CalendarCheck, Check, Coins, Eye, Landmark, ShieldCheck, X } from "lucide-react";
import { Alert, Button, Modal, PageHeader, SkeletonStats, Tabs } from "@/components/ds";
import { bo, boError, moneyLabel } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useCounts, useManagedList } from "@/lib/useBoList";
import { DateRange, ExportButton, FilterBar, FilterSelect, Kpi, KpiGrid, KV, ListView, ReasonModal, SearchBox, STATUS_FR, StatusChips, Tag, dd, dt, useNotice, useTabParam, type BoColumn, type RowAction } from "../_components/ui";

interface Summary { gmv: string; commission_earned: string; commission_in_escrow: string; escrow_held: string; refunded: string; payouts: Record<string, { count: number; amount: string }>; by_status: Record<string, { count: number; amount: string }> }
interface Payment { id: number; booking_id: number; client: string; artisan: string; amount: string; platform_fee: string; net: string; method: string; status: string; refunded_amount: string; created_at: string; payment_date: string | null; verification: "provider_verified" | "unverified" | "manual"; provider_verified_at: string | null; provider_checked_at: string | null; provider_status: string }
interface PaymentDetail extends Payment { cash?: CashSummary; booking_status: string; discount: string; can_refund: boolean; logs: { previous_status: string; new_status: string; at: string; notes: string }[]; history: { action: string; at: string; by: string; reason: string }[] }
interface Payout { id: number; artisan_id: number; artisan: string; amount: string; status: string; requested_at: string; processed_at: string | null; notes: string }
interface Invoice { id: number; number: string; booking_id: number; client: string; artisan: string; amount: string; fee: string; total: string }

const VERIFICATION_FR: Record<string, string> = { provider_verified: "Vérifié auprès du prestataire", unverified: "Non vérifié", manual: "Confirmation manuelle (sans prestataire)" };
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
              ["Preuve de l’encaissement", d.provider_verified_at ? `${VERIFICATION_FR[d.verification]} · ${dt(d.provider_verified_at)}` : VERIFICATION_FR[d.verification] ?? d.verification],
              ...(d.provider_status ? [["Dernier statut du prestataire", d.provider_status] as [string, string]] : []),
              ["Remboursé", moneyLabel(d.refunded_amount)], ["Remise", moneyLabel(d.discount)], ["Client", d.client], ["Artisan", d.artisan], ["Statut de la réservation", STATUS_FR[d.booking_status] ?? d.booking_status]]} />
            {d.cash ? <div><h3 className="mb-1.5 text-sm font-bold text-ink">Espèces entre les parties</h3><CashBlock cash={d.cash} /></div> : null}
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

function PaymentsTab({ onOpen, version }: { onOpen: (id: number) => void; version: number }) {
  const m = useManagedList<Payment, { status: string; method: string; user: string; from: string; to: string }>("/finance/payments/", { status: "", method: "", user: "", from: "", to: "" });
  const { values: f, list } = m;
  const counts = useCounts("/finance/payments/", { _all: "", pending: "status=pending", held: "status=held", released: "status=released", refunded: "status=refunded", failed: "status=failed" }, `${list.version}-${version}`);
  const columns: BoColumn<Payment>[] = [
    { key: "id", header: "Paiement", primary: true, sort: "created_at", cell: (r) => <span className="font-semibold text-ink">#{r.id} · réservation #{r.booking_id}</span> },
    { key: "status", header: "Statut", sort: "status", cell: (r) => <Tag value={r.status} label={STATUS_FR[r.status]} /> },
    { key: "method", header: "Moyen", hideOnMobile: true, from: "lg", cell: (r) => METHOD_FR[r.method] ?? r.method },
    { key: "amount", header: "Montant", align: "right", sort: "amount", cell: (r) => moneyLabel(r.amount) },
    { key: "fee", header: "Commission", align: "right", hideOnMobile: true, from: "xl", cell: (r) => moneyLabel(r.platform_fee) },
    { key: "parties", header: "Client → artisan", hideOnMobile: true, from: "xl", cell: (r) => `${r.client} → ${r.artisan}` },
    { key: "date", header: "Créé le", hideOnMobile: true, from: "2xl", cell: (r) => dd(r.created_at) },
  ];
  const rowActions = (r: Payment): RowAction[] => [
    { label: "Détail du paiement", icon: Eye, onClick: () => onOpen(r.id) },
    { label: "Ouvrir la réservation", icon: CalendarCheck, href: `/backoffice/bookings/${r.booking_id}` },
  ];
  return (
    <>
      <StatusChips items={[["", "Tous"], ["pending", "En attente"], ["held", "Séquestre"], ["released", "Versés"], ["refunded", "Remboursés"], ["failed", "Échoués"]]} value={f.status} onChange={(v) => m.set({ status: v })} counts={counts} label="Statut du paiement" />
      <FilterBar
        search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="N° de paiement ou de réservation, nom du client ou de l’artisan…" />}
        activeCount={m.activeCount}
        onReset={m.reset}
        onRefresh={() => void list.reload()}
        refreshing={list.loading}
        actions={<ExportButton dataset="payments" from={f.from} to={f.to} />}
      >
        <FilterSelect label="Moyen" value={f.method} onChange={(v) => m.set({ method: v })} options={[["", "Tous"], ...Object.entries(METHOD_FR)]} />
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
        {f.user ? <Button size="sm" variant="soft" onClick={() => m.set({ user: "" })} title="Retirer le filtre par compte">Compte #{f.user} ✕</Button> : null}
      </FilterBar>
      <ListView
        list={list}
        columns={columns}
        rowKey={(r) => r.id}
        rowLabel={(r) => `paiement #${r.id}`}
        caption="Paiements"
        empty="Aucun paiement ne correspond."
        emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        ordering={f.ordering}
        onOrdering={(v) => m.set({ ordering: v })}
        rowActions={rowActions}
        pageSize={m.pageSize}
        onPageSize={(n) => m.set({ size: String(n) })}
      />
    </>
  );
}

function PayoutsTab({ onChanged, version }: { onChanged: () => void; version: number }) {
  const { can } = useBo();
  const manage = can("finance.manage");
  const m = useManagedList<Payout, { status: string; from: string; to: string }>("/finance/payouts/", { status: "pending", from: "", to: "" });
  const { values: f, list } = m;
  const counts = useCounts("/finance/payouts/", { pending: "status=pending", sent: "status=sent", failed: "status=failed", _all: "" }, `${list.version}-${version}`);
  const [approve, setApprove] = useState<Payout | null>(null);
  const [reject, setReject] = useState<Payout | null>(null);
  const [notice, setNotice] = useNotice();
  const columns: BoColumn<Payout>[] = [
    { key: "id", header: "Retrait", primary: true, sort: "requested_at", cell: (r) => <span className="font-semibold text-ink">#{r.id} · {r.artisan}</span> },
    { key: "amount", header: "Montant", align: "right", sort: "amount", cell: (r) => moneyLabel(r.amount) },
    { key: "status", header: "Statut", sort: "status", cell: (r) => <Tag value={r.status} label={STATUS_FR[r.status]} /> },
    { key: "req", header: "Demandé le", hideOnMobile: true, from: "lg", cell: (r) => dd(r.requested_at) },
    { key: "note", header: "Référence / note", wrap: true, hideOnMobile: true, from: "xl", cell: (r) => <span className="text-inkSoft">{r.notes || "—"}</span> },
    {
      key: "act", header: "Décision", align: "right", cell: (r) => (r.status === "pending" && manage ? (
        <span className="flex justify-end gap-2">
          <Button size="sm" leftIcon={<Check aria-hidden className="h-4 w-4" />} onClick={() => setApprove(r)}>Valider</Button>
          <Button size="sm" variant="danger" leftIcon={<X aria-hidden className="h-4 w-4" />} onClick={() => setReject(r)}>Rejeter</Button>
        </span>
      ) : <span className="text-ash">—</span>),
    },
  ];
  const rowActions = (r: Payout): RowAction[] => [
    { label: "Valider le retrait", icon: Check, onClick: () => setApprove(r), hidden: !manage || r.status !== "pending" },
    { label: "Rejeter le retrait", icon: X, tone: "danger", onClick: () => setReject(r), hidden: !manage || r.status !== "pending" },
    { label: "Fiche de l’artisan", icon: ShieldCheck, href: `/backoffice/users/${r.artisan_id}`, hidden: !can("users.view") },
  ];
  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <StatusChips items={[["pending", "En attente"], ["sent", "Envoyés"], ["failed", "Rejetés"], ["", "Tous"]]} value={f.status} onChange={(v) => m.set({ status: v })} counts={counts} label="Statut du retrait" />
      <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="N° de retrait ou nom de l’artisan…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
      </FilterBar>
      <ListView
        list={list}
        columns={columns}
        rowKey={(r) => r.id}
        rowLabel={(r) => `retrait #${r.id}`}
        caption="Retraits"
        empty="Aucun retrait dans cet état."
        emptyHint={f.status === "pending" && !m.activeCount ? "Aucun retrait en attente de validation." : undefined}
        ordering={f.ordering}
        onOrdering={(v) => m.set({ ordering: v })}
        rowActions={rowActions}
        pageSize={m.pageSize}
        onPageSize={(n) => m.set({ size: String(n) })}
      />
      <ReasonModal open={Boolean(approve)} title={`Valider le retrait #${approve?.id ?? ""} ?`} description={`Confirmez que le virement de ${approve ? moneyLabel(approve.amount) : ""} à ${approve?.artisan ?? ""} a RÉELLEMENT été effectué, et saisissez sa référence. L’artisan en est informé.`}
        confirmLabel="Marquer comme envoyé" reasonKey="reference" reasonLabel="Référence du virement" onClose={() => setApprove(null)}
        request={(b) => bo.post(`/finance/payouts/${approve?.id}/approve/`, { reference: b.reference })} onDone={() => { setApprove(null); setNotice("Retrait marqué comme envoyé."); void list.reload(); onChanged(); }} />
      <ReasonModal open={Boolean(reject)} title={`Rejeter le retrait #${reject?.id ?? ""} ?`} description="Les gains redeviennent disponibles pour l’artisan, qui est informé du motif." confirmLabel="Rejeter" tone="danger" onClose={() => setReject(null)}
        request={(b) => bo.post(`/finance/payouts/${reject?.id}/reject/`, { reason: b.reason })} onDone={() => { setReject(null); setNotice("Retrait rejeté."); void list.reload(); onChanged(); }} />
    </>
  );
}

function InvoicesTab() {
  const m = useManagedList<Invoice, { from: string; to: string }>("/finance/invoices/", { from: "", to: "" });
  const { values: f, list } = m;
  const columns: BoColumn<Invoice>[] = [
    { key: "n", header: "Facture", primary: true, sort: "issued_at", cell: (r) => <span className="font-semibold text-ink">{r.number}</span> },
    { key: "b", header: "Réservation", cell: (r) => <a className="font-semibold text-primaryDark underline underline-offset-2" href={`/backoffice/bookings/${r.booking_id}`}>#{r.booking_id}</a> },
    { key: "p", header: "Client → artisan", hideOnMobile: true, from: "lg", cell: (r) => `${r.client} → ${r.artisan}` },
    { key: "amount", header: "Montant", align: "right", hideOnMobile: true, cell: (r) => moneyLabel(r.amount) },
    { key: "fee", header: "Commission", align: "right", hideOnMobile: true, from: "xl", cell: (r) => moneyLabel(r.fee) },
    { key: "total", header: "Total", align: "right", sort: "total", cell: (r) => moneyLabel(r.total) },
  ];
  return (
    <>
      <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="N° de facture, de réservation ou nom du client…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => r.number} caption="Factures" empty="Aucune facture ne correspond." ordering={f.ordering} onOrdering={(v) => m.set({ ordering: v })}
        pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
    </>
  );
}

export default function FinancePage() {
  const [tab, setTab] = useTabParam(["payments", "payouts", "invoices"] as const, "payments");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [summaryError, setSummaryError] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [version, setVersion] = useState(0);

  const loadSummary = useCallback(() => {
    setSummaryError("");
    void bo.get<Summary>("/finance/summary/").then(setSummary).catch((e) => { setSummary(null); setSummaryError(boError(e, "La synthèse financière n’a pas pu être chargée.")); });
  }, []);
  useEffect(loadSummary, [loadSummary]);
  const changed = () => { setVersion((v) => v + 1); loadSummary(); };

  return (
    <>
      <PageHeader title="Finances" description="Paiements sous séquestre, commissions, remboursements et retraits. Aucun paiement ne se crée ni ne se valide à la main : les montants viennent des réservations." />
      {summary ? (
        <KpiGrid className="mb-5">
          <Kpi icon={<Banknote className="h-5 w-5" />} label="Volume payé" value={moneyLabel(summary.gmv)} />
          <Kpi icon={<Coins className="h-5 w-5" />} tone="accent" label="Commissions gagnées" value={moneyLabel(summary.commission_earned)} hint={`${moneyLabel(summary.commission_in_escrow)} encore sous séquestre`} />
          <Kpi icon={<Landmark className="h-5 w-5" />} tone="night" label="Sous séquestre" value={moneyLabel(summary.escrow_held)} />
          <Kpi label="Remboursé" value={moneyLabel(summary.refunded)} hint={`Retraits en attente : ${summary.payouts.pending?.count ?? 0} (${moneyLabel(summary.payouts.pending?.amount ?? "0")})`} />
        </KpiGrid>
      ) : summaryError ? <Alert tone="danger" className="mb-5" action={<Button size="sm" variant="outline" onClick={loadSummary}>Réessayer</Button>}>{summaryError}</Alert> : <SkeletonStats count={4} className="mb-5 sm:grid-cols-2 lg:grid-cols-4" />}
      <Tabs ariaLabel="Sections" value={tab} onChange={setTab} className="mb-4" items={[{ id: "payments", label: "Paiements" }, { id: "payouts", label: "Retraits", count: summary?.payouts.pending?.count }, { id: "invoices", label: "Factures" }]} />
      {tab === "payments" ? <PaymentsTab onOpen={setOpen} version={version} /> : null}
      {tab === "payouts" ? <PayoutsTab onChanged={changed} version={version} /> : null}
      {tab === "invoices" ? <InvoicesTab /> : null}
      <PaymentPanel id={open} onClose={() => setOpen(null)} onChanged={changed} />
    </>
  );
}
