"use client";
import { useState } from "react";
import Link from "next/link";
import { ClipboardList, Plus } from "lucide-react";
import { Alert, ButtonLink, Card, CardHeader, EmptyState, PageHeader, SkeletonStats, Tabs } from "@/components/ds";
import { hours, money, pct, useBusiness, useOrgData, type Dashboard, type BizRequest } from "@/lib/business";
import { Bars, Kpi, PriorityPill, Progress, StatusPill } from "@/components/business/ui";

const PERIODS = [
  { id: "month", label: "Ce mois-ci" },
  { id: "90", label: "90 jours" },
  { id: "year", label: "Cette année" },
] as const;

function range(id: string): { from: string; to: string } {
  const now = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  if (id === "year") return { from: `${now.getFullYear()}-01-01`, to: iso(now) };
  if (id === "90") return { from: iso(new Date(now.getTime() - 90 * 86400000)), to: iso(now) };
  return { from: `${iso(now).slice(0, 8)}01`, to: iso(now) };
}

function Overview() {
  const { org, can } = useBusiness();
  const [period, setPeriod] = useState<(typeof PERIODS)[number]["id"]>("month");
  const { from, to } = range(period);
  const cur = org?.currency ?? "XOF";
  const stats = useOrgData<Dashboard>(can("reports.view") ? `dashboard/?from=${from}&to=${to}` : null, "Le tableau de bord ne peut pas être chargé.");
  const mine = useOrgData<{ results: BizRequest[] }>("requests/?mine=1&page_size=5");
  const d = stats.data;
  return (
    <>
      <PageHeader
        eyebrow="Tratra Business"
        title="Vue d’ensemble"
        description="Indicateurs calculés sur vos interventions réelles."
        actions={can("requests.create") ? <ButtonLink href="/dashboard/business/requests?new=1" leftIcon={<Plus aria-hidden className="h-4 w-4" />}>Nouvelle demande</ButtonLink> : null}
      />
      {can("reports.view") ? (
        <>
          <Tabs ariaLabel="Période" items={PERIODS.map((p) => ({ id: p.id, label: p.label }))} value={period} onChange={setPeriod} className="mb-4" />
          {stats.loading ? <SkeletonStats /> : stats.error ? <Alert tone="danger">{stats.error}</Alert> : d ? (
            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Kpi label="Demandes ouvertes" value={d.requests.open} hint={`${d.requests.created} créées sur la période`} />
                <Kpi label="En retard (SLA)" value={d.requests.overdue} tone={d.requests.overdue ? "danger" : "default"} hint="Échéance de résolution dépassée" />
                <Kpi label="Interventions terminées" value={d.requests.completed} />
                <Kpi label="À valider par moi" value={d.pending_my_approval} />
                <Kpi label="SLA prise en charge" value={pct(d.sla.response.rate)} hint={d.sla.response.measured ? `${d.sla.response.met} / ${d.sla.response.measured} mesurées` : "Pas encore mesuré"} />
                <Kpi label="SLA résolution" value={pct(d.sla.resolution.rate)} hint={d.sla.resolution.measured ? `${d.sla.resolution.met} / ${d.sla.resolution.measured} mesurées` : "Pas encore mesuré"} />
                <Kpi label="Délai moyen de résolution" value={hours(d.durations.avg_resolution_hours)} />
                <Kpi label="Dépenses" value={money(d.spend.total, cur)} hint={d.spend.unpriced_interventions ? `${d.spend.unpriced_interventions} intervention(s) sans montant` : undefined} />
              </div>
              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                <Card as="section" aria-label="Dépenses par site">
                  <CardHeader title="Dépenses par site" />
                  {d.spend.by_site.length ? <Bars rows={d.spend.by_site.map((s) => ({ label: s.name, value: Number(s.amount) }))} format={(n) => money(n, cur)} /> : <p className="text-sm text-ash">Aucune dépense sur la période.</p>}
                </Card>
                <Card as="section" aria-label="Dépenses par mois">
                  <CardHeader title="Dépenses par mois" />
                  {d.spend.by_month.length ? <Bars rows={d.spend.by_month.map((s) => ({ label: s.month, value: Number(s.amount) }))} format={(n) => money(n, cur)} /> : <p className="text-sm text-ash">Aucune dépense sur la période.</p>}
                </Card>
                <Card as="section" aria-label="Budgets">
                  <CardHeader title="Budgets en cours" action={can("budgets.manage") ? <Link href="/dashboard/business/budgets" className="text-sm font-semibold text-primaryDark hover:underline">Gérer</Link> : undefined} />
                  {d.budgets.length ? (
                    <ul className="space-y-4">
                      {d.budgets.map((b) => (
                        <li key={b.id} className="space-y-1.5">
                          <div className="flex justify-between gap-3 text-sm"><span className="font-medium text-ink">{b.name}</span><span className="text-inkSoft">{money(b.spent, cur)} / {money(b.amount, cur)}</span></div>
                          <Progress percent={b.percent} level={b.level} />
                        </li>
                      ))}
                    </ul>
                  ) : <p className="text-sm text-ash">Aucun budget actif.</p>}
                </Card>
                <Card as="section" aria-label="Maintenance préventive et équipements">
                  <CardHeader title="Préventif et équipements" />
                  <dl className="grid grid-cols-3 gap-3 text-center">
                    <div className="rounded-panel bg-canvas p-3"><dt className="text-xs text-ash">Plans actifs</dt><dd className="font-display text-xl font-bold">{d.preventive.active_plans}</dd></div>
                    <div className="rounded-panel bg-canvas p-3"><dt className="text-xs text-ash">En retard</dt><dd className={`font-display text-xl font-bold ${d.preventive.overdue ? "text-dangerInk" : ""}`}>{d.preventive.overdue}</dd></div>
                    <div className="rounded-panel bg-canvas p-3"><dt className="text-xs text-ash">Sous 30 jours</dt><dd className="font-display text-xl font-bold">{d.preventive.due_30_days}</dd></div>
                  </dl>
                  {d.top_equipment.length ? (
                    <div className="mt-4"><p className="mb-2 text-xs font-semibold text-ash">Équipements les plus sollicités</p>
                      <Bars rows={d.top_equipment.map((e) => ({ label: e.name, value: e.interventions }))} format={(n) => `${n} interv.`} /></div>
                  ) : null}
                </Card>
              </div>
            </div>
          ) : null}
        </>
      ) : null}

      <Card as="section" aria-label="Mes demandes" className="mt-6">
        <CardHeader icon={<ClipboardList className="h-5 w-5" />} title="Mes demandes récentes" action={<Link href="/dashboard/business/requests" className="text-sm font-semibold text-primaryDark hover:underline">Tout voir</Link>} />
        {mine.data?.results.length ? (
          <ul className="divide-y divide-lineSoft">
            {mine.data.results.map((r) => (
              <li key={r.id}>
                <Link href={`/dashboard/business/requests/${r.id}`} className="flex flex-wrap items-center justify-between gap-2 py-3 hover:bg-canvas">
                  <span className="min-w-0"><span className="block truncate font-semibold text-ink">{r.title}</span><span className="text-xs text-ash">{r.number} · {r.site_name}</span></span>
                  <span className="flex items-center gap-2"><PriorityPill priority={r.priority} /><StatusPill status={r.status} /></span>
                </Link>
              </li>
            ))}
          </ul>
        ) : mine.loading ? null : <EmptyState title="Aucune demande" description="Signalez un problème sur un équipement ou créez une demande d’intervention." />}
      </Card>
    </>
  );
}

export default function BusinessHome() {
  return <Overview />;
}
