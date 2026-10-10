"use client";
import { useCallback, useEffect, useState } from "react";
import { Download } from "lucide-react";
import { Alert, Button, PageHeader, SkeletonStats, Stat } from "@/components/ds";
import { apiFetch } from "@/lib/api";
import { bo, boError, moneyLabel, pct } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { Bars, DateRange, FilterBar, Section, STATUS_FR } from "../_components/ui";

interface Overview {
  range: { from: string; to: string };
  signups: { date: string; count: number }[];
  bookings: { total: number; by_status: Record<string, number>; daily: { date: string; count: number }[]; completion_rate: number | null; cancellation_rate: number | null; dispute_rate: number | null };
  top_categories: { name: string; bookings: number }[];
  top_cities: { name: string; bookings: number }[];
  active_artisans: number;
  reviews: { count: number; average: number | null };
  finance?: { gmv: string; commission: string; average_basket: string; paid_share: number | null };
}

const EXPORTS: { id: string; label: string; needs: string; hint: string }[] = [
  { id: "users", label: "Utilisateurs", needs: "users.view", hint: "Sans téléphone ni e-mail" },
  { id: "bookings", label: "Réservations", needs: "bookings.view", hint: "Montants si vous avez le droit finance" },
  { id: "payments", label: "Paiements", needs: "finance.view", hint: "Sans référence du prestataire" },
  { id: "reviews", label: "Avis", needs: "reviews.moderate", hint: "Notes seulement, sans commentaire" },
  { id: "audit", label: "Journal d’audit", needs: "security.manage", hint: "Qui a fait quoi, quand" },
];

function BarList({ rows, total }: { rows: { name: string; bookings: number }[]; total: number }) {
  if (!rows.length) return <p className="text-sm text-inkSoft">Aucune donnée sur la période.</p>;
  return (
    <ul className="space-y-2">
      {rows.map((r) => (
        <li key={r.name} className="text-sm">
          <span className="flex justify-between"><span className="text-ink">{r.name}</span><span className="font-semibold">{r.bookings}</span></span>
          <span aria-hidden className="mt-1 block h-1.5 rounded-full bg-lineSoft"><span className="block h-1.5 rounded-full bg-primary" style={{ width: `${total ? Math.round((r.bookings / total) * 100) : 0}%` }} /></span>
        </li>
      ))}
    </ul>
  );
}

export default function AnalyticsPage() {
  const { can } = useBo();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [d, setD] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setError("");
    try { setD(await bo.get<Overview>(`/analytics/overview/?${new URLSearchParams({ ...(from ? { from } : {}), ...(to ? { to } : {}) })}`)); } catch (e) { setError(boError(e, "Les statistiques n’ont pas pu être chargées.")); }
  }, [from, to]);
  useEffect(() => void load(), [load]);

  async function download(id: string) {
    setBusy(id);
    setNotice("");
    setError("");
    try {
      const qs = new URLSearchParams({ ...(from ? { from } : {}), ...(to ? { to } : {}) }).toString();
      const res = await apiFetch(`/backoffice/analytics/export/${id}/${qs ? `?${qs}` : ""}`);
      if (!res.ok) throw new Error(String(res.status));
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `tratra-${id}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      setNotice("Export téléchargé. Il est journalisé dans l’audit ; traitez-le comme une donnée confidentielle.");
    } catch (e) {
      setError(e instanceof Error && e.message === "403" ? "Droits insuffisants pour cet export." : "L’export n’a pas pu être téléchargé.");
    } finally {
      setBusy(null);
    }
  }

  const b = d?.bookings;
  const catTotal = d?.top_categories.reduce((s, r) => s + r.bookings, 0) ?? 0;
  const cityTotal = d?.top_cities.reduce((s, r) => s + r.bookings, 0) ?? 0;
  return (
    <>
      <PageHeader title="Statistiques et exports" description="Indicateurs agrégés sur la période choisie (30 derniers jours par défaut). Aucune donnée personnelle ; les montants exigent le droit finance." />
      <FilterBar><DateRange from={from} to={to} onFrom={setFrom} onTo={setTo} /></FilterBar>
      {error ? <Alert tone="danger" className="mb-4" action={<Button size="sm" variant="outline" onClick={() => void load()}>Réessayer</Button>}>{error}</Alert> : null}
      {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}
      {!d && !error ? <SkeletonStats count={4} className="mb-6 sm:grid-cols-2 lg:grid-cols-4" /> : null}
      {d && b ? (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Réservations" value={b.total} hint={`du ${d.range.from} au ${d.range.to}`} />
            <Stat label="Taux de réalisation" value={pct(b.completion_rate)} hint={`${b.by_status.completed ?? 0} terminées`} tone="accent" />
            <Stat label="Taux d’annulation" value={pct(b.cancellation_rate)} hint={`${b.by_status.cancelled ?? 0} annulées`} tone="night" />
            <Stat label="Artisans actifs" value={d.active_artisans} hint={`Taux de litige : ${pct(b.dispute_rate)}`} />
          </div>
          {d.finance ? (
            <Section title="Finances" className="mb-6">
              <div className="grid gap-4 sm:grid-cols-4">
                <Stat label="Volume payé" value={moneyLabel(d.finance.gmv)} /><Stat label="Commissions" value={moneyLabel(d.finance.commission)} tone="accent" />
                <Stat label="Panier moyen" value={moneyLabel(d.finance.average_basket)} tone="night" /><Stat label="Réservations payées" value={pct(d.finance.paid_share)} />
              </div>
            </Section>
          ) : null}
          <div className="mb-6 grid gap-6 lg:grid-cols-2">
            <Section title="Réservations créées par jour"><Bars data={b.daily} label="Réservations" />
              <p className="mt-3 flex flex-wrap gap-2 text-xs">{Object.entries(b.by_status).map(([s, n]) => <span key={s} className="rounded-full bg-canvas px-3 py-1">{STATUS_FR[s] ?? s} : <strong>{n}</strong></span>)}</p></Section>
            <Section title="Inscriptions par jour"><Bars data={d.signups} label="Inscriptions" color="#F6C90E" />
              <p className="mt-3 text-xs text-inkSoft">Avis publiés sur la période : {d.reviews.count}{d.reviews.average !== null ? ` · note moyenne ${d.reviews.average} / 5` : ""}.</p></Section>
            <Section title="Catégories les plus demandées"><BarList rows={d.top_categories} total={catTotal} /></Section>
            <Section title="Villes les plus actives"><BarList rows={d.top_cities} total={cityTotal} /></Section>
          </div>
        </>
      ) : null}
      <Section title="Exports CSV" actions={<span className="text-xs text-ash">Période ci-dessus appliquée · 50 000 lignes maximum</span>}>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {EXPORTS.filter((x) => can(x.needs)).map((x) => (
            <li key={x.id} className="flex items-center justify-between gap-3 rounded-panel border border-lineSoft p-3">
              <span className="min-w-0"><span className="block text-sm font-semibold text-ink">{x.label}</span><span className="block text-xs text-ash">{x.hint}</span></span>
              <Button size="sm" variant="outline" loading={busy === x.id} leftIcon={<Download aria-hidden className="h-4 w-4" />} onClick={() => void download(x.id)}>CSV</Button>
            </li>
          ))}
        </ul>
        {!EXPORTS.some((x) => can(x.needs)) ? <p className="text-sm text-inkSoft">Votre rôle ne donne accès à aucun export.</p> : null}
      </Section>
    </>
  );
}
