"use client";
import { useCallback, useEffect, useState } from "react";
import { Ban, CalendarCheck, Eye, Gavel, UserRound } from "lucide-react";
import { Alert, Badge, Button, Modal, PageHeader, Tabs } from "@/components/ds";
import { bo, boError, moneyLabel } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useBoList, useCounts, useManagedList } from "@/lib/useBoList";
import {
  DateRange, ExportButton, FilterBar, FilterSelect, KV, ListView, ReasonModal, SearchBox, STATUS_FR, StatusChips, Tag, dd, dt, postTo, useNotice, useTabParam,
  type BoColumn, type RowAction,
} from "../_components/ui";

interface Booking { id: number; status: string; service: string | null; client: string; client_id: number; artisan: string; artisan_id: number; booking_date: string; city: string | null; payment_status: string | null; disputes: number; created_at: string }
interface Dispute { id: number; booking_id: number; status: string; reporter: string; reason: string; created_at: string; resolved_at: string | null; resolution_action: string | null; payment_status: string | null; amount: string | null }
interface DisputeDetail extends Dispute { client: string; artisan: string; reporter_role: string; resolution: string; resolved_by: string | null; can_decide: boolean; can_move_money: boolean; history: { action: string; at: string; by: string; reason: string }[] }

const ACTION_FR: Record<string, string> = { refund_client: "Remboursement du client", release_artisan: "Versement à l’artisan", none: "Aucune action financière" };

