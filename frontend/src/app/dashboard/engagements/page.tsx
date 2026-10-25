"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowRight, Briefcase, CalendarClock, FilePlus2, FileSignature, ListChecks, Search, Users } from "lucide-react";
import { Alert, Button, ButtonLink, Card, CardHeader, EmptyState, PageHeader, StatusBadge, Tabs } from "@/components/ds";
import {
  PERIOD_FR, contractStatusKey, dateFr, durationLabel, eng, fcfa, MISSION_TYPE_FR, type Application, type Contract, type Overview, type Page, type Posting,
} from "@/lib/engagements";
import { LoadState, useLoad } from "./_components/common";
import { todoHref } from "./_components/todo";

type Tab = "contracts" | "postings" | "applications";

function TodoCard({ overview }: { overview: Overview }) {
  if (overview.todo.length === 0) return null;
  return (
    <Card padding="md" className="mb-6">
      <CardHeader title="À faire" description="Ce qui attend une réponse de votre part." icon={<ListChecks className="h-5 w-5" />} />
      <ul className="divide-y divide-lineSoft">
        {overview.todo.map((t, i) => (
          <li key={`${t.kind}-${t.contract_id}-${t.installment_id ?? t.event_id ?? t.posting_id ?? i}`}>
            <Link href={todoHref(t)} className="flex items-center justify-between gap-3 py-3 text-sm hover:text-primaryDark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
              <span className="min-w-0">
                <span className="block font-semibold text-ink">{t.label}</span>
                <span className="block truncate text-xs text-ash">{t.title}{t.at ? ` · ${dateFr(t.at.slice(0, 10))}` : ""}</span>
              </span>
              <ArrowRight aria-hidden className="h-4 w-4 shrink-0 text-ash" />
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function ContractRow({ c }: { c: Contract }) {
  return (
    <li>
      <Link href={`/dashboard/engagements/contracts/${c.id}`} className="group block rounded-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2">
        <Card interactive padding="none" className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4 sm:p-5">
          <span aria-hidden className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-primarySoft text-primary"><FileSignature className="h-6 w-6" /></span>
          <div className="min-w-0 flex-1">
            <h2 className="truncate font-display text-base font-bold text-ink">{c.title}</h2>
            <p className="mt-1 text-sm text-ash">
              {c.my_role === "worker" ? "Pour" : "Avec"} {c.counterpart.name}{c.organization ? ` · ${c.organization.name}` : ""} · {MISSION_TYPE_FR[c.mission_type]}
            </p>
            <p className="mt-1 text-sm text-inkSoft">
              {fcfa(c.amount, c.currency)} {PERIOD_FR[c.period]} · {durationLabel(c)} · dès le {dateFr(c.start_date)}
            </p>
          </div>
          <StatusBadge kind="contract" status={contractStatusKey(c)} />
        </Card>
      </Link>
    </li>
  );
}

function Contracts() {
  const [filter, setFilter] = useState<"live" | "ended">("live");
  const live = "pending_acceptance,accepted,signed,active,suspended,notice,draft";
  const ended = "terminated,completed,cancelled";
  const { data, error, loading, reload } = useLoad(() => eng.get<Page<Contract>>(`/contracts/?status=${filter === "live" ? live : ended}&limit=50`), [filter]);
  return (
    <>
      <Tabs ariaLabel="Contrats" value={filter} onChange={setFilter} className="mb-4" items={[{ id: "live", label: "En cours" }, { id: "ended", label: "Terminés" }]} />
      <LoadState loading={loading} error={error} hasData={Boolean(data)} reload={() => void reload()}>
        {data && data.results.length === 0 ? (
          <EmptyState icon={<FileSignature aria-hidden />} title={filter === "live" ? "Aucun contrat en cours" : "Aucun contrat terminé"}
            description={filter === "live" ? "Publiez un besoin, ou répondez à une offre : le contrat se prépare ici, accepté par les deux parties." : "Les contrats terminés restent consultables ici, avec leur historique."}
            actions={filter === "live" ? <ButtonLink href="/dashboard/engagements/postings/new" leftIcon={<FilePlus2 aria-hidden className="h-4 w-4" />}>Publier un besoin</ButtonLink> : undefined} />
        ) : (
          <ul className="grid gap-3">{data?.results.map((c) => <ContractRow key={c.id} c={c} />)}</ul>
        )}
      </LoadState>
    </>
  );
}

function Postings() {
  const { data, error, loading, reload } = useLoad(() => eng.get<Page<Posting>>("/postings/mine/?limit=50"), []);
  return (
    <LoadState loading={loading} error={error} hasData={Boolean(data)} reload={() => void reload()}>
      {data && data.results.length === 0 ? (
        <EmptyState icon={<Briefcase aria-hidden />} title="Aucun besoin publié" description="Décrivez ce dont vous avez besoin sur la durée : des prestataires vérifiés pourront postuler."
          actions={<ButtonLink href="/dashboard/engagements/postings/new" leftIcon={<FilePlus2 aria-hidden className="h-4 w-4" />}>Publier un besoin</ButtonLink>} />
      ) : (
        <ul className="grid gap-3">
          {data?.results.map((p) => (
            <li key={p.id}>
              <Link href={`/dashboard/engagements/postings/${p.id}`} className="block rounded-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2">
                <Card interactive padding="none" className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4 sm:p-5">
                  <div className="min-w-0 flex-1">
                    <h2 className="truncate font-display text-base font-bold text-ink">{p.title}</h2>
                    <p className="mt-1 text-sm text-ash">{p.category.name} · {p.city} · {MISSION_TYPE_FR[p.mission_type]}</p>
                    <p className="mt-1 text-sm text-inkSoft">{fcfa(p.amount, p.currency)} {PERIOD_FR[p.period]}{p.applications_count ? ` · ${p.applications_count} candidature(s)` : ""}</p>
                  </div>
                  <StatusBadge kind="posting" status={p.status} />
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </LoadState>
  );
}

function Applications() {
  const { data, error, loading, reload } = useLoad(() => eng.get<Page<Application>>("/applications/mine/?limit=50"), []);
  return (
    <LoadState loading={loading} error={error} hasData={Boolean(data)} reload={() => void reload()}>
      {data && data.results.length === 0 ? (
        <EmptyState icon={<Search aria-hidden />} title="Aucune candidature" description="Parcourez les offres de longue durée : postuler est possible dès que votre profil est vérifié."
          actions={<ButtonLink href="/dashboard/engagements/offers" leftIcon={<Search aria-hidden className="h-4 w-4" />}>Parcourir les offres</ButtonLink>} />
      ) : (
        <ul className="grid gap-3">
          {data?.results.map((a) => (
            <li key={a.id}>
              <Link href={a.contract_id ? `/dashboard/engagements/contracts/${a.contract_id}` : `/dashboard/engagements/postings/${a.posting}`}
                className="block rounded-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2">
                <Card interactive padding="none" className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4 sm:p-5">
                  <div className="min-w-0 flex-1">
                    <h2 className="truncate font-display text-base font-bold text-ink">{a.posting_title}</h2>
                    <p className="mt-1 text-sm text-ash">Candidature du {dateFr(a.created_at.slice(0, 10))}{a.interviews.some((i) => i.status === "proposed" || i.status === "confirmed") ? " · entretien prévu" : ""}</p>
                  </div>
                  <StatusBadge kind="application" status={a.status} />
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </LoadState>
  );
}

export default function EngagementsHome() {
  const [tab, setTab] = useState<Tab>("contracts");
  const { data: overview, error, reload } = useLoad(() => eng.get<Overview>("/me/overview/"), []);
  const counts = useMemo(() => overview?.counts, [overview]);
  return (
    <>
      <PageHeader
        title="Engagements"
        description="Prestations récurrentes et missions de longue durée : candidatures, contrat accepté par les deux parties, planning, rémunération mensuelle et évaluations."
        actions={
          <>
            <ButtonLink href="/dashboard/engagements/offers" variant="outline" leftIcon={<Search aria-hidden className="h-4 w-4" />}>Parcourir les offres</ButtonLink>
            <ButtonLink href="/dashboard/engagements/postings/new" leftIcon={<FilePlus2 aria-hidden className="h-4 w-4" />}>Publier un besoin</ButtonLink>
          </>
        }
      />
      <Alert tone="brand" className="mb-6" title="Une intervention ponctuelle ?">
        Elle reste une réservation classique : <Link href="/dashboard/services">explorez les services</Link>. Cet espace est réservé à ce qui se répète ou dure dans le temps.
      </Alert>
      {error ? (
        <Alert tone="warning" className="mb-6" action={<Button size="sm" variant="outline" onClick={() => void reload()}>Réessayer</Button>}>{error}</Alert>
      ) : null}
      {overview ? <TodoCard overview={overview} /> : null}
      {counts ? (
        <p className="mb-4 flex flex-wrap gap-x-5 gap-y-1 text-sm text-inkSoft">
          <span className="inline-flex items-center gap-1.5"><CalendarClock aria-hidden className="h-4 w-4 text-primary" /> {counts.active} en cours</span>
          {counts.pending_acceptance ? <span>{counts.pending_acceptance} à accepter</span> : null}
          {counts.suspended ? <span>{counts.suspended} suspendu(s)</span> : null}
          {counts.notice ? <span>{counts.notice} en préavis</span> : null}
          {overview?.postings_open ? <span className="inline-flex items-center gap-1.5"><Users aria-hidden className="h-4 w-4 text-primary" /> {overview.postings_open} besoin(s) ouvert(s)</span> : null}
        </p>
      ) : null}
      <Tabs ariaLabel="Sections" value={tab} onChange={setTab} className="mb-4" items={[{ id: "contracts", label: "Contrats" }, { id: "postings", label: "Mes besoins" }, { id: "applications", label: "Mes candidatures" }]} />
      {tab === "contracts" ? <Contracts /> : tab === "postings" ? <Postings /> : <Applications />}
    </>
  );
}
