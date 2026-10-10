"use client";
import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Modal, PageHeader, Tabs, type Column } from "@/components/ds";
import { bo, boError, moneyLabel } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useBoList, useDebounced } from "@/lib/useBoList";
import { DateRange, FilterBar, FilterSelect, KV, ListView, ReasonModal, SearchBox, STATUS_FR, Tag, dt, useNotice, useTabParam } from "../_components/ui";

interface Booking { id: number; status: string; service: string | null; client: string; artisan: string; booking_date: string; city: string | null; payment_status: string | null; disputes: number; created_at: string }
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

export default function BookingsPage() {
  const { can } = useBo();
  const [tab, setTab] = useTabParam(["bookings", "disputes"] as const, "bookings");
  const [notice] = useNotice();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [disputed, setDisputed] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [dStatus, setDStatus] = useState("open_only");
  const [openDispute, setOpenDispute] = useState<number | null>(null);
  const bookings = useBoList<Booking>("/bookings/", { q: useDebounced(q), status, disputed, from, to });
  const disputes = useBoList<Dispute>("/disputes/", dStatus === "open_only" ? { open: "true" } : { status: dStatus });

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id");
    if (id && /^\d+$/.test(id)) setOpenDispute(Number(id));
  }, []);

  const bColumns: Column<Booking>[] = [
    { key: "id", header: "N°", primary: true, cell: (r) => <span className="font-semibold text-ink">#{r.id}</span> },
    { key: "status", header: "Statut", cell: (r) => <Tag value={r.status} label={STATUS_FR[r.status]} /> },
    { key: "service", header: "Service", cell: (r) => r.service ?? "—" },
    { key: "parties", header: "Client → artisan", hideOnMobile: true, cell: (r) => `${r.client} → ${r.artisan}` },
    { key: "date", header: "Prévue le", cell: (r) => dt(r.booking_date) },
    { key: "pay", header: "Paiement", hideOnMobile: true, cell: (r) => (r.payment_status ? <Tag value={r.payment_status} label={STATUS_FR[r.payment_status]} /> : "—") },
    { key: "disp", header: "Litiges", align: "right", cell: (r) => (r.disputes ? <Badge tone="danger">{r.disputes}</Badge> : "—") },
  ];
  const dColumns: Column<Dispute>[] = [
    { key: "id", header: "Litige", primary: true, cell: (r) => <span className="font-semibold text-ink">#{r.id} · réservation #{r.booking_id}</span> },
    { key: "status", header: "Statut", cell: (r) => <Tag value={r.status} label={STATUS_FR[r.status]} /> },
    { key: "reporter", header: "Ouvert par", cell: (r) => r.reporter },
    { key: "reason", header: "Motif", hideOnMobile: true, cell: (r) => <span className="text-inkSoft">{r.reason}</span> },
    { key: "amount", header: "Montant", align: "right", hideOnMobile: true, cell: (r) => (r.amount ? moneyLabel(r.amount) : "—") },
    { key: "date", header: "Ouvert le", hideOnMobile: true, cell: (r) => dt(r.created_at) },
    { key: "act", header: "", align: "right", cell: (r) => <Button size="sm" variant="outline" onClick={() => setOpenDispute(r.id)}>{can("bookings.manage") && (r.status === "open" || r.status === "under_review") ? "Traiter" : "Voir"}</Button> },
  ];

  return (
    <>
      <PageHeader title="Réservations et litiges" description="Consultation et médiation. L’administration passe par la machine à états et l’escrow : rien ne contourne le circuit normal." />
      {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}
      <Tabs ariaLabel="Sections" value={tab} onChange={setTab} className="mb-4" items={[{ id: "bookings", label: "Réservations", count: tab === "bookings" ? bookings.count : undefined }, { id: "disputes", label: "Litiges", count: tab === "disputes" ? disputes.count : undefined }]} />
      {tab === "bookings" ? (
        <>
          <FilterBar>
            <SearchBox value={q} onChange={setQ} placeholder="N°, client, artisan, ville, service…" />
            <FilterSelect label="Statut" value={status} onChange={setStatus} options={[["", "Tous"], ...Object.entries(STATUS_FR).filter(([k]) => ["pending", "confirmed", "in_progress", "completed", "cancelled"].includes(k))]} />
            <FilterSelect label="Litiges" value={disputed} onChange={setDisputed} options={[["", "Tous"], ["true", "Avec litige"]]} />
            <DateRange from={from} to={to} onFrom={setFrom} onTo={setTo} />
          </FilterBar>
          <ListView list={bookings} columns={bColumns} rowKey={(r) => r.id} rowHref={(r) => `/backoffice/bookings/${r.id}`} caption="Réservations" empty="Aucune réservation ne correspond." />
        </>
      ) : (
        <>
          <FilterBar>
            <FilterSelect label="Statut" value={dStatus} onChange={setDStatus} options={[["open_only", "À traiter"], ["open", "Ouverts"], ["under_review", "En examen"], ["resolved", "Résolus"], ["rejected", "Rejetés"]]} />
          </FilterBar>
          <ListView list={disputes} columns={dColumns} rowKey={(r) => r.id} caption="Litiges" empty="Aucun litige dans cet état." />
        </>
      )}
      <DisputePanel id={openDispute} onClose={() => setOpenDispute(null)} onChanged={() => disputes.reload()} />
    </>
  );
}
