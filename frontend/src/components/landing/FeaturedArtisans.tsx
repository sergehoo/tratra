"use client";
import { useMemo } from "react";
import { ArrowRight, FileCheck2, HardHat, IdCard, RefreshCw, UserCheck, ShieldCheck } from "lucide-react";
import ArtisanCard from "@/components/market/ArtisanCard";
import { EmptyState } from "@/components/market/primitives";
import { CardGridSkeleton } from "@/components/market/Skeletons";
import { registerHref } from "@/lib/links";
import { resultsOf } from "@/lib/public";
import type { PublicArtisan } from "@/lib/types";
import { useLanding } from "./LandingData";
import { CONTAINER, CtaLink, SECTION_Y, SectionHeading, btn } from "./kit";
import { Reveal, RevealGroup, RevealItem } from "./Reveal";

/** Étapes RÉELLES du contrôle d'un profil artisan (badge Vérifié). */
const CHECKS = [
  { icon: IdCard, title: "Pièce d’identité", text: "Contrôlée par l’équipe Tratra avant l’attribution du badge." },
  { icon: FileCheck2, title: "Documents justificatifs", text: "Transmis par l’artisan, examinés par l’équipe Tratra." },
  { icon: ShieldCheck, title: "Badge « Vérifié »", text: "Affiché uniquement une fois la vérification validée." },
];

export default function FeaturedArtisans() {
  const { data, loading, error, reload } = useLanding("featured");
  const { data: categories } = useLanding("categories");
  // Métiers ayant au moins une prestation active (lien « Voir les prestations
  // en … » jamais vide) ; null tant que les catégories sont inconnues.
  const tradesWithServices = useMemo(
    () =>
      categories
        ? new Set(
            resultsOf(categories)
              .filter((c) => (c.services_count ?? 0) > 0)
              .map((c) => c.slug),
          )
        : null,
    [categories],
  );
  const artisans: PublicArtisan[] = data
    ? Array.isArray(data)
      ? (data as PublicArtisan[])
      : (data.results ?? [])
    : [];

  return (
    <section
      id="artisans"
      aria-labelledby="artisans-titre"
      className={`scroll-mt-20 overflow-hidden bg-slate-50 lg:scroll-mt-24 ${SECTION_Y}`}
    >
      <div className={CONTAINER}>
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <Reveal>
            <SectionHeading
              id="artisans-titre"
              eyebrow="Artisans à la une"
              title={
                <>
                  Des professionnels <span className="text-primary">vérifiés</span>, près de chez vous
                </>
              }
              description="Seuls les profils ayant passé la vérification d’identité et des documents apparaissent dans cette sélection."
            />
          </Reveal>
          {artisans.length ? (
            <Reveal delay={0.1} className="hidden shrink-0 md:block">
              <CtaLink href="/search" variant="outline">
                Parcourir les prestations
                <ArrowRight aria-hidden className="h-4 w-4" />
              </CtaLink>
            </Reveal>
          ) : null}
        </div>

        <div className="mt-12">
          {artisans.length ? (
            <>
              <RevealGroup
                as="ul"
                ariaLabel="Artisans à la une"
                className="-mx-4 flex snap-x snap-mandatory scroll-px-4 gap-4 overflow-x-auto px-4 pb-4 [scrollbar-width:none] sm:mx-0 sm:grid sm:snap-none sm:grid-cols-2 sm:gap-5 sm:overflow-visible sm:px-0 sm:pb-0 lg:grid-cols-4 [&::-webkit-scrollbar]:hidden"
              >
                {artisans.map((a) => (
                  <RevealItem
                    as="li"
                    key={a.id}
                    className="w-[82%] max-w-[320px] shrink-0 snap-start sm:w-auto sm:max-w-none"
                  >
                    <ArtisanCard artisan={a} tradesWithServices={tradesWithServices} />
                  </RevealItem>
                ))}
              </RevealGroup>
              <div className="mt-6 md:hidden">
                <CtaLink href="/search" variant="outline" className="w-full">
                  Parcourir les prestations
                  <ArrowRight aria-hidden className="h-4 w-4" />
                </CtaLink>
              </div>
            </>
          ) : loading ? (
            <CardGridSkeleton kind="artisan" count={4} className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4" />
          ) : error ? (
            <EmptyState
              icon={<UserCheck aria-hidden className="h-7 w-7" />}
              title="Les artisans n’ont pas pu être chargés"
              description="La connexion a échoué. Réessayez ou parcourez directement les prestations disponibles."
              actions={
                <>
                  <button type="button" onClick={reload} className={btn("primary")}>
                    <RefreshCw aria-hidden className="h-4 w-4" />
                    Réessayer
                  </button>
                  <CtaLink href="/search" variant="outline">
                    Parcourir les prestations
                  </CtaLink>
                </>
              }
            />
          ) : (
            <Reveal>
              <div className="grid gap-5 lg:grid-cols-5">
                <EmptyState
                  className="justify-center border-solid border-slate-100 py-12 shadow-soft lg:col-span-3"
                  icon={<UserCheck aria-hidden className="h-7 w-7" />}
                  title="Nos artisans vérifiés arrivent"
                  description="Seuls les profils contrôlés (identité, documents) figureront dans cette sélection."
                  actions={
                    <>
                      <CtaLink href={registerHref("handyman")} variant="primary">
                        <HardHat aria-hidden className="h-4 w-4" />
                        Rejoindre Tratra comme artisan
                      </CtaLink>
                      <CtaLink href="/search" variant="outline">
                        Parcourir les prestations
                      </CtaLink>
                    </>
                  }
                />
                <div className="rounded-3xl bg-night p-6 text-white shadow-strong sm:p-8 lg:col-span-2">
                  <h3 className="font-display text-lg font-bold">Comment un profil est vérifié</h3>
                  <ol className="mt-6 space-y-5">
                    {CHECKS.map(({ icon: Icon, title, text }, i) => (
                      <li key={title} className="flex gap-4">
                        <span className="relative grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-accent/15 text-accent">
                          <Icon aria-hidden className="h-5 w-5" />
                          <span
                            aria-hidden
                            className="absolute -right-1.5 -top-1.5 grid h-5 w-5 place-items-center rounded-full bg-accent text-[11px] font-bold text-night"
                          >
                            {i + 1}
                          </span>
                        </span>
                        <span>
                          <span className="block font-semibold">{title}</span>
                          <span className="mt-0.5 block text-sm leading-relaxed text-white/70">{text}</span>
                        </span>
                      </li>
                    ))}
                  </ol>
                </div>
              </div>
            </Reveal>
          )}
        </div>
      </div>
    </section>
  );
}