function DisputePanel({ id, onClose, onChanged }: { id: number | null; onClose: () => void; onChanged: () => void }) {
  const [d, setD] = useState<DisputeDetail | null>(null);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"resolve" | "reject" | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (id === null) return;
    setError("");
    try {
      setD(await bo.get<DisputeDetail>(`/disputes/${id}/`));
    } catch (e) {
      setError(boError(e, "Ce litige n’a pas pu être chargé."));
    }
  }, [id]);
  useEffect(() => { setD(null); void load(); }, [load]);

  async function takeCharge() {
    setBusy(true);
    try {
      await bo.post(`/disputes/${id}/review/`, {});
      await load();
      onChanged();
    } catch (e) {
      setError(boError(e, "Impossible de prendre en charge ce litige."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Modal open={id !== null && mode === null} onClose={onClose} size="lg" title={d ? `Litige #${d.id} — réservation #${d.booking_id}` : "Litige"}>
        {error ? <Alert tone="danger" className="mb-3">{error}</Alert> : null}
        {!d && !error ? <p className="text-sm text-inkSoft" role="status">Chargement…</p> : null}
        {d ? (
          <div className="space-y-5">
            <KV items={[["Statut", <Tag key="s" value={d.status} label={STATUS_FR[d.status]} />], ["Ouvert par", `${d.reporter} (${d.reporter_role === "client" ? "client" : "artisan"})`], ["Client", d.client], ["Artisan", d.artisan],
              ["Paiement", d.payment_status ? STATUS_FR[d.payment_status] ?? d.payment_status : "Aucun"], ["Montant", d.amount ? moneyLabel(d.amount) : "Réservé aux rôles financiers"], ["Ouvert le", dt(d.created_at)]]} />
            <div>
              <h3 className="mb-1 text-sm font-bold text-ink">Motif du litige</h3>
              <p className="whitespace-pre-line rounded-panel bg-canvas p-3 text-sm text-inkSoft">{d.reason}</p>
            </div>
            {d.status === "resolved" || d.status === "rejected" ? (
              <Alert tone="info" title={d.status === "resolved" ? `Résolu : ${ACTION_FR[d.resolution_action ?? "none"] ?? d.resolution_action}` : "Litige rejeté"}>
                {d.resolution || "Sans commentaire."} — {d.resolved_by ?? "—"} le {dt(d.resolved_at)}
              </Alert>
            ) : d.can_decide ? (
              <div className="flex flex-wrap gap-2">
                {d.status === "open" ? <Button variant="outline" loading={busy} onClick={() => void takeCharge()}>Prendre en charge</Button> : null}
                <Button onClick={() => setMode("resolve")}>Trancher</Button>
                <Button variant="danger" onClick={() => setMode("reject")}>Rejeter</Button>
              </div>
            ) : <Alert tone="warning">Votre rôle consulte ce litige sans pouvoir le trancher.</Alert>}
            {d.history.length ? (
              <ul className="divide-y divide-lineSoft text-sm">
                {d.history.map((h, i) => <li key={i} className="py-1.5"><strong>{h.action.replace("backoffice.", "")}</strong> — {h.by} · {dt(h.at)}{h.reason ? <span className="block text-inkSoft">{h.reason}</span> : null}</li>)}
              </ul>
            ) : null}
          </div>
        ) : null}
      </Modal>
      <ReasonModal
        open={mode === "resolve"}
        title="Trancher ce litige"
        description={d?.can_move_money ? "Rembourser ou verser déplace de l’argent : la décision est définitive et journalisée." : "Votre rôle ne peut pas déplacer d’argent : choisissez « Aucune action financière » ou demandez à la finance de trancher."}
        confirmLabel="Valider la décision"
        reasonLabel="Résolution (visible dans le journal)"
        fields={[{ key: "action", label: "Décision", type: "select", options: [["none", ACTION_FR.none], ...(d?.can_move_money ? [["refund_client", ACTION_FR.refund_client], ["release_artisan", ACTION_FR.release_artisan]] as [string, string][] : [])] }]}
        onClose={() => setMode(null)}
        request={(b) => bo.post(`/disputes/${id}/resolve/`, { action: b.action || "none", reason: b.reason })}
        onDone={() => { setMode(null); void load(); onChanged(); }}
      />
      <ReasonModal open={mode === "reject"} title="Rejeter ce litige" description="Aucune action financière n’est effectuée. Les deux parties sont informées." confirmLabel="Rejeter" tone="danger" onClose={() => setMode(null)}
        request={(b) => bo.post(`/disputes/${id}/reject/`, { reason: b.reason })} onDone={() => { setMode(null); void load(); onChanged(); }} />
    </>
  );
}

const BOOKING_STATES = ["pending", "confirmed", "in_progress", "completed", "cancelled"] as const;

function BookingsTab() {
  const { can } = useBo();
  const m = useManagedList<Booking, { status: string; disputed: string; payment_status: string; user: string; from: string; to: string }>("/bookings/", { status: "", disputed: "", payment_status: "", user: "", from: "", to: "" });
  const { values: f, list } = m;
  const counts = useCounts("/bookings/", { _all: "", ...Object.fromEntries(BOOKING_STATES.map((s) => [s, `status=${s}`])) }, list.count);
  const [cancel, setCancel] = useState<Booking | null>(null);
  const [notice, setNotice] = useNotice();
  const canManage = can("bookings.manage");

  const columns: BoColumn<Booking>[] = [
    { key: "id", header: "N°", primary: true, sort: "created_at", cell: (r) => <span className="font-semibold text-ink">#{r.id}</span> },
    { key: "status", header: "Statut", sort: "status", cell: (r) => <Tag value={r.status} label={STATUS_FR[r.status]} /> },
    { key: "service", header: "Service", wrap: true, cell: (r) => r.service ?? "—" },
    { key: "parties", header: "Client → artisan", hideOnMobile: true, from: "xl", cell: (r) => `${r.client} → ${r.artisan}` },
    { key: "date", header: "Prévue le", sort: "date", cell: (r) => dd(r.booking_date) },
    { key: "pay", header: "Paiement", hideOnMobile: true, from: "xl", cell: (r) => (r.payment_status ? <Tag value={r.payment_status} label={STATUS_FR[r.payment_status]} /> : "—") },
    { key: "disp", header: "Litiges", align: "right", cell: (r) => (r.disputes ? <Badge tone="danger">{r.disputes}</Badge> : "—") },
  ];
  const rowActions = (r: Booking): RowAction[] => [
    { label: "Ouvrir la réservation", icon: Eye, href: `/backoffice/bookings/${r.id}` },
    { label: "Fiche du client", icon: UserRound, href: `/backoffice/users/${r.client_id}`, hidden: !can("users.view") },
    { label: "Fiche de l’artisan", icon: UserRound, href: `/backoffice/users/${r.artisan_id}`, hidden: !can("users.view") },
    { label: "Litiges de cette réservation", icon: Gavel, href: `/backoffice/bookings?tab=disputes&q=${r.id}`, hidden: !r.disputes },
    { label: "Annuler la réservation", icon: Ban, tone: "danger", onClick: () => setCancel(r), hidden: !canManage || !["pending", "confirmed", "in_progress"].includes(r.status) },
  ];

  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <StatusChips items={[["", "Toutes"], ["pending", "En attente"], ["confirmed", "Confirmées"], ["in_progress", "En cours"], ["completed", "Terminées"], ["cancelled", "Annulées"]]} value={f.status} onChange={(v) => m.set({ status: v })} counts={counts} label="Statut de la réservation" />
      <FilterBar
        search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="N°, client, artisan, ville, service…" />}
        activeCount={m.activeCount}
        onReset={m.reset}
        onRefresh={() => void list.reload()}
        refreshing={list.loading}
        actions={<ExportButton dataset="bookings" from={f.from} to={f.to} />}
      >
        <FilterSelect label="Litiges" value={f.disputed} onChange={(v) => m.set({ disputed: v })} options={[["", "Tous"], ["true", "Avec litige"]]} />
        <FilterSelect label="Paiement" value={f.payment_status} onChange={(v) => m.set({ payment_status: v })} options={[["", "Tous"], ["pending", "En attente"], ["held", "Sous séquestre"], ["released", "Versé"], ["refunded", "Remboursé"], ["failed", "Échoué"]]} />
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
        {f.user ? (
          <Button size="sm" variant="soft" onClick={() => m.set({ user: "" })} title="Retirer le filtre par compte">Compte #{f.user} ✕</Button>
        ) : null}
      </FilterBar>
      <ListView
        list={list}
        columns={columns}
        rowKey={(r) => r.id}
        rowHref={(r) => `/backoffice/bookings/${r.id}`}
        rowLabel={(r) => `réservation #${r.id}`}
        caption="Réservations"
        empty="Aucune réservation ne correspond."
        emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        ordering={f.ordering}
        onOrdering={(v) => m.set({ ordering: v })}
        rowActions={rowActions}
        pageSize={m.pageSize}
        onPageSize={(n) => m.set({ size: String(n) })}
      />
      <ReasonModal
        open={Boolean(cancel)}
        title={`Annuler la réservation #${cancel?.id ?? ""} ?`}
        description="L’annulation suit la politique de pénalité et l’escrow (remboursement net). Le client et l’artisan sont informés."
        confirmLabel="Annuler la réservation"
        tone="danger"
        onClose={() => setCancel(null)}
        request={cancel ? postTo(`/bookings/${cancel.id}/cancel/`) : async () => undefined}
        onDone={() => { setCancel(null); setNotice("Réservation annulée."); void list.reload(); }}
      />
    </>
  );
}

type DisputeFilters = { status: string; user: string; from: string; to: string };

function DisputesTab({ openDispute }: { openDispute: (id: number) => void }) {
  const { can } = useBo();
  const m = useManagedList<Dispute, DisputeFilters>("/disputes/", { status: "todo", user: "", from: "", to: "" });
  const { values: f, list } = m;
  const counts = useCounts("/disputes/", { todo: "status=todo", open: "status=open", under_review: "status=under_review", resolved: "status=resolved", rejected: "status=rejected", _all: "" }, list.count);
  const columns: BoColumn<Dispute>[] = [
    { key: "id", header: "Litige", primary: true, sort: "created_at", cell: (r) => <span className="font-semibold text-ink">#{r.id} · réservation #{r.booking_id}</span> },
    { key: "status", header: "Statut", sort: "status", cell: (r) => <Tag value={r.status} label={STATUS_FR[r.status]} /> },
    { key: "reporter", header: "Ouvert par", cell: (r) => r.reporter },
    { key: "reason", header: "Motif", wrap: true, hideOnMobile: true, from: "xl", cell: (r) => <span className="text-inkSoft">{r.reason}</span> },
    { key: "amount", header: "Montant", align: "right", hideOnMobile: true, from: "xl", cell: (r) => (r.amount ? moneyLabel(r.amount) : "—") },
    { key: "date", header: "Ouvert le", hideOnMobile: true, from: "lg", cell: (r) => dd(r.created_at) },
  ];
  const rowActions = (r: Dispute): RowAction[] => [
    { label: can("bookings.manage") && (r.status === "open" || r.status === "under_review") ? "Traiter le litige" : "Voir le litige", icon: Gavel, onClick: () => openDispute(r.id) },
    { label: "Ouvrir la réservation", icon: CalendarCheck, href: `/backoffice/bookings/${r.booking_id}` },
  ];
  return (
    <>
      <StatusChips items={[["todo", "À traiter"], ["open", "Ouverts"], ["under_review", "En examen"], ["resolved", "Résolus"], ["rejected", "Rejetés"], ["", "Tous"]]} value={f.status} onChange={(v) => m.set({ status: v })} counts={counts} label="Statut du litige" />
      <FilterBar
        search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="N° de litige ou de réservation, motif, plaignant…" />}
        activeCount={m.activeCount}
        onReset={m.reset}
        onRefresh={() => void list.reload()}
        refreshing={list.loading}
      >
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
        {f.user ? <Button size="sm" variant="soft" onClick={() => m.set({ user: "" })} title="Retirer le filtre par compte">Compte #{f.user} ✕</Button> : null}
      </FilterBar>
      <ListView
        list={list}
        columns={columns}
        rowKey={(r) => r.id}
        rowLabel={(r) => `litige #${r.id}`}
        caption="Litiges"
        empty="Aucun litige dans cet état."
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

export default function BookingsPage() {
  const [tab, setTab] = useTabParam(["bookings", "disputes"] as const, "bookings");
  const [openDispute, setOpenDispute] = useState<number | null>(null);
  const disputesVersion = useBoList<Dispute>("/disputes/", { status: "todo" }, 1); // compteur de l'onglet : litiges à traiter
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id");
    if (id && /^\d+$/.test(id)) setOpenDispute(Number(id));
  }, []);

  return (
    <>
      <PageHeader title="Réservations et litiges" description="Consultation et médiation. L’administration passe par la machine à états et l’escrow : rien ne contourne le circuit normal." />
      <Tabs ariaLabel="Sections" value={tab} onChange={setTab} className="mb-4" items={[{ id: "bookings", label: "Réservations" }, { id: "disputes", label: "Litiges", count: disputesVersion.count }]} />
      {tab === "bookings" ? <BookingsTab /> : <DisputesTab key={reloadKey} openDispute={setOpenDispute} />}
      <DisputePanel id={openDispute} onClose={() => setOpenDispute(null)} onChanged={() => { setReloadKey((k) => k + 1); void disputesVersion.reload(); }} />
    </>
  );
}
