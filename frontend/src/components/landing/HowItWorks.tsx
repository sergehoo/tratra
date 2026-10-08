import { ArrowRight, CalendarCheck, Search, ShieldCheck, UserCheck, Wallet } from "lucide-react";
import { ESCROW_ENABLED } from "@/lib/config";
import { CONTAINER, CtaLink, SECTION_Y, SectionHeading } from "./kit";
import { GrowLine, Reveal, RevealGroup, RevealItem } from "./Reveal";

/** Parcours réel d'une réservation sur Tratra (Server Component). */
const STEPS = [
  {
    icon: Search,
    title: "Recherchez",
    text: "Choisissez un métier et indiquez votre commune, ou laissez Tratra vous localiser.",
  },
  {
    icon: UserCheck,
    title: "Comparez les profils",
    text: "Badge « Vérifié » après contrôle de l’identité et des documents, tarifs affichés, avis de clients après une mission terminée.",
  },
  {
    icon: CalendarCheck,
    title: "Réservez",
    text: "Intervention immédiate ou à l’heure que vous choisissez, puis suivi de l’artisan en temps réel.",
  },
  // Séquestre annoncé uniquement s'il est réellement actif (ESCROW_ENABLED).
  ESCROW_ENABLED
    ? {
        icon: ShieldCheck,
        title: "Payez en sécurité, puis notez",
        text: "L’argent n’est versé à l’artisan qu’une fois la mission terminée. Vous notez ensuite la prestation.",
      }
    : {
        icon: Wallet,
        title: "Payez après l’intervention, puis notez",
        text: "Vous réglez l’artisan une fois la mission terminée, puis vous notez la prestation.",
      },
];

export default function HowItWorks() {
  return (
    <section
      id="comment"
      aria-labelledby="comment-titre"
      className={`scroll-mt-20 bg-white lg:scroll-mt-24 ${SECTION_Y}`}
    >
      <div className={CONTAINER}>
        <Reveal>
          <SectionHeading
            id="comment-titre"
            eyebrow="Comment ça marche"
            align="center"
            title={
              <>
                Un artisan chez vous en <span className="text-primary">4 étapes</span>
              </>
            }
            description="Un parcours simple et encadré, de la recherche jusqu’au paiement."
          />
        </Reveal>

        <div className="relative mt-14 lg:mt-20">
          {/* Ligne de progression horizontale (bureau) ; segments verticaux par étape sur mobile */}
          <span aria-hidden className="absolute left-[12.5%] right-[12.5%] top-7 hidden h-0.5 bg-slate-200 lg:block" />
          <GrowLine
            axis="x"
            className="absolute left-[12.5%] right-[12.5%] top-7 !hidden h-0.5 bg-gradient-to-r from-primary to-accent lg:!block"
          />

          <RevealGroup as="ol" className="relative grid gap-10 lg:grid-cols-4 lg:gap-8" stagger={0.14}>
            {STEPS.map(({ icon: Icon, title, text }, i) => (
              <RevealItem
                as="li"
                key={title}
                className="relative flex gap-5 lg:flex-col lg:items-center lg:text-center"
              >
                {i < STEPS.length - 1 ? (
                  <span
                    aria-hidden
                    className="absolute -bottom-9 left-[27px] top-[60px] w-0.5 rounded-full bg-gradient-to-b from-primary to-accent lg:hidden"
                  />
                ) : null}
                <span className="relative grid h-14 w-14 shrink-0 place-items-center rounded-full bg-white text-primaryDark shadow-soft ring-2 ring-primary/80">
                  <Icon aria-hidden className="h-6 w-6" />
                  <span
                    aria-hidden
                    className="absolute -right-1 -top-1 grid h-6 w-6 place-items-center rounded-full bg-accent font-display text-xs font-extrabold text-night ring-2 ring-white"
                  >
                    {i + 1}
                  </span>
                </span>
                <div className="min-w-0 pt-1 lg:mt-5 lg:pt-0">
                  <h3 className="font-display text-lg font-bold text-ink">
                    <span className="sr-only">Étape {i + 1} : </span>
                    {title}
                  </h3>
                  <p className="mt-2 text-[15px] leading-relaxed text-ash lg:mx-auto lg:max-w-[16rem]">{text}</p>
                </div>
              </RevealItem>
            ))}
          </RevealGroup>
        </div>

        <Reveal className="mt-14 flex justify-center" delay={0.1}>
          <CtaLink href="/search" variant="primary" size="lg">
            Commencer ma recherche
            <ArrowRight aria-hidden className="h-5 w-5" />
          </CtaLink>
        </Reveal>
      </div>
    </section>
  );
}
