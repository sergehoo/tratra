"use client";
import { ArrowRight, HardHat, LayoutDashboard } from "lucide-react";
import ServiceCard from "@/components/market/ServiceCard";
import { CardGridSkeleton } from "@/components/market/Skeletons";
import { useAuth } from "@/lib/auth";
import { ESCROW_ENABLED } from "@/lib/config";
import { registerHref } from "@/lib/links";
import { resultsOf } from "@/lib/public";
import { useLanding } from "./LandingData";
import { CONTAINER, CtaLink, SectionHeading } from "./kit";
import { Reveal, RevealGroup, RevealItem } from "./Reveal";

/** Dernières prestations réellement publiées (section masquée s'il n'y en a aucune). */
/** Tuile d'appel affichée quand le catalogue compte moins de 3 prestations. */
function PublishTile({ wide }: { wide: boolean }) {
  const { user } = useAuth();
  const isArtisan = user?.user_type === "handyman";
  return (
    <div
      className={`relative flex h-full flex-col justify-between overflow-hidden rounded-3xl bg-night p-7 text-white shadow-strong ${
        wide ? "lg:p-10" : ""
      }`}
    >
      <div aria-hidden className="absolute -right-16 -top-16 h-56 w-56 rounded-full bg-primary/40 blur-3xl" />
      <div className="relative">
        <span className="grid h-12 w-12 place-items-center rounded-2xl bg-accent text-night">
          <HardHat aria-hidden className="h-6 w-6" />
        </span>
        <p className="mt-6 text-[11px] font-bold uppercase tracking-[0.16em] text-accent">Vous êtes artisan ?</p>
        <h3 className="mt-2 font-display text-xl font-bold leading-snug sm:text-2xl">
          Publiez vos prestations sur Tratra
        </h3>
        <p className="mt-3 max-w-md text-[15px] leading-relaxed text-white/75">
          Fixez vos tarifs, faites vérifier votre profil et recevez des réservations de clients près de chez vous.
        </p>
      </div>
      <div className="relative mt-8 flex flex-wrap gap-3">
        {isArtisan ? (
          <CtaLink href="/dashboard/provide" variant="accent">
            <LayoutDashboard aria-hidden className="h-4 w-4" />
            Mon espace artisan
          </CtaLink>
        ) : (
          <CtaLink href={registerHref("handyman")} variant="accent">
            <HardHat aria-hidden className="h-4 w-4" />
            Devenir artisan
          </CtaLink>
        )}
      </div>
    </div>
  );
}

export default function LatestServices() {
  const { data, loading } = useLanding("services");
  const services = resultsOf(data)
    .filter((s) => s.is_active !== false)
    .slice(0, 6);

  if (!services.length && !loading) return null;

  return (
    <section aria-labelledby="prestations-titre" className="bg-white pb-6 pt-20 md:pb-10 md:pt-28">
      <div className={CONTAINER}>
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <Reveal>
            <SectionHeading
              id="prestations-titre"
              eyebrow="Réservez en ligne"
              title="Prestations disponibles"
              description={`Tarifs fixés par les artisans eux-mêmes. Intervention immédiate ou planifiée, ${
                ESCROW_ENABLED ? "paiement sécurisé" : "paiement à la fin de l’intervention"
              }.`}
            />
          </Reveal>
          {services.length ? (
            <Reveal delay={0.1} className="shrink-0">
              <CtaLink href="/search" variant="outline">
                Toutes les prestations
                <ArrowRight aria-hidden className="h-4 w-4" />
              </CtaLink>
            </Reveal>
          ) : null}
        </div>

        <div className="mt-12">
          {services.length ? (
            <RevealGroup as="ul" className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {services.map((s) => (
                <RevealItem as="li" key={s.id}>
                  <ServiceCard service={s} />
                </RevealItem>
              ))}
              {services.length < 3 ? (
                <RevealItem as="li" className={services.length === 1 ? "lg:col-span-2" : undefined}>
                  <PublishTile wide={services.length === 1} />
                </RevealItem>
              ) : null}
            </RevealGroup>
          ) : (
            <CardGridSkeleton count={3} />
          )}
        </div>
      </div>
    </section>
  );
}
