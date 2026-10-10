"use client";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Alert, Button, PageHeader, SkeletonPage } from "@/components/ds";
import { bo, boError, moneyLabel } from "@/lib/bo";
import { CashBlock } from "../../_components/CashBlock";
import { KV, ReasonModal, Section, STATUS_FR, Tag, dt, postTo } from "../../_components/ui";
import type { CashSummary } from "@/lib/cash";

interface Detail {
  id: number;
  status: string;
  version: number;
  service: string | null;
  client: string;
  client_id: number;
  artisan: string;
  artisan_id: number;
  booking_date: string;
  city: string | null;
  description: string | null;
  address: string | null;
  client_phone: string | null;
  artisan_phone: string | null;
  created_at: string;
  timeline: { status: string; previous_status: string | null; at: string; by: string }[];
  payment: { status: string; method: string; amount?: string; platform_fee?: string; refunded?: string } | null;
  cash: CashSummary | null;
  disputes: { id: number; status: string; created_at: string }[];
  live: { artisan_sharing: boolean; en_route_at: string | null; arrived_at: string | null } | null;
  identity_verified: boolean;
  review: { id: number; rating: number; hidden: boolean } | null;
  messages: number;
  can_cancel: boolean;
  history: { action: string; at: string; by: string; reason: string }[];
}
const BY_FR: Record<string, string> = { client: "le client", handyman: "l’artisan", admin: "l’administration", system: "le système" };

export default function BookingDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [cancel, setCancel] = useState(false);
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setD(await bo.get<Detail>(`/bookings/${id}/`));
    } catch (e) {
      setError(boError(e, "Cette réservation n’a pas pu être chargée."));
    }
  }, [id]);
  useEffect(() => void load(), [load]);

  if (error && !d) {
    return (
      <>
        <PageHeader title="Réservation" back={{ href: "/backoffice/bookings", label: "Réservations" }} />
        <Alert tone="danger" title="Réservation indisponible" action={<Button size="sm" variant="outline" onClick={() => void load()}>Réessayer</Button>}>{error}</Alert>
      </>
    );
  }
  if (!d) return <SkeletonPage />;
  return (
    <>
      <PageHeader title={`Réservation #${d.id}`} back={{ href: "/backoffice/bookings", label: "Réservations" }} description={`${d.service ?? "Intervention"} · ${dt(d.booking_date)}`}
        actions={d.can_cancel ? <Button variant="danger" size="sm" onClick={() => setCancel(true)}>Annuler la réservation</Button> : null} />
      {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}
      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Réservation">
          <KV items={[["Statut", <Tag key="s" value={d.status} label={STATUS_FR[d.status]} />], ["Version", d.version], ["Client", `${d.client}${d.client_phone ? ` · ${d.client_phone}` : ""}`], ["Artisan", `${d.artisan}${d.artisan_phone ? ` · ${d.artisan_phone}` : ""}`],
            ["Ville", d.city], ["Adresse", d.address ?? "Réservée aux rôles qui agissent sur les réservations"], ["Description", d.description || "—"], ["Créée le", dt(d.created_at)],
            ["Identité vérifiée à l’arrivée", d.identity_verified ? "Oui" : "Non"], ["Messages échangés", `${d.messages} (contenu non consultable)`]]} />
        </Section>
        <Section title="Paiement">
          {d.payment ? (
            <KV items={[["Statut", <Tag key="p" value={d.payment.status} label={STATUS_FR[d.payment.status] ?? d.payment.status} />], ["Moyen", d.payment.method],
              ...(d.payment.amount !== undefined ? ([["Montant", moneyLabel(d.payment.amount)], ["Commission", moneyLabel(d.payment.platform_fee)], ["Remboursé", moneyLabel(d.payment.refunded)]] as [string, string][]) : [["Montants", "Réservés aux rôles financiers"] as [string, string]])]} />
          ) : <p className="text-sm text-inkSoft">Aucun paiement enregistré pour cette réservation.</p>}
          {d.cash ? <div className="mt-4 border-t border-lineSoft pt-4"><h3 className="mb-2 text-sm font-bold text-ink">Espèces entre les parties</h3><CashBlock cash={d.cash} /></div> : null}
          {d.review ? <p className="mt-4 text-sm text-inkSoft">Avis client : {d.review.rating} / 5{d.review.hidden ? " (masqué)" : ""}.</p> : null}
        </Section>
        <Section title="Chronologie">
          <ol className="space-y-2 text-sm">
            {d.timeline.length ? d.timeline.map((t, i) => (
              <li key={i}><Tag value={t.status} label={STATUS_FR[t.status]} /> <span className="text-inkSoft">par {BY_FR[t.by] ?? t.by} · {dt(t.at)}{t.previous_status ? ` (depuis « ${STATUS_FR[t.previous_status] ?? t.previous_status} »)` : ""}</span></li>
            )) : <li className="text-inkSoft">Aucun changement de statut enregistré.</li>}
          </ol>
        </Section>
        <Section title="Litiges et suivi">
          {d.disputes.length ? <ul className="mb-3 space-y-1.5 text-sm">{d.disputes.map((x) => <li key={x.id}><a className="font-semibold text-primaryDark underline underline-offset-2" href={`/backoffice/bookings?tab=disputes&id=${x.id}`}>Litige #{x.id}</a> — {STATUS_FR[x.status] ?? x.status} · {dt(x.created_at)}</li>)}</ul> : <p className="mb-3 text-sm text-inkSoft">Aucun litige.</p>}
          {d.live ? <KV items={[["Partage de position (artisan)", d.live.artisan_sharing ? "Actif" : "Inactif"], ["En route", dt(d.live.en_route_at)], ["Arrivé", dt(d.live.arrived_at)]]} /> : <p className="text-sm text-inkSoft">Aucun suivi démarré.</p>}
        </Section>
        {d.history.length ? (
          <Section title="Décisions d’administration" className="lg:col-span-2">
            <ul className="divide-y divide-lineSoft text-sm">{d.history.map((h, i) => <li key={i} className="py-2"><strong>{h.action.replace("backoffice.", "")}</strong> — {h.by} · {dt(h.at)}{h.reason ? <span className="block text-inkSoft">Motif : {h.reason}</span> : null}</li>)}</ul>
          </Section>
        ) : null}
      </div>
      <ReasonModal open={cancel} title="Annuler cette réservation ?" description="L’annulation suit la politique de pénalité et l’escrow (remboursement net). Le client et l’artisan sont informés." confirmLabel="Annuler la réservation" tone="danger"
        onClose={() => setCancel(false)} request={postTo(`/bookings/${d.id}/cancel/`)} onDone={() => { setCancel(false); setNotice("Réservation annulée."); void load(); }} />
    </>
  );
}
