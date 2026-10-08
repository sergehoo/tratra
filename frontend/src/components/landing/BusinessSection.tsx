"use client";
import { ArrowRight, BadgeCheck, Building2, CalendarRange, LayoutDashboard, Store } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { formatFCFA } from "@/lib/format";
import { registerHref } from "@/lib/links";
import { resultsOf } from "@/lib/public";
import type { SubscriptionPlan } from "@/lib/types";
import { useLanding } from "./LandingData";
import { CONTAINER, CtaLink, Eyebrow, SECTION_Y } from "./kit";
import { Reveal, RevealGroup, RevealItem } from "./Reveal";

const INTERVALS: Record<string, { label: string; per: string }> = {
  monthly: { label: "Mensuel", per: "/ mois" },
  yearly: { label: "Annuel", per: "/ an" },
};

const BENEFITS = [
  { icon: Store, text: "Interventions pour vos bureaux, boutiques et sites" },
  { icon: BadgeCheck, text: "Profil entreprise vérifié" },
  { icon: CalendarRange, text: "Abonnements adaptés à votre activité" },
];

/** Nom, périodicité et prix uniquement : le détail des offres reste sur /company/plans. */
function PlanCard({ plan }: { plan: SubscriptionPlan }) {
  const interval = INTERVALS[plan.interval];
  const amount = Number(plan.price);
  const price = formatFCFA(plan.price) ?? (amount === 0 ? "Gratuit" : null);

  return (
    <article className="flex h-full flex-col rounded-3xl border border-white/10 bg-white/[0.07] p-6 backdrop-blur-sm transition duration-300 hover:-translate-y-1 hover:border-accent/40 hover:bg-white/[0.1]">
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-display text-lg font-bold text-white">{plan.name}</h3>
        {interval ? (
          <span className="shrink-0 rounded-full bg-accent/15 px-2.5 py-1 text-xs font-semibold text-accent">
            {interval.label}
          </span>
        ) : null}
      </div>
      {price ? (
        <p className="mt-4 flex flex-wrap items-baseline gap-x-1.5">
          <span className="font-display text-3xl font-extrabold tracking-tight text-white">{price}</span>
          {interval && amount > 0 ? <span className="text-sm text-white/70">{interval.per}</span> : null}
        </p>
      ) : null}
    </article>
  );
}

/** Offre B2B : arguments réels + abonnements issus de l'API (aucun prix inventé). */
export default function BusinessSection() {
  const { user } = useAuth();
  const { data, loading } = useLanding("plans");
  const plans = resultsOf(data)
    .filter((p) => p.active !== false)
    .slice(0, 3);

  const isCompany = user?.user_type === "entreprise";
  const primary = isCompany
    ? { href: "/company", label: "Mon espace entreprise", icon: LayoutDashboard }
    : { href: registerHref("entreprise"), label: "Créer un compte entreprise", icon: Building2 };
  const offersHref = isCompany ? "/company/plans" : registerHref("entreprise", "/company/plans");

  return (
    <section
      id="entreprises"
      aria-labelledby="entreprises-titre"
      className={`scroll-mt-20 bg-white lg:scroll-mt-24 ${SECTION_Y}`}
    >
      <div className={CONTAINER}>
        <Reveal y={32}>
          <div className="relative isolate overflow-hidden rounded-[2rem] bg-gradient-to-br from-primaryDark via-[#123f28] to-night px-6 py-12 text-white shadow-strong sm:px-10 md:px-14 md:py-16 lg:rounded-[2.5rem]">
            <div
              aria-hidden
              className="absolute -right-24 -top-24 -z-10 h-80 w-80 rounded-full bg-accent/15 blur-3xl"
            />
            <div
              aria-hidden
              className="absolute -bottom-32 -left-20 -z-10 h-96 w-96 rounded-full bg-primary/40 blur-3xl"
            />
            <div
              aria-hidden
              className="absolute inset-0 -z-10 opacity-[0.06] [background-image:linear-gradient(rgba(255,255,255,.8)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.8)_1px,transparent_1px)] [background-size:44px_44px] [mask-image:radial-gradient(ellipse_at_80%_20%,black_10%,transparent_65%)]"
            />

            <div className="grid items-center gap-12 lg:grid-cols-12">
              <div className="lg:col-span-6">
                <Eyebrow tone="dark">
                  <Building2 aria-hidden className="h-3.5 w-3.5" />
                  Tratra Entreprises
                </Eyebrow>
                <h2
                  id="entreprises-titre"
                  className="mt-4 font-display text-[1.85rem] font-extrabold leading-[1.12] tracking-tight [text-wrap:balance] sm:text-4xl lg:text-[2.6rem]"
                >
                  Des artisans fiables pour vos <span className="text-accent">locaux professionnels</span>
                </h2>
                <p className="mt-4 max-w-xl text-base leading-relaxed text-white/80 sm:text-lg">
                  Confiez dépannages et entretien à des professionnels vérifiés, depuis un espace dédié à votre
                  entreprise.
                </p>
                <ul className="mt-8 space-y-3.5">
                  {BENEFITS.map(({ icon: Icon, text }) => (
                    <li key={text} className="flex items-center gap-3 text-[15px] font-medium text-white/90">
                      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white/10 text-accent ring-1 ring-inset ring-white/10">
                        <Icon aria-hidden className="h-5 w-5" />
                      </span>
                      {text}
                    </li>
                  ))}
                </ul>
                <div className="mt-10 flex flex-col gap-3 sm:flex-row">
                  <CtaLink href={primary.href} variant="accent" size="lg">
                    <primary.icon aria-hidden className="h-5 w-5" />
                    {primary.label}
                  </CtaLink>
                  <CtaLink href={offersHref} variant="outlineLight" size="lg">
                    Voir les offres
                    <ArrowRight aria-hidden className="h-5 w-5" />
                  </CtaLink>
                </div>
              </div>

              <div className="lg:col-span-6">
                {plans.length ? (
                  <RevealGroup
                    as="ul"
                    ariaLabel="Offres entreprise"
                    className={`grid gap-4 ${plans.length > 1 ? "sm:grid-cols-2" : ""}`}
                    delay={0.15}
                  >
                    {plans.map((p, i) => (
                      <RevealItem
                        as="li"
                        key={p.id}
                        className={plans.length === 3 && i === 2 ? "sm:col-span-2" : undefined}
                      >
                        <PlanCard plan={p} />
                      </RevealItem>
                    ))}
                  </RevealGroup>
                ) : loading ? (
                  <div aria-hidden className="grid gap-4 sm:grid-cols-2">
                    {Array.from({ length: 2 }, (_, i) => (
                      <div key={i} className="h-32 rounded-3xl border border-white/10 bg-white/5" />
                    ))}
                  </div>
                ) : (
                  <div className="rounded-3xl border border-white/10 bg-white/[0.07] p-8 backdrop-blur-sm">
                    <span className="grid h-12 w-12 place-items-center rounded-2xl bg-accent text-night">
                      <Building2 aria-hidden className="h-6 w-6" />
                    </span>
                    <h3 className="mt-5 font-display text-xl font-bold">Un espace dédié à votre entreprise</h3>
                    <p className="mt-2 leading-relaxed text-white/80">
                      Créez votre compte entreprise pour renseigner votre société, faire vérifier votre profil et gérer
                      vos interventions.
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
