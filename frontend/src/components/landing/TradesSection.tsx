"use client";
import Link from "next/link";
import { ArrowRight, ArrowUpRight, LayoutGrid, RefreshCw } from "lucide-react";
import { EmptyState } from "@/components/market/primitives";
import { formatCount } from "@/lib/format";
import { featuredTrades } from "@/lib/trades";
import { useTrades } from "./LandingData";
import { CONTAINER, CtaLink, SECTION_Y, SectionHeading, btn } from "./kit";
import { Reveal, RevealGroup, RevealItem } from "./Reveal";

/**
 * Métiers MIS EN AVANT par l'administration (catalogue unique) avec leurs prestations. « Voir tous les métiers » ouvre le catalogue complet (/metiers).
 * Un métier actif est affiché même sans offre.
 */
export default function TradesSection() {
  const { trades: all, loading, error, reload } = useTrades();
  const trades = featuredTrades(all);

  return (
    <section
      id="metiers"
      aria-labelledby="metiers-titre"
      className={`scroll-mt-20 bg-white lg:scroll-mt-24 ${SECTION_Y}`}
    >
      <div className={CONTAINER}>
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <Reveal>
            <SectionHeading
              id="metiers-titre"
              eyebrow="Métiers"
              title={
                <>
                  Un savoir-faire pour <span className="text-primary">chaque besoin</span> de la maison
                </>
              }
              description="Choisissez un métier : vous accédez directement aux offres publiées par les artisans, avec leurs tarifs."
            />
          </Reveal>
          <Reveal delay={0.1} className="hidden shrink-0 md:block">
            <CtaLink href="/metiers" variant="outline">
              Voir tous les métiers
              <ArrowRight aria-hidden className="h-4 w-4" />
            </CtaLink>
          </Reveal>
        </div>

        <div className="mt-12">
          {trades.length ? (
            <RevealGroup
              as="ul"
              className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-5"
              stagger={0.045}
            >
              {trades.map((t) => {
                const count = t.offersTotal ?? 0;
                const shown = t.prestations.slice(0, 3);
                return (
                  <RevealItem as="li" key={t.key} className="min-w-0">
                    <Link
                      href={t.href}
                      className="group relative flex h-full flex-col rounded-3xl border border-slate-100 bg-white p-4 shadow-soft transition duration-300 hover:-translate-y-1 hover:border-primary/25 hover:shadow-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 sm:p-5"
                    >
                      <span className="grid h-12 w-12 place-items-center rounded-2xl bg-primarySoft text-primaryDark transition-colors duration-300 group-hover:bg-accent group-hover:text-ink">
                        <t.icon aria-hidden className="h-6 w-6" strokeWidth={1.8} />
                      </span>
                      <ArrowUpRight
                        aria-hidden
                        className="absolute right-4 top-4 h-5 w-5 text-slate-300 opacity-0 transition duration-300 group-hover:translate-x-0.5 group-hover:opacity-100 group-hover:text-primaryDark"
                      />
                      <h3 className="mt-4 break-words font-display text-[15px] font-bold leading-snug text-ink hyphens-auto sm:text-base lg:text-[17px]">
                        {t.label}
                      </h3>
                      {shown.length ? (
                        <ul aria-label={`Prestations : ${t.label}`} className="mt-2 hidden flex-wrap gap-1.5 sm:flex">
                          {shown.map((p) => (
                            <li key={p.id} className="max-w-full truncate rounded-full bg-slate-50 px-2 py-0.5 text-xs text-inkSoft ring-1 ring-inset ring-slate-100">
                              {p.name}
                            </li>
                          ))}
                          {t.prestations.length > shown.length ? (
                            <li className="rounded-full px-2 py-0.5 text-xs font-semibold text-primaryDark">+{t.prestations.length - shown.length}</li>
                          ) : null}
                        </ul>
                      ) : t.blurb ? (
                        <p className="mt-1 hidden text-sm leading-relaxed text-ash sm:line-clamp-2">{t.blurb}</p>
                      ) : null}
                      <p className="mt-auto pt-4 text-xs font-semibold">
                        {count > 0 ? (
                          <span className="inline-flex items-center gap-1.5 rounded-full bg-primarySoft px-2.5 py-1 text-primaryDark">
                            {formatCount(count)} offre{count > 1 ? "s" : ""}
                          </span>
                        ) : (
                          <span className="text-ash">Aucune offre pour l’instant</span>
                        )}
                      </p>
                    </Link>
                  </RevealItem>
                );
              })}
            </RevealGroup>
          ) : loading ? (
            <div
              role="status"
              aria-label="Chargement des métiers"
              className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-5"
            >
              {Array.from({ length: 10 }, (_, i) => (
                <div key={i} aria-hidden className="rounded-3xl border border-slate-100 bg-white p-5 shadow-soft">
                  <div className="skeleton h-12 w-12 !rounded-2xl" />
                  <div className="skeleton mt-4 h-4 w-3/4" />
                  <div className="skeleton mt-2 h-3 w-full" />
                  <div className="skeleton mt-6 h-3 w-1/2" />
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              icon={<LayoutGrid aria-hidden className="h-7 w-7" />}
              title={error ? "Les métiers n’ont pas pu être chargés" : "Le catalogue des métiers arrive"}
              description={
                error
                  ? "La connexion au catalogue a échoué. Vous pouvez réessayer ou lancer directement une recherche."
                  : "Les premiers métiers seront affichés ici dès leur ouverture sur la plateforme."
              }
              actions={
                <>
                  {error ? (
                    <button type="button" onClick={reload} className={btn("primary")}>
                      <RefreshCw aria-hidden className="h-4 w-4" />
                      Réessayer
                    </button>
                  ) : null}
                  <CtaLink href="/search" variant="outline">
                    Rechercher un artisan
                  </CtaLink>
                </>
              }
            />
          )}
        </div>

        <div className="mt-8 md:hidden">
          <CtaLink href="/metiers" variant="outline" className="w-full">
            Voir tous les métiers
            <ArrowRight aria-hidden className="h-4 w-4" />
          </CtaLink>
        </div>
      </div>
    </section>
  );
}
