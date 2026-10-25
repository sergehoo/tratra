"use client";
import Link from "next/link";
import { useState } from "react";
import { MapPin, Search, ShieldCheck } from "lucide-react";
import { Alert, Badge, Button, Card, EmptyState, PageHeader, SelectField, StatusBadge, TextField } from "@/components/ds";
import { MISSION_TYPE_FR, PERIOD_FR, RELATIONSHIP_FR, dateFr, eng, fcfa, scheduleLabel, type Page, type Posting } from "@/lib/engagements";
import { useDebouncedValue } from "../_components/useDebouncedValue";
import { LoadState, useLoad } from "../_components/common";
import { ReceivedInvitations } from "../_components/Invitations";
import { useTermsContext } from "../_components/useTermsContext";

/** Offres ouvertes : le serveur filtre ; « Postuler » n'apparaît que si le profil est vérifié (sinon la raison est expliquée). */
export default function OffersPage() {
  const ctx = useTermsContext();
  const [q, setQ] = useState("");
  const [city, setCity] = useState("");
  const [category, setCategory] = useState("");
  const [type, setType] = useState("");
  const dq = useDebouncedValue(q);
  const dcity = useDebouncedValue(city);
  const params = new URLSearchParams({ limit: "30" });
  if (dq.trim()) params.set("q", dq.trim());
  if (dcity.trim()) params.set("city", dcity.trim());
  if (category) params.set("category", category);
  if (type) params.set("mission_type", type);
  const { data, error, loading, reload } = useLoad(() => eng.get<Page<Posting>>(`/postings/?${params.toString()}`), [params.toString()]);
  const blocked = data?.results.some((p) => !p.mine && !p.applied && p.can_apply === false);
  return (
    <>
      <PageHeader back={{ href: "/dashboard/engagements", label: "Engagements" }} title="Offres de longue durée"
        description="Missions régulières ou sur plusieurs mois. Chaque offre est publiée par un compte Tratra ; postuler exige un profil vérifié." />
      <ReceivedInvitations onResponded={() => void reload()} />
      <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <TextField label="Recherche" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Gardien, ménage, jardinier…" leading={<Search className="h-4 w-4" />} />
        <TextField label="Ville" value={city} onChange={(e) => setCity(e.target.value)} />
        <SelectField label="Métier" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">Tous</option>
          {ctx.categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </SelectField>
        <SelectField label="Type" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">Tous</option>
          <option value="recurring">{MISSION_TYPE_FR.recurring}</option>
          <option value="long_term">{MISSION_TYPE_FR.long_term}</option>
        </SelectField>
      </div>
      {blocked ? (
        <Alert tone="info" className="mb-5" icon={<ShieldCheck />} title="Postuler demande un profil vérifié">
          Complétez votre profil professionnel et votre vérification d’identité : <Link href="/dashboard/profile/kyc">ouvrir mon dossier</Link>.
        </Alert>
      ) : null}
      <LoadState loading={loading} error={error} hasData={Boolean(data)} reload={() => void reload()}>
        {data && data.results.length === 0 ? (
          <EmptyState icon={<Search aria-hidden />} title="Aucune offre ne correspond" description="Modifiez vos filtres, ou revenez plus tard : les offres sont publiées par des utilisateurs réels, aucune n’est affichée par défaut." />
        ) : (
          <ul className="grid gap-3">
            {data?.results.map((p) => (
              <li key={p.id}>
                <Link href={`/dashboard/engagements/postings/${p.id}`} className="block rounded-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2">
                  <Card interactive padding="none" className="p-4 sm:p-5">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <h2 className="min-w-0 font-display text-base font-bold text-ink">{p.title}</h2>
                      <div className="flex flex-wrap gap-1.5">
                        {p.mine ? <Badge tone="gray">Mon offre</Badge> : null}
                        {p.applied ? <Badge tone="info">Candidature envoyée</Badge> : null}
                        {p.work_relationship === "employment" ? <Badge tone="warning">{RELATIONSHIP_FR.employment}</Badge> : null}
                      </div>
                    </div>
                    <p className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ash">
                      <span>{p.category.name}</span>
                      <span className="inline-flex items-center gap-1"><MapPin aria-hidden className="h-4 w-4" />{p.city}</span>
                      <span>{MISSION_TYPE_FR[p.mission_type]}</span>
                      {p.start_date ? <span>dès le {dateFr(p.start_date)}</span> : null}
                    </p>
                    <p className="mt-2 text-sm font-semibold text-ink">{fcfa(p.amount, p.currency)} {PERIOD_FR[p.period]}</p>
                    <p className="mt-0.5 text-xs text-ash">{scheduleLabel(p.schedule)} · publié par {p.organization?.name ?? p.publisher?.name ?? "un utilisateur Tratra"}</p>
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </LoadState>
      <p className="mt-6 text-xs text-ash">Le statut de chaque offre est géré par son auteur. <StatusBadge kind="posting" status="open" className="ml-1" /> = ouverte aux candidatures.</p>
    </>
  );
}
