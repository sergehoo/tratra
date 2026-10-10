"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Alert, Button, PageHeader, SkeletonStats, Stat, type Column } from "@/components/ds";
import { bo, boError } from "@/lib/bo";
import { useBoList } from "@/lib/useBoList";
import { FilterBar, FilterSelect, ListView, STATUS_FR, Section, Tag, dt } from "../_components/ui";

interface Overview {
  active: { pending: number; confirmed: number; in_progress: number };
  stuck: Record<string, number>;
  stuck_labels: Record<string, string>;
  idempotent_writes_24h: { total: number; by_scope: Record<string, number> };
  sync: { push_failed_24h: number; push_queued_stuck: number; payouts_failed: number };
  devices: { total: number; active_7d: number };
}
interface Row { id: number; status: string; reason: string; service: string | null; client: string; artisan: string; booking_date: string; created_at: string; version: number; age_hours: number }
const SCOPE_FR: Record<string, string> = { "booking.create": "Créations de réservation", "booking.transition": "Changements de statut" };

export default function ContinuityPage() {
  const [o, setO] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [kind, setKind] = useState("");
  const list = useBoList<Row>("/continuity/stuck/", { kind });
  const load = useCallback(async () => {
    setError("");
    try { setO(await bo.get<Overview>("/continuity/overview/")); } catch (e) { setError(boError(e, "La vue de continuité n’a pas pu être chargée.")); }
  }, []);
  useEffect(() => void load(), [load]);

  const columns: Column<Row>[] = [
    { key: "id", header: "Réservation", primary: true, cell: (r) => <Link href={`/backoffice/bookings/${r.id}`} className="font-semibold text-primaryDark underline underline-offset-2">#{r.id}</Link> },
    { key: "status", header: "Statut", cell: (r) => <Tag value={r.status} label={STATUS_FR[r.status]} /> },
    { key: "reason", header: "Blocage détecté", cell: (r) => <span className="text-inkSoft">{r.reason}</span> },
    { key: "who", header: "Client → artisan", hideOnMobile: true, cell: (r) => `${r.client} → ${r.artisan}` },
    { key: "date", header: "Prévue le", hideOnMobile: true, cell: (r) => dt(r.booking_date) },
    { key: "age", header: "Ancienneté", align: "right", cell: (r) => `${r.age_hours} h` },
  ];
  const stuckTotal = o ? Object.values(o.stuck).reduce((a, b) => a + b, 0) : 0;
  return (
    <>
      <PageHeader title="Continuité des activités" description="Rien ne doit se perdre après une fermeture, une coupure ou un changement de téléphone. Cette vue est en lecture seule : l’administration ne force jamais l’état d’une activité."
        actions={<Button size="sm" variant="outline" onClick={() => { void load(); void list.reload(); }}>Actualiser</Button>} />
      {error ? <Alert tone="danger" className="mb-4" action={<Button size="sm" variant="outline" onClick={() => void load()}>Réessayer</Button>}>{error}</Alert> : null}
      {!o && !error ? <SkeletonStats count={4} className="mb-6 sm:grid-cols-2 lg:grid-cols-4" /> : null}
      {o ? (
        <>
          {stuckTotal ? <Alert tone="warning" className="mb-4" title="Activités à vérifier">{stuckTotal} activité(s) semblent bloquées : contactez les parties ou annulez via la réservation si nécessaire.</Alert> : <Alert tone="success" className="mb-4">Aucune activité bloquée détectée.</Alert>}
          <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="En attente" value={o.active.pending} hint={`${o.stuck.pending_old ?? 0} depuis plus de 24 h`} />
            <Stat label="Confirmées" value={o.active.confirmed} hint={`${o.stuck.confirmed_late ?? 0} en retard de démarrage`} tone="accent" />
            <Stat label="En cours" value={o.active.in_progress} hint={`${o.stuck.in_progress_long ?? 0} depuis plus de 24 h`} tone="night" />
            <Stat label="Appareils actifs (7 j)" value={o.devices.active_7d} hint={`${o.devices.total} enregistrés`} />
          </div>
          <div className="mb-6 grid gap-6 lg:grid-cols-2">
            <Section title="Écritures rejouables (24 h)">
              <p className="mb-2 text-sm text-inkSoft">Créations et changements de statut menés à terme avec une clé d’idempotence : un renvoi après coupure ou double appui n’a créé aucun doublon.</p>
              <p className="text-2xl font-extrabold text-ink">{o.idempotent_writes_24h.total}</p>
              <ul className="mt-2 text-sm text-inkSoft">{Object.entries(o.idempotent_writes_24h.by_scope).map(([k, v]) => <li key={k}>{SCOPE_FR[k] ?? k} : {v}</li>)}</ul>
            </Section>
            <Section title="Signaux de synchronisation">
              <ul className="space-y-1.5 text-sm">
                <li>Notifications push en échec (24 h) : <strong>{o.sync.push_failed_24h}</strong></li>
                <li>Notifications bloquées « en file » (&gt; 15 min) : <strong>{o.sync.push_queued_stuck}</strong></li>
                <li>Retraits échoués : <strong>{o.sync.payouts_failed}</strong></li>
              </ul>
              <p className="mt-3 text-xs text-ash">Détail des envois dans le module Notifications.</p>
            </Section>
          </div>
        </>
      ) : null}
      <FilterBar>
        <FilterSelect label="Type de blocage" value={kind} onChange={setKind} options={[["", "Tous"], ...Object.entries(o?.stuck_labels ?? {})]} />
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} caption="Activités bloquées" empty="Aucune activité bloquée." />
    </>
  );
}
