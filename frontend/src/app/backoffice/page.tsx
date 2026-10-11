"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowRight, CalendarCheck, Hammer, MapPin, Users, Wallet } from "lucide-react";
import { Alert, Button, Card, PageHeader, SkeletonStats } from "@/components/ds";
import { bo, boError, moneyLabel, pct } from "@/lib/bo";
import type { Dashboard } from "@/lib/boDashboard";
import { Bars, Kpi, KpiGrid, Section, STATUS_FR, dt } from "./_components/ui";

/** Indicateurs RÉELS filtrés par droit : une section absente = le rôle n'a pas le droit de la consulter. */
export default function BackOfficeHome() {
  const [d, setD] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setD(await bo.get<Dashboard>("/dashboard/"));
    } catch (e) {
      setError(boError(e, "Le tableau de bord n’a pas pu être chargé."));
    }
  }, []);
  useEffect(() => void load(), [load]);

  if (error && !d) {
    return (
      <>
        <PageHeader title="Tableau de bord" />
        <Alert tone="danger" title="Tableau de bord indisponible" action={<Button size="sm" variant="outline" onClick={() => void load()}>Réessayer</Button>}>{error}</Alert>
      </>
    );
  }
  if (!d) {
    return (
      <>
        <PageHeader title="Tableau de bord" />
        <SkeletonStats count={4} className="sm:grid-cols-2 lg:grid-cols-4" />
      </>
    );
  }
  const { users, bookings, finance, live } = d.kpis;
  return (
    <>
      <PageHeader
        title="Tableau de bord"
        description={`Données réelles au ${dt(d.generated_at)}.`}
        actions={<Button size="sm" variant="outline" onClick={() => void load()}>Actualiser</Button>}
      />

      {d.alerts.length ? (
        <Section title="À traiter" className="mb-6">
          <ul className="grid gap-2 sm:grid-cols-2">
            {d.alerts.map((a) => (
              <li key={a.key}>
                <Link href={a.href} className="flex min-h-[48px] items-center justify-between gap-3 rounded-panel border border-lineSoft px-4 py-2.5 text-sm font-semibold text-ink transition hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
                  <span className="flex items-center gap-2.5">
                    <AlertTriangle aria-hidden className={a.severity === "danger" ? "h-4 w-4 text-danger" : "h-4 w-4 text-warning"} />
                    {a.label}
                  </span>
                  <span className="flex items-center gap-2">
                    <span className="rounded-full bg-accent px-2.5 py-0.5 text-xs font-bold text-ink">{a.count}</span>
                    <ArrowRight aria-hidden className="h-4 w-4 text-ash" />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      ) : (
        <Alert tone="success" className="mb-6">Rien à traiter pour votre rôle en ce moment.</Alert>
      )}

      <KpiGrid className="mb-6">
        {users ? <Kpi href="/backoffice/users" icon={<Users className="h-5 w-5" />} label="Utilisateurs" value={users.total} hint={`${users.new_7d} nouveaux sur 7 jours`} /> : null}
        {users ? <Kpi icon={<Hammer className="h-5 w-5" />} tone="accent" label="Artisans approuvés" value={`${users.artisans_approved}\u00A0/\u00A0${users.artisans}`} hint="Profils approuvés par l’équipe" /> : null}
        {bookings ? <Kpi href="/backoffice/bookings" icon={<CalendarCheck className="h-5 w-5" />} label="Réservations en cours" value={bookings.active} hint={`${bookings.completed_30d} terminées sur 30 jours`} /> : null}
        {live ? <Kpi icon={<MapPin className="h-5 w-5" />} tone="night" label="Suivis actifs" value={live.sharing_sessions} hint="Artisans qui partagent leur position" /> : null}
      </KpiGrid>

      {finance ? (
        <Section title="Finances — 30 derniers jours" className="mb-6" actions={<Link href="/backoffice/finance" className="text-sm font-semibold text-primaryDark underline underline-offset-2">Détail</Link>}>
          <KpiGrid>
            <Kpi icon={<Wallet className="h-5 w-5" />} label="Volume payé" value={moneyLabel(finance.gmv_30d)} />
            <Kpi label="Commissions" value={moneyLabel(finance.commission_30d)} tone="accent" />
            <Kpi label="Sous séquestre" value={moneyLabel(finance.escrow_held)} tone="night" />
            <Kpi label="Retraits en attente" value={finance.payouts_pending} hint={moneyLabel(finance.payouts_pending_amount)} href="/backoffice/finance?tab=payouts" />
          </KpiGrid>
        </Section>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        {d.series.bookings ? (
          <Section title="Réservations créées">
            <Bars data={d.series.bookings} label="Réservations (30 j)" />
            {bookings ? (
              <ul className="mt-4 flex flex-wrap gap-2 text-xs text-inkSoft">
                {Object.entries(bookings.by_status).map(([s, n]) => (
                  <li key={s} className="rounded-full bg-canvas px-3 py-1">{STATUS_FR[s] ?? s} : <strong>{n}</strong></li>
                ))}
              </ul>
            ) : null}
          </Section>
        ) : null}
        {d.series.signups ? (
          <Section title="Inscriptions">
            <Bars data={d.series.signups} label="Inscriptions (30 j)" color="#F6C90E" />
            {users ? <p className="mt-4 text-xs text-inkSoft">{users.new_30d} nouveaux comptes sur 30 jours · {pct(users.artisans ? users.artisans_approved / users.artisans : null)} d’artisans approuvés.</p> : null}
          </Section>
        ) : null}
      </div>
      {!users && !bookings && !finance && !live ? (
        <Card padding="md" radius="card" className="mt-6"><p className="text-sm text-inkSoft">Votre rôle n’ouvre aucun indicateur sur cette page : utilisez le menu pour accéder à vos modules.</p></Card>
      ) : null}
    </>
  );
}
