"use client";
import { ArrowRight, HardHat, LayoutDashboard, Search } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { ESCROW_ENABLED } from "@/lib/config";
import { registerHref } from "@/lib/links";
import { CONTAINER, CtaLink, Eyebrow } from "./kit";
import { Reveal } from "./Reveal";

/** Bande d'appel final (jaune) : recrutement artisans + recherche client. */
export default function FinalCta() {
  const { user } = useAuth();
  const isArtisan = user?.user_type === "handyman";

  return (
    <section aria-labelledby="cta-titre" className="relative isolate overflow-hidden bg-accent">
      <div
        aria-hidden
        className="absolute inset-0 -z-10 opacity-[0.07] [background-image:repeating-linear-gradient(135deg,#0b1210_0_2px,transparent_2px_26px)]"
      />
      <div aria-hidden className="absolute -right-20 -top-28 -z-10 h-80 w-80 rounded-full bg-white/40 blur-3xl" />

      <div className={`${CONTAINER} grid items-center gap-10 py-16 md:py-20 lg:grid-cols-12 lg:gap-14`}>
        <Reveal className="lg:col-span-7">
          <Eyebrow tone="accent">
            <HardHat aria-hidden className="h-3.5 w-3.5" />
            Artisans
          </Eyebrow>
          <h2
            id="cta-titre"
            className="mt-4 font-display text-[1.85rem] font-extrabold leading-[1.1] tracking-tight text-night [text-wrap:balance] sm:text-4xl lg:text-[2.75rem]"
          >
            Vous êtes artisan&nbsp;? Recevez des missions près de chez vous
          </h2>
          <p className="mt-4 max-w-xl text-base leading-relaxed text-night/80 sm:text-lg">
            Créez votre profil, faites vérifier vos documents et recevez des demandes de clients dans votre zone, avec
            {ESCROW_ENABLED ? " un paiement sécurisé à la fin de chaque mission." : " un paiement à la fin de chaque intervention."}
          </p>
          <div className="mt-8">
            {isArtisan ? (
              <CtaLink href="/dashboard/provide" variant="night" size="lg">
                <LayoutDashboard aria-hidden className="h-5 w-5" />
                Accéder à mon espace artisan
              </CtaLink>
            ) : (
              <CtaLink href={registerHref("handyman")} variant="night" size="lg">
                <HardHat aria-hidden className="h-5 w-5" />
                Devenir artisan Tratra
              </CtaLink>
            )}
          </div>
        </Reveal>

        <Reveal className="lg:col-span-5" delay={0.12}>
          <div className="rounded-3xl bg-white/60 p-6 shadow-[0_24px_60px_-28px_rgba(11,18,16,.45)] ring-1 ring-night/10 backdrop-blur sm:p-8">
            <span className="grid h-12 w-12 place-items-center rounded-2xl bg-night text-accent">
              <Search aria-hidden className="h-6 w-6" />
            </span>
            <h3 className="mt-5 font-display text-xl font-bold text-night sm:text-2xl">Besoin d’un artisan&nbsp;?</h3>
            <p className="mt-2 leading-relaxed text-night/80">
              Trouvez un professionnel vérifié pour un dépannage, des travaux ou l’entretien de votre logement.
            </p>
            <CtaLink href="/search" variant="outlineNight" size="lg" className="mt-6 w-full sm:w-auto">
              Trouver un artisan
              <ArrowRight aria-hidden className="h-5 w-5" />
            </CtaLink>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
