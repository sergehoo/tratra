import { IdCard, MessageSquareQuote, Navigation, Scale, ShieldCheck, Wallet } from "lucide-react";
import { ESCROW_ENABLED } from "@/lib/config";
import { CONTAINER, SECTION_Y, SectionHeading } from "./kit";
import { Reveal, RevealGroup, RevealItem } from "./Reveal";

/** Garantie de paiement : séquestre uniquement s'il est réellement actif (ESCROW_ENABLED). */
const PAYMENT = ESCROW_ENABLED
  ? {
      icon: ShieldCheck,
      title: "Paiement sous séquestre",
      text: "Votre paiement est conservé par la plateforme et n’est versé à l’artisan qu’une fois la mission terminée.",
    }
  : {
      icon: Wallet,
      title: "Paiement à la fin de l’intervention",
      text: "Vous réglez l’artisan une fois la prestation réalisée ; la réservation et le montant restent tracés sur Tratra.",
    };

/**
 * Garanties RÉELLES de la plateforme (KYC et badge « Vérifié », paiement, suivi,
 * litiges, avis de missions terminées). Server Component.
 */
export default function TrustSection() {
  return (
    <section
      id="confiance"
      aria-labelledby="confiance-titre"
      className={`relative isolate scroll-mt-20 overflow-hidden bg-[#f3faf6] lg:scroll-mt-24 ${SECTION_Y}`}
    >
      <div
        aria-hidden
        className="absolute -right-40 -top-40 -z-10 h-[28rem] w-[28rem] rounded-full bg-primary/10 blur-3xl"
      />
      <div className={CONTAINER}>
        <Reveal>
          <SectionHeading
            id="confiance-titre"
            eyebrow="Confiance"
            title={
              <>
                Votre tranquillité, <span className="text-primary">garantie par la plateforme</span>
              </>
            }
            description={`Vérification des artisans, ${
              ESCROW_ENABLED ? "paiement protégé" : "paiement à la fin de l’intervention"
            }, suivi et médiation : chaque intervention est encadrée de bout en bout.`}
          />
        </Reveal>

        <RevealGroup as="ul" className="mt-12 grid gap-4 sm:gap-5 md:grid-cols-2 lg:grid-cols-6">
          {/* Deux garanties majeures, mises en avant */}
          <RevealItem as="li" className="md:col-span-1 lg:col-span-3">
            <article className="relative h-full overflow-hidden rounded-3xl bg-primaryDark p-7 text-white shadow-strong sm:p-9">
              <div aria-hidden className="absolute -right-16 -top-16 h-56 w-56 rounded-full bg-primary/60 blur-2xl" />
              <span className="relative grid h-14 w-14 place-items-center rounded-2xl bg-white/10 text-accent ring-1 ring-inset ring-white/15">
                <IdCard aria-hidden className="h-7 w-7" />
              </span>
              <h3 className="relative mt-6 font-display text-xl font-bold sm:text-2xl">
                Identité et documents vérifiés
              </h3>
              <p className="relative mt-3 max-w-md leading-relaxed text-white/90">
                Chaque artisan transmet sa pièce d’identité et ses justificatifs, contrôlés par l’équipe Tratra. Le
                badge « Vérifié » n’apparaît qu’après validation&nbsp;: filtrez «&nbsp;Profils vérifiés&nbsp;» pour ne
                voir qu’eux.
              </p>
            </article>
          </RevealItem>

          <RevealItem as="li" className="md:col-span-1 lg:col-span-3">
            <article className="relative h-full overflow-hidden rounded-3xl bg-night p-7 text-white shadow-strong sm:p-9">
              <div aria-hidden className="absolute -bottom-20 -right-10 h-56 w-56 rounded-full bg-accent/20 blur-2xl" />
              <span className="relative grid h-14 w-14 place-items-center rounded-2xl bg-accent text-night">
                <PAYMENT.icon aria-hidden className="h-7 w-7" />
              </span>
              <h3 className="relative mt-6 font-display text-xl font-bold sm:text-2xl">{PAYMENT.title}</h3>
              <p className="relative mt-3 max-w-md leading-relaxed text-white/85">{PAYMENT.text}</p>
            </article>
          </RevealItem>

          {[
            {
              icon: Navigation,
              title: "Suivi en temps réel",
              text: "Suivez l’avancement de votre intervention, du départ de l’artisan jusqu’à la fin de la mission.",
            },
            ESCROW_ENABLED
              ? {
                  icon: Scale,
                  title: "Litiges et remboursement",
                  text: "Un problème ? Ouvrez un litige : l’équipe Tratra examine le dossier et peut rembourser le séquestre.",
                }
              : {
                  icon: Scale,
                  title: "Litiges et médiation",
                  text: "Un problème ? Ouvrez un litige : l’équipe Tratra examine le dossier et assure la médiation avec l’artisan.",
                },
            {
              icon: MessageSquareQuote,
              title: "Avis authentiques",
              text: "Seul le client d’une mission terminée sur Tratra peut la noter : chaque avis publié est rattaché à cette mission.",
            },
          ].map(({ icon: Icon, title, text }, i) => (
            <RevealItem as="li" key={title} className={`lg:col-span-2 ${i === 2 ? "md:col-span-2" : "md:col-span-1"}`}>
              <article className="group h-full rounded-3xl border border-white bg-white p-7 shadow-soft transition duration-300 hover:-translate-y-1 hover:shadow-strong">
                <span className="grid h-12 w-12 place-items-center rounded-2xl bg-primarySoft text-primaryDark transition-colors duration-300 group-hover:bg-accent group-hover:text-ink">
                  <Icon aria-hidden className="h-6 w-6" />
                </span>
                <h3 className="mt-5 font-display text-lg font-bold text-ink">{title}</h3>
                <p className="mt-2 text-[15px] leading-relaxed text-ash">{text}</p>
              </article>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  );
}
