"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Activity, CalendarCheck, Eye, Smartphone, Timer } from "lucide-react";
import { Alert, Button, PageHeader, SkeletonStats } from "@/components/ds";
import { bo, boError } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useManagedList } from "@/lib/useBoList";
import { FilterBar, FilterSelect, Kpi, KpiGrid, ListView, STATUS_FR, Section, Tag, dd, type BoColumn, type RowAction } from "../_components/ui";

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
  const { can } = useBo();
  const [o, setO] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const m = useManagedList<Row, { kind: string }>("/continuity/stuck/", { kind: "" });
  const { values: f, list } = m;
  const load = useCallback(async () => {
    setError("");
    try { setO(await bo.get<Overview>("/continuity/overview/")); } catch (e) { setError(boError(e, "La vue de continuité n’a pas pu être chargée.")); }
  }, []);
  useEffect(() => void load(), [load]);

  const columns: BoColumn<Row>[] = [
    { key: "id", header: "Réservation", primary: true, cell: (r) => <Link href={`/backoffice/bookings/${r.id}`} className="font-semibold text-primaryDark underline underline-offset-2">#{r.id}</Link> },
    { key: "status", header: "Statut", cell: (r) => <Tag value={r.status} label={STATUS_FR[r.status]} /> },
    { key: "reason", header: "Blocage détecté", wrap: true, cell: (r) => <span className="text-inkSoft">{r.reason}</span> },
    { key: "who", header: "Client → artisan", hideOnMobile: true, from: "xl", cell: (r) => `${r.client} → ${r.artisan}` },
    { key: "date", header: "Prévue le", hideOnMobile: true, from: "lg", cell: (r) => dd(r.booking_date) },
    { key: "age", header: "Ancienneté", align: "right", cell: (r) => `${r.age_hours} h` },
  ];
  const rowActions = (r: Row): RowAction[] => [
    { label: "Ouvrir la réservation", icon: Eye, href: `/backoffice/bookings/${r.id}`, hidden: !can("bookings.view") },
    { label: "Dossier support des parties", icon: CalendarCheck, href: `/backoffice/support`, hidden: !can("support.manage") },
  ];
  const stuckTotal = o ? Object.values(o.stuck).reduce((a, b) => a + b, 0) : 0;
  return (
    <>
      <PageHeader title="Continuité des activités" description="Rien ne doit se perdre après une fermeture, une coupure ou un changement de téléphone. Cette vue est en lecture seule : l’administration ne force jamais l’état d’une activité." />
      {error ? <Alert tone="danger" className="mb-4" action={<Button size="sm" variant="outline" onClick={() => void load()}>Réessayer</Button>}>{error}</Alert> : null}
      {!o && !error ? <SkeletonStats count={4} className="mb-6 sm:grid-cols-2 lg:grid-cols-4" /> : null}
      {o ? (
        <>
          {stuckTotal ? <Alert tone="warning" className="mb-4" title="Activités à vérifier">{stuckTotal} activité(s) semblent bloquées : contactez les parties ou annulez via la réservation si nécessaire.</Alert> : <Alert tone="success" className="mb-4">Aucune activité bloquée détectée.</Alert>}
          <KpiGrid className="mb-6">
            <Kpi icon={<Timer className="h-5 w-5" />} label="En attente" value={o.active.pending} hint={`${o.stuck.pending_old ?? 0} depuis plus de 24 h`} />
            <Kpi icon={<CalendarCheck className="h-5 w-5" />} tone="accent" label="Confirmées" value={o.active.confirmed} hint={`${o.stuck.confirmed_late ?? 0} en retard de démarrage`} />
            <Kpi icon={<Activity className="h-5 w-5" />} tone="night" label="En cours" value={o.active.in_progress} hint={`${o.stuck.in_progress_long ?? 0} depuis plus de 24 h`} />
            <Kpi icon={<Smartphone className="h-5 w-5" />} label="Appareils actifs (7 j)" value={o.devices.active_7d} hint={`${o.devices.total} enregistrés`} />
          </KpiGrid>
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
      <FilterBar activeCount={m.activeCount} onReset={m.reset} onRefresh={() => { void load(); void list.reload(); }} refreshing={list.loading}>
        <FilterSelect label="Type de blocage" value={f.kind} onChange={(v) => m.set({ kind: v })} options={[["", "Tous"], ...Object.entries(o?.stuck_labels ?? {})]} />
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => `réservation #${r.id}`} caption="Activités bloquées" empty="Aucune activité bloquée." emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        rowActions={rowActions} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
    </>
  );
}
