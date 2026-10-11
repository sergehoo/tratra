"use client";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Ban, Gavel, UserRound } from "lucide-react";
import { Alert, Badge, Button, PageHeader, SkeletonPage } from "@/components/ds";
import { bo, boError, moneyLabel } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { CashBlock } from "../../_components/CashBlock";
import { useCrumb } from "../../_components/crumbs";
import { Fiche, Pane, Restricted } from "../../_components/fiche";
import { KV, ReasonModal, Section, STATUS_FR, Tag, dd, dt, postTo } from "../../_components/ui";
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
  const { can } = useBo();
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [cancel, setCancel] = useState(false);
  const [notice, setNotice] = useState("");
  useCrumb(d ? `Réservation #${d.id}` : null);

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
  const usersView = can("users.view");

  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <Fiche
        name={`Réservation #${d.id}`}
        eyebrow="Réservation"
        subtitle={`${d.service ?? "Intervention"} · ${dt(d.booking_date)}`}
        badges={<><Tag value={d.status} label={STATUS_FR[d.status]} />{d.payment ? <Tag value={d.payment.status} label={`Paiement : ${STATUS_FR[d.payment.status] ?? d.payment.status}`} /> : null}{d.disputes.length ? <Badge tone="danger">{d.disputes.length} litige(s)</Badge> : null}{d.identity_verified ? <Badge tone="success">Identité vérifiée</Badge> : null}</>}
        facts={[["Client", d.client], ["Artisan", d.artisan], ["Ville", d.city], ["Créée le", dd(d.created_at)]]}
        actions={d.can_cancel ? <Button variant="danger" size="sm" leftIcon={<Ban aria-hidden className="h-4 w-4" />} onClick={() => setCancel(true)}>Annuler la réservation</Button> : null}
        tabs={[
          {
            id: "general", label: "Informations générales", content: (
              <Pane>
                <Section title="Réservation">
                  <KV items={[["Statut", <Tag key="s" value={d.status} label={STATUS_FR[d.status]} />], ["Version", d.version], ["Client", `${d.client}${d.client_phone ? ` · ${d.client_phone}` : ""}`], ["Artisan", `${d.artisan}${d.artisan_phone ? ` · ${d.artisan_phone}` : ""}`],
                    ["Ville", d.city], ["Adresse", d.address ?? "Réservée aux rôles qui agissent sur les réservations"], ["Description", d.description || "—"], ["Créée le", dt(d.created_at)],
                    ["Identité vérifiée à l’arrivée", d.identity_verified ? "Oui" : "Non"], ["Messages échangés", `${d.messages} (contenu non consultable)`]]} />
                </Section>
                <Section title="Suivi de l’intervention">
                  {d.live ? <KV items={[["Partage de position (artisan)", d.live.artisan_sharing ? "Actif" : "Inactif"], ["En route", dt(d.live.en_route_at)], ["Arrivé", dt(d.live.arrived_at)]]} /> : <p className="text-sm text-inkSoft">Aucun suivi démarré.</p>}
                </Section>
              </Pane>
            ),
          },
          {
            id: "activity", label: "Activités et historique", count: d.timeline.length || undefined, content: (
              <Pane>
                <Section title="Chronologie">
                  <ol className="space-y-2 text-sm">
                    {d.timeline.length ? d.timeline.map((t, i) => (
                      <li key={i}><Tag value={t.status} label={STATUS_FR[t.status]} /> <span className="text-inkSoft">par {BY_FR[t.by] ?? t.by} · {dt(t.at)}{t.previous_status ? ` (depuis « ${STATUS_FR[t.previous_status] ?? t.previous_status} »)` : ""}</span></li>
                    )) : <li className="text-inkSoft">Aucun changement de statut enregistré.</li>}
                  </ol>
                </Section>
                <Section title="Litiges" actions={d.disputes.length ? <Link href={`/backoffice/bookings?tab=disputes&q=${d.id}`} className="text-sm font-semibold text-primaryDark underline underline-offset-2">Voir dans le module</Link> : undefined}>
                  {d.disputes.length ? <ul className="space-y-1.5 text-sm">{d.disputes.map((x) => <li key={x.id}><Link className="font-semibold text-primaryDark underline underline-offset-2" href={`/backoffice/bookings?tab=disputes&id=${x.id}`}>Litige #{x.id}</Link> — {STATUS_FR[x.status] ?? x.status} · {dt(x.created_at)}</li>)}</ul> : <p className="text-sm text-inkSoft">Aucun litige.</p>}
                </Section>
              </Pane>
            ),
          },
          {
            id: "documents", label: "Documents et justificatifs", content: (
              <Pane>
                <Section title="Avis client">
                  {d.review ? <p className="text-sm text-inkSoft">Note : <strong className="text-ink">{d.review.rating} / 5</strong>{d.review.hidden ? " (avis masqué)" : ""}. {can("reviews.moderate") ? <Link className="font-semibold text-primaryDark underline underline-offset-2" href={`/backoffice/reviews?q=${d.id}`}>Modérer</Link> : null}</p> : <p className="text-sm text-inkSoft">Aucun avis déposé.</p>}
                </Section>
                <Section title="Justificatif d’espèces">
                  {d.cash ? <CashBlock cash={d.cash} /> : <p className="text-sm text-inkSoft">Aucune déclaration d’espèces pour cette réservation.</p>}
                  <p className="mt-3 text-xs text-ash">Le justificatif facultatif reste privé : seules les deux parties y ont accès, jamais le Back-Office.</p>
                </Section>
              </Pane>
            ),
          },
          {
            id: "money", label: "Paiements et engagements", content: (
              <Pane columns={1}>
                <Section title="Paiement">
                  {d.payment ? (
                    <KV items={[["Statut", <Tag key="p" value={d.payment.status} label={STATUS_FR[d.payment.status] ?? d.payment.status} />], ["Moyen", d.payment.method],
                      ...(d.payment.amount !== undefined ? ([["Montant", moneyLabel(d.payment.amount)], ["Commission", moneyLabel(d.payment.platform_fee)], ["Remboursé", moneyLabel(d.payment.refunded)]] as [string, string][]) : [["Montants", "Réservés aux rôles financiers"] as [string, string]])]} />
                  ) : <p className="text-sm text-inkSoft">Aucun paiement enregistré pour cette réservation.</p>}
                  {can("finance.view") && d.payment ? <p className="mt-3"><Link className="text-sm font-semibold text-primaryDark underline underline-offset-2" href={`/backoffice/finance?tab=payments&q=${d.id}`}>Détail et remboursement dans Finances</Link></p> : null}
                </Section>
              </Pane>
            ),
          },
          {
            id: "notes", label: "Notes internes et audit", content: (
              <Section title="Décisions d’administration">
                {d.history.length ? <ul className="divide-y divide-lineSoft text-sm">{d.history.map((h, i) => <li key={i} className="py-2"><strong>{h.action.replace("backoffice.", "")}</strong> — {h.by} · {dt(h.at)}{h.reason ? <span className="block text-inkSoft">Motif : {h.reason}</span> : null}</li>)}</ul> : <p className="text-sm text-inkSoft">Aucune décision d’administration sur cette réservation.</p>}
                <p className="mt-3 text-xs text-ash">Les notes internes se rédigent sur la fiche du compte concerné (module Support).</p>
              </Section>
            ),
          },
          {
            id: "actions", label: "Actions administratives", content: (
              <Pane>
                <Section title="Décision">
                  {d.can_cancel ? (
                    <div className="space-y-3">
                      <Button variant="danger" leftIcon={<Ban aria-hidden className="h-4 w-4" />} onClick={() => setCancel(true)}>Annuler la réservation</Button>
                      <p className="text-xs text-ash">L’annulation suit la politique de pénalité et l’escrow (remboursement net). Le client et l’artisan sont informés.</p>
                    </div>
                  ) : can("bookings.manage") ? <p className="text-sm text-inkSoft">Cette réservation ne peut plus être annulée dans son état actuel.</p> : <Restricted right="bookings.manage">Annuler une réservation.</Restricted>}
                </Section>
                <Section title="Parties et liens">
                  <ul className="space-y-2 text-sm font-semibold text-primaryDark">
                    {usersView ? <li><Link className="inline-flex items-center gap-2 underline underline-offset-2" href={`/backoffice/users/${d.client_id}`}><UserRound aria-hidden className="h-4 w-4" />Fiche du client — {d.client}</Link></li> : null}
                    {usersView ? <li><Link className="inline-flex items-center gap-2 underline underline-offset-2" href={`/backoffice/users/${d.artisan_id}`}><UserRound aria-hidden className="h-4 w-4" />Fiche de l’artisan — {d.artisan}</Link></li> : null}
                    <li><Link className="inline-flex items-center gap-2 underline underline-offset-2" href={`/backoffice/bookings?tab=disputes&q=${d.id}`}><Gavel aria-hidden className="h-4 w-4" />Litiges de cette réservation</Link></li>
                  </ul>
                </Section>
              </Pane>
            ),
          },
        ]}
      />
      <ReasonModal open={cancel} title="Annuler cette réservation ?" description="L’annulation suit la politique de pénalité et l’escrow (remboursement net). Le client et l’artisan sont informés." confirmLabel="Annuler la réservation" tone="danger"
        onClose={() => setCancel(false)} request={postTo(`/bookings/${d.id}/cancel/`)} onDone={() => { setCancel(false); setNotice("Réservation annulée."); void load(); }} />
    </>
  );
}
