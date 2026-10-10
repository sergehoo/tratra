"use client";
import { useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  BadgeCheck,
  Briefcase,
  Building2,
  CalendarCheck,
  CalendarClock,
  CircleAlert,
  CircleCheck,
  Compass,
  Hammer,
  Info,
  Search,
  ShieldCheck,
  Star,
  TriangleAlert,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import ServiceCard from "@/components/market/ServiceCard";
import { TrustBadges, TrustScorePill } from "@/components/trust/TrustBadge";
import {
  Alert,
  Badge,
  ButtonLink,
  Card,
  CardHeader,
  EmptyState,
  Eyebrow,
  Input,
  SkeletonCard,
  SkeletonStats,
  StatusBadge,
  Tabs,
  buttonClass,
  cx,
} from "@/components/ds";
import { TARGET_HREF, useDashboard, type DashAction, type DashItem, type DashboardData } from "@/lib/dashboard";
import { formatFCFA } from "@/lib/format";
import { iconForCategory } from "@/lib/trades";
import type { Category, Paginated, Service } from "@/lib/types";
import { useData } from "@/lib/useData";
import { formatDateTimeShort } from "./_components/dates";

const itemHref = (i: DashItem) => (i.role === "handyman" ? `/dashboard/provider/missions/${i.id}` : `/dashboard/bookings/${i.id}`);

/** Carte-indicateur cliquable (valeur réelle issue de l'API). */
function Kpi({ href, icon: Icon, label, value, hint, tone = "primary" }: {
  href: string;
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: "primary" | "accent" | "night";
}) {
  const tile = { primary: "bg-primarySoft text-primary", accent: "bg-accentSoft text-accentDark", night: "bg-night text-accent" }[tone];
  return (
    <Link
      href={href}
      className="group block rounded-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
    >
      <Card interactive padding="md" className="flex h-full items-start gap-4">
        <span aria-hidden className={cx("grid h-12 w-12 shrink-0 place-items-center rounded-2xl", tile)}>
          <Icon className="h-5 w-5" />
        </span>
        <div className="min-w-0">
          <p className="whitespace-nowrap font-display text-[1.7rem] font-extrabold leading-none tracking-tight text-ink">{value}</p>
          <p className="mt-1.5 text-sm font-medium text-ash">{label}</p>
          {hint ? <p className="mt-1 text-xs text-ash">{hint}</p> : null}
        </div>
        <ArrowRight aria-hidden className="ml-auto h-4 w-4 shrink-0 text-fog transition group-hover:translate-x-0.5 group-hover:text-primaryDark" />
      </Card>
    </Link>
  );
}

function ItemRow({ item }: { item: DashItem }) {
  const when = formatDateTimeShort(item.booking_date);
  return (
    <li>
      <Link
        href={itemHref(item)}
        className="flex items-center gap-3 rounded-panel border border-lineSoft bg-white p-3.5 transition hover:border-primary/30 hover:shadow-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary sm:p-4"
      >
        <span aria-hidden className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primarySoft text-primary">
          {item.role === "handyman" ? <Hammer className="h-5 w-5" /> : <CalendarCheck className="h-5 w-5" />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-display text-[15px] font-bold leading-tight text-ink">{item.title}</p>
          <p className="mt-0.5 truncate text-xs text-ash">
            {item.role === "handyman" ? "Client" : "Artisan"} : {item.counterpart}
            {when ? ` · ${when}` : ""}
            {item.city ? ` · ${item.city}` : ""}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <StatusBadge kind="booking" status={item.status} />
          <span className="text-[11px] font-semibold uppercase tracking-wider text-ash">
            {item.role === "handyman" ? "Mission" : "Réservation"}
          </span>
        </div>
      </Link>
    </li>
  );
}

const SEVERITY: Record<DashAction["severity"], { icon: LucideIcon; box: string }> = {
  danger: { icon: CircleAlert, box: "bg-dangerSoft text-danger" },
  warning: { icon: TriangleAlert, box: "bg-warningSoft text-warning" },
  info: { icon: Info, box: "bg-infoSoft text-info" },
};

function ActionsCard({ actions }: { actions: DashAction[] }) {
  return (
    <Card>
      <CardHeader title="À traiter" description="Ce qui demande votre attention." icon={<CircleAlert className="h-5 w-5" />} />
      {actions.length === 0 ? (
        <div className="flex items-center gap-3 rounded-panel bg-successSoft p-4 text-sm font-medium text-successInk">
          <CircleCheck aria-hidden className="h-5 w-5 shrink-0" />
          Rien à traiter pour le moment.
        </div>
      ) : (
        <ul className="space-y-3">
          {actions.map((a) => {
            const { icon: Icon, box } = SEVERITY[a.severity];
            return (
              <li key={a.key} className="flex items-start gap-3">
                <span aria-hidden className={cx("mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-xl", box)}>
                  <Icon className="h-[18px] w-[18px]" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold leading-snug text-ink">{a.title}</p>
                  <p className="mt-0.5 text-xs leading-relaxed text-ash">{a.description}</p>
                  <Link
                    href={TARGET_HREF[a.target]}
                    className="mt-1.5 inline-flex min-h-[32px] items-center gap-1 text-xs font-bold text-primaryDark hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  >
                    Ouvrir <ArrowRight aria-hidden className="h-3.5 w-3.5" />
                  </Link>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

const KYC_LABEL = {
  none: { label: "À déposer", tone: "gray" },
  pending: { label: "En vérification", tone: "accent" },
  approved: { label: "Vérifiée", tone: "success" },
  rejected: { label: "Refusée", tone: "danger" },
} as const;

function ProfileCard({ data }: { data: DashboardData }) {
  const p = data.provider;
  if (!p) {
    return (
      <Card variant="night" className="relative isolate overflow-hidden">
        <div aria-hidden className="absolute -right-10 -top-10 -z-10 h-40 w-40 rounded-full bg-accent/20 blur-3xl" />
        <Eyebrow tone="dark">Prestataire</Eyebrow>
        <h2 className="mt-3 font-display text-xl font-extrabold leading-tight">Proposez vos services avec ce même compte</h2>
        <p className="mt-2 text-sm leading-relaxed text-white/75">
          Créez votre profil professionnel en un clic, sans nouvelle inscription. Vos services sont publiés et vous recevez
          des missions après vérification de votre identité par l’équipe Tratra.
        </p>
        <ButtonLink href="/dashboard/provide" variant="accent" className="mt-5" rightIcon={<ArrowRight aria-hidden className="h-4 w-4" />}>
          Proposer mes services
        </ButtonLink>
      </Card>
    );
  }
  const kyc = KYC_LABEL[p.kyc.status];
  const missing = p.completion.items.filter((i) => !i.done).slice(0, 4);
  return (
    <Card>
      <CardHeader
        title="Profil professionnel"
        icon={<ShieldCheck className="h-5 w-5" />}
        action={<Badge tone={p.publishable ? "success" : "gray"} dot>{p.publishable ? "Publié" : "Non publié"}</Badge>}
      />
      {p.badges?.length ? (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <TrustBadges badges={p.badges} />
          {p.trust_score != null ? <TrustScorePill score={p.trust_score} /> : null}
          <Link href="/dashboard/reputation" className="text-xs font-semibold text-primaryDark hover:underline">Ma réputation</Link>
        </div>
      ) : null}
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-sm font-semibold text-ink">Progression</span>
        <span className="font-display text-lg font-extrabold text-primaryDark">{p.completion.percent}%</span>
      </div>
      <div
        role="progressbar"
        aria-label="Progression du profil professionnel"
        aria-valuenow={p.completion.percent}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-2.5 overflow-hidden rounded-full bg-lineSoft"
      >
        <div className="h-full rounded-full bg-gradient-to-r from-primary to-accent transition-[width] duration-slow ease-emphasized" style={{ width: `${p.completion.percent}%` }} />
      </div>
      <div className="mt-4 flex items-center justify-between gap-3 rounded-panel bg-canvas px-3.5 py-3">
        <span className="flex items-center gap-2 text-sm font-semibold text-ink">
          <BadgeCheck aria-hidden className="h-4 w-4 text-primary" /> Identité (KYC)
        </span>
        <Badge tone={kyc.tone} dot>{kyc.label}</Badge>
      </div>
      {p.kyc.status === "rejected" && p.kyc.rejection_reason ? (
        <Alert tone="danger" className="mt-3">{p.kyc.rejection_reason}</Alert>
      ) : null}
      {missing.length ? (
        <ul className="mt-4 space-y-1.5 text-sm text-inkSoft">
          {missing.map((i) => (
            <li key={i.key} className="flex items-start gap-2">
              <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accentDark" />
              {i.label}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-sm font-medium text-successInk">Votre dossier est complet.</p>
      )}
      <div className="mt-5 flex flex-wrap gap-2">
        <ButtonLink href="/dashboard/profile" size="sm">Compléter mon profil</ButtonLink>
        <ButtonLink href="/dashboard/profile/kyc" size="sm" variant="outline">Mes documents</ButtonLink>
      </div>
    </Card>
  );
}

/** Découverte : catégories qui ont des services réels, puis quelques services publiés. */
/** Espace entreprise : une organisation liée au MÊME compte (aucun second compte). */
function CompanyCard({ company }: { company: boolean }) {
  return (
    <Card variant="soft">
      <CardHeader title="Espace entreprise" icon={<Building2 className="h-5 w-5" />} />
      <p className="text-sm leading-relaxed text-inkSoft">
        {company
          ? "Gérez votre organisation et vos offres B2B depuis ce même compte."
          : "Créez une organisation rattachée à votre compte pour gérer une entreprise et ses offres B2B, sans nouvelle inscription."}
      </p>
      <ButtonLink href={company ? "/company" : "/dashboard/company/new"} variant="outline" className="mt-4" rightIcon={<ArrowRight aria-hidden className="h-4 w-4" />}>
        {company ? "Ouvrir l’espace entreprise" : "Créer un espace entreprise"}
      </ButtonLink>
    </Card>
  );
}

function Discovery() {
  const cats = useData<Paginated<Category>>("/categories/?ordering=-services_count&page_size=8");
  const services = useData<Paginated<Service>>("/services/?page_size=3");
  const categories = (cats.data?.results ?? []).filter((c) => (c.services_count ?? 0) > 0).slice(0, 8);
  const list = services.data?.results ?? [];
  const loading = cats.loading || services.loading;

  if (!loading && categories.length === 0 && list.length === 0) return null;
  return (
    <section aria-labelledby="decouverte" className="mt-10">
      <div className="mb-4 flex items-end justify-between gap-3">
        <h2 id="decouverte" className="font-display text-xl font-extrabold tracking-tight text-ink">À découvrir</h2>
        <Link href="/dashboard/services" className="inline-flex min-h-[44px] items-center gap-1 text-sm font-bold text-primaryDark hover:underline">
          Tout explorer <ArrowRight aria-hidden className="h-4 w-4" />
        </Link>
      </div>
      {loading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" role="status" aria-label="Chargement en cours">
          {Array.from({ length: 4 }, (_, i) => <SkeletonCard key={i} />)}
        </div>
      ) : (
        <>
          {categories.length ? (
            <ul className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {categories.map((c) => {
                const Icon = iconForCategory(c.slug);
                return (
                  <li key={c.id}>
                    <Link
                      href={`/dashboard/services?categories=${c.id}`}
                      className="flex min-h-[64px] items-center gap-3 rounded-panel border border-lineSoft bg-white p-3 transition hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                    >
                      <span aria-hidden className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primarySoft text-primary">
                        <Icon className="h-5 w-5" />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-bold text-ink">{c.name}</span>
                        <span className="block text-xs text-ash">{c.services_count} service{(c.services_count ?? 0) > 1 ? "s" : ""}</span>
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          ) : null}
          {list.length ? (
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {list.map((s) => <ServiceCard key={s.id} service={s} />)}
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

export default function DashboardHome() {
  const { data, loading, error, reload } = useDashboard();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [tab, setTab] = useState<"bookings" | "missions">("bookings");

  if (loading) {
    return (
      <div className="space-y-6" role="status" aria-label="Chargement du tableau de bord">
        <div aria-hidden className="skeleton h-56 !rounded-card" />
        <SkeletonStats count={4} className="sm:grid-cols-2 lg:grid-cols-4" />
        <div aria-hidden className="grid gap-6 lg:grid-cols-3">
          <div className="skeleton h-72 !rounded-card lg:col-span-2" />
          <div className="skeleton h-72 !rounded-card" />
        </div>
        <span className="sr-only">Chargement…</span>
      </div>
    );
  }
  if (error || !data) {
    return (
      <>
        <h1 className="sr-only">Tableau de bord</h1>
        <Alert tone="danger" title="Tableau de bord indisponible" action={<button onClick={() => void reload()} className={buttonClass("outline", "sm")}>Réessayer</button>}>
          {error || "Les données n’ont pas pu être chargées."}
        </Alert>
      </>
    );
  }

  const { client, provider, upcoming, reviews, user } = data;
  const inProgress = client.bookings.pending + client.bookings.confirmed + client.bookings.in_progress;
  const showClientKpis = client.bookings.total > 0 || !provider;

  const kpis: ReactNode[] = [];
  if (showClientKpis) {
    kpis.push(
      <Kpi key="rb" href="/dashboard/bookings" icon={CalendarCheck} label="Réservations en cours" value={inProgress}
        hint={client.bookings.total ? `${client.bookings.completed} terminée${client.bookings.completed > 1 ? "s" : ""}` : "Aucune pour le moment"} />,
    );
  }
  if (provider) {
    kpis.push(
      <Kpi key="mp" href="/dashboard/provider" icon={Hammer} tone="accent" label="Missions à traiter" value={provider.missions.pending}
        hint={provider.missions.pending ? "En attente de votre réponse" : "Aucune demande en attente"} />,
      <Kpi key="mc" href="/dashboard/provider" icon={Briefcase} label="Missions à venir"
        value={provider.missions.confirmed + provider.missions.in_progress}
        hint={`${provider.missions.completed} terminée${provider.missions.completed > 1 ? "s" : ""}`} />,
      <Kpi key="gw" href="/dashboard/wallet" icon={Wallet} tone="night" label="Gains disponibles"
        value={formatFCFA(provider.earnings.available) ?? "0 FCFA"} />,
    );
  } else {
    kpis.push(
      <Kpi key="cd" href="/dashboard/bookings" icon={CircleCheck} label="Prestations terminées" value={client.bookings.completed} />,
      <Kpi key="rv" href="/dashboard/reviews" icon={Star} tone="accent" label="Avis à rédiger" value={reviews.to_write}
        hint={reviews.to_write ? "Partagez votre expérience" : "Rien à noter"} />,
    );
  }
  const recent = tab === "missions" && provider ? provider.recent_missions : client.recent_bookings;

  function onSearch(e: FormEvent) {
    e.preventDefault();
    const term = q.trim();
    router.push(`/dashboard/services${term ? `?search=${encodeURIComponent(term)}` : ""}`);
  }

  const greeting = user.first_name || user.display_name;
  const summary = upcoming.length
    ? `${upcoming.length} intervention${upcoming.length > 1 ? "s" : ""} à venir.`
    : provider
      ? "Gérez vos prestations et trouvez aussi un artisan pour vos propres besoins."
      : "Trouvez un artisan vérifié près de chez vous, ou proposez vos propres services.";

  return (
    <div className="space-y-8">
      {/* Hero personnalisé */}
      <section aria-labelledby="titre-dashboard" className="relative isolate overflow-hidden rounded-card bg-night px-5 py-7 text-white shadow-strong sm:px-8 sm:py-9">
        <div aria-hidden className="absolute inset-0 -z-10 bg-[radial-gradient(60%_90%_at_0%_0%,rgba(46,139,87,0.55),transparent_70%),radial-gradient(45%_70%_at_100%_100%,rgba(246,201,14,0.16),transparent_70%)]" />
        <Eyebrow tone="dark">Mon espace</Eyebrow>
        <h1 id="titre-dashboard" className="mt-3 font-display text-[1.85rem] font-extrabold leading-[1.1] tracking-tight [text-wrap:balance] sm:text-4xl">
          Bonjour, <span className="text-accent">{greeting}</span>
        </h1>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-white/80 sm:text-base">{summary}</p>

        <form role="search" onSubmit={onSearch} className="mt-6 flex max-w-xl flex-col gap-2 sm:flex-row">
          <label htmlFor="hero-search" className="sr-only">Rechercher un service ou un métier</label>
          <Input
            id="hero-search"
            type="search"
            enterKeyHint="search"
            autoComplete="off"
            placeholder="Plomberie, électricité, ménage…"
            leading={<Search className="h-4 w-4" />}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="w-full min-w-0 sm:flex-1"
          />
          <button type="submit" className={buttonClass("accent", "md", "shrink-0")}>Rechercher</button>
        </form>

        <div className="mt-5 flex flex-wrap gap-3">
          <ButtonLink href="/dashboard/services" variant="primary" leftIcon={<Compass aria-hidden className="h-4 w-4" />}>
            Trouver un artisan
          </ButtonLink>
          <ButtonLink href="/dashboard/provide" variant="outlineLight" leftIcon={<Hammer aria-hidden className="h-4 w-4" />}>
            {provider ? "Gérer mes services" : "Proposer mes services"}
          </ButtonLink>
        </div>
      </section>

      {/* Indicateurs réels */}
      <section aria-label="Indicateurs" className={cx("grid grid-cols-1 gap-4 sm:grid-cols-2", kpis.length === 3 ? "lg:grid-cols-3" : "lg:grid-cols-4")}>{kpis.slice(0, 4)}</section>

      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-6 lg:col-span-2">
          <Card>
            <CardHeader title="Prochaines interventions" description="Vos réservations et missions à venir, par date." icon={<CalendarClock className="h-5 w-5" />} />
            {upcoming.length ? (
              <ul className="space-y-3">{upcoming.map((i) => <ItemRow key={`${i.role}-${i.id}`} item={i} />)}</ul>
            ) : (
              <EmptyState
                compact
                icon={<CalendarClock />}
                title="Aucune intervention à venir"
                description="Dès qu’une réservation ou une mission est planifiée, elle apparaît ici."
                actions={<ButtonLink href="/dashboard/services" size="sm">Explorer les services</ButtonLink>}
              />
            )}
          </Card>

          <Card>
            <CardHeader
              title="Activité récente"
              icon={<CalendarCheck className="h-5 w-5" />}
              action={
                provider ? (
                  <Tabs
                    ariaLabel="Type d’activité"
                    value={tab}
                    onChange={setTab}
                    items={[{ id: "bookings", label: "Réservations" }, { id: "missions", label: "Missions" }]}
                  />
                ) : undefined
              }
            />
            {recent.length ? (
              <ul className="space-y-3">{recent.map((i) => <ItemRow key={`${i.role}-${i.id}`} item={i} />)}</ul>
            ) : (
              <EmptyState
                compact
                title={tab === "missions" ? "Aucune mission pour le moment" : "Aucune réservation pour le moment"}
                description={tab === "missions"
                  ? "Les demandes des clients apparaîtront ici dès que vos services seront publiés."
                  : "Réservez un artisan vérifié en quelques minutes."}
                actions={tab === "missions"
                  ? <ButtonLink href="/dashboard/provider" size="sm" variant="outline">Mes prestations</ButtonLink>
                  : <ButtonLink href="/dashboard/services" size="sm">Trouver un artisan</ButtonLink>}
              />
            )}
            {recent.length ? (
              <div className="mt-4">
                <ButtonLink href={tab === "missions" ? "/dashboard/provider" : "/dashboard/bookings"} variant="ghost" size="sm" rightIcon={<ArrowRight aria-hidden className="h-4 w-4" />}>
                  {tab === "missions" ? "Toutes mes missions" : "Toutes mes réservations"}
                </ButtonLink>
              </div>
            ) : null}
          </Card>
        </div>

        <div className="min-w-0 space-y-6">
          <ActionsCard actions={data.actions} />
          <ProfileCard data={data} />
          <CompanyCard company={data.capabilities.company} />
        </div>
      </div>

      <Discovery />
    </div>
  );
}
