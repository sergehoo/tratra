"use client";
import Link from "next/link";
import { ArrowRight, CalendarClock, Siren, Zap } from "lucide-react";
import { OnlineDot } from "@/components/market/primitives";
import { formatCount } from "@/lib/format";
import { useLanding, useTrades } from "./LandingData";
import { CONTAINER, CtaLink, Eyebrow, SECTION_Y } from "./kit";
import { Reveal, RevealGroup, RevealItem } from "./Reveal";

/** Situations d'urgence courantes, adossées aux familles réelles. */
const URGENT: { key: string; situation: string }[] = [
  { key: "plomberie", situation: "Fuite d’eau, canalisation ou WC bouché" },
  { key: "electricite", situation: "Panne de courant, disjoncteur qui saute" },
  { key: "serrurerie", situation: "Porte claquée, clé perdue ou serrure bloquée" },
  { key: "climatisation", situation: "Climatiseur en panne ou qui fuit" },
];

export default function UrgencySection() {
  const { data: stats, loading: statsLoading } = useLanding("stats");
  const { trades, loading: tradesLoading } = useTrades();
  const online = stats?.artisans_online ?? 0;

  const shortcuts = URGENT.flatMap((u) => {
    const family = trades.find((t) => t.key === u.key);
    return family ? [{ ...u, family }] : [];
  });

  return (
    <section
      id="urgences"
      aria-labelledby="urgences-titre"
      className={`relative isolate scroll-mt-20 overflow-hidden bg-night text-white lg:scroll-mt-24 ${SECTION_Y}`}
    >
      <div
        aria-hidden
        className="absolute inset-0 -z-10 bg-[radial-gradient(55%_60%_at_85%_15%,rgba(246,201,14,0.14),transparent_70%),radial-gradient(50%_60%_at_5%_100%,rgba(46,139,87,0.35),transparent_70%)]"
      />
      <div
        aria-hidden
        className="absolute inset-0 -z-10 opacity-[0.05] [background-image:repeating-linear-gradient(135deg,#F6C90E_0_2px,transparent_2px_22px)] [mask-image:linear-gradient(to_bottom,black,transparent_60%)]"
      />

      <div className={`${CONTAINER} grid items-center gap-12 lg:grid-cols-12 lg:gap-16`}>
        <Reveal className="lg:col-span-6">
          <Eyebrow tone="dark">
            <Siren aria-hidden className="h-3.5 w-3.5" />
            Urgences
          </Eyebrow>
          <h2
            id="urgences-titre"
            className="mt-4 font-display text-[1.85rem] font-extrabold leading-[1.12] tracking-tight [text-wrap:balance] sm:text-4xl lg:text-[2.75rem]"
          >
            Une <span className="text-accent">urgence</span>&nbsp;? Fuite, panne, porte claquée…
          </h2>

          <div className="mt-6 min-h-[3.5rem]">
            {online > 0 ? (
              <p className="inline-flex items-center gap-3 rounded-2xl bg-white/[0.06] px-4 py-3 text-base font-semibold ring-1 ring-inset ring-white/10">
                <OnlineDot label="" className="!gap-0" />
                <span>
                  <span className="text-accent">{formatCount(online)}</span> artisan{online > 1 ? "s" : ""} en ligne
                  maintenant
                </span>
              </p>
            ) : !stats && statsLoading ? (
              <span aria-hidden className="block h-12 w-72 max-w-full rounded-2xl bg-white/10" />
            ) : (
              <p className="max-w-xl text-base leading-relaxed text-white/75 sm:text-lg">
                Réservation immédiate dès qu’un artisan vérifié est disponible, ou planifiez l’intervention à l’heure
                qui vous arrange.
              </p>
            )}
          </div>

          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <CtaLink href="/search?online=1" variant="accent" size="lg">
              <Zap aria-hidden className="h-5 w-5" />
              Intervention immédiate
            </CtaLink>
            <CtaLink href="/search" variant="outlineLight" size="lg">
              <CalendarClock aria-hidden className="h-5 w-5" />
              Planifier une intervention
            </CtaLink>
          </div>
        </Reveal>

        <div className="lg:col-span-6">
          {shortcuts.length ? (
            <RevealGroup as="ul" className="grid gap-3 sm:grid-cols-2 sm:gap-4" stagger={0.08} delay={0.1}>
              {shortcuts.map(({ key, situation, family }) => (
                <RevealItem as="li" key={key}>
                  <Link
                    href={`${family.href}&online=1`}
                    className="group flex h-full items-start gap-4 rounded-3xl border border-white/10 bg-nightSoft/90 p-5 transition duration-300 hover:-translate-y-1 hover:border-accent/40 hover:bg-nightSoft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-night"
                  >
                    <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-accent/15 text-accent transition-colors duration-300 group-hover:bg-accent group-hover:text-night">
                      <family.icon aria-hidden className="h-6 w-6" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center justify-between gap-2">
                        <span className="font-display text-lg font-bold text-white">{family.label}</span>
                        <ArrowRight
                          aria-hidden
                          className="h-4 w-4 shrink-0 text-white/40 transition duration-300 group-hover:translate-x-1 group-hover:text-accent"
                        />
                      </span>
                      <span className="mt-1 block text-sm leading-relaxed text-white/70">{situation}</span>
                    </span>
                  </Link>
                </RevealItem>
              ))}
            </RevealGroup>
          ) : tradesLoading ? (
            <div aria-hidden className="grid gap-3 sm:grid-cols-2 sm:gap-4">
              {Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="h-[104px] rounded-3xl border border-white/10 bg-white/5" />
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
