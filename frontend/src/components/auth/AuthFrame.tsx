import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowLeft, BadgeCheck, Navigation, ShieldCheck, Wallet, type LucideIcon } from "lucide-react";
import { ButtonLink, Card, Eyebrow, cx } from "@/components/ds";
import { ESCROW_ENABLED } from "@/lib/config";

/**
 * Cadre commun des pages d'authentification (connexion, inscription).
 *  - >= lg : deux colonnes — panneau « night » (image, halos vert/jaune, garanties
 *    réelles de la plateforme) à gauche, formulaire à droite ;
 *  - mobile : en-tête de marque sombre, puis formulaire pleine largeur en feuille arrondie.
 * Le composant ne porte aucune logique métier : il ne fait que cadrer son contenu.
 */

const HERO_IMAGE = "/images/hero/hero-main.jpg";

const RING_NIGHT =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-night";

/**
 * Garanties RÉELLES, reprises de la landing (Hero / TrustSection) : badge « Vérifié »
 * après contrôle KYC, paiement selon ESCROW_ENABLED, suivi de l'intervention.
 */
const PROMISES: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: BadgeCheck,
    title: "Artisans vérifiés",
    text: "Le badge « Vérifié » n’apparaît qu’après contrôle de l’identité et des documents par l’équipe Tratra.",
  },
  ESCROW_ENABLED
    ? {
        icon: ShieldCheck,
        title: "Paiement sous séquestre",
        text: "Votre paiement est conservé par la plateforme et n’est versé à l’artisan qu’une fois la mission terminée.",
      }
    : {
        icon: Wallet,
        title: "Paiement à la fin de l’intervention",
        text: "Vous réglez l’artisan une fois la prestation réalisée ; la réservation et le montant restent tracés sur Tratra.",
      },
  {
    icon: Navigation,
    title: "Suivi en temps réel",
    text: "Suivez l’avancement de votre intervention, du départ de l’artisan jusqu’à la fin de la mission.",
  },
];

/** Logo + mot-symbole sur fond sombre (lien vers l'accueil). */
function BrandLink() {
  return (
    <Link href="/" aria-label="Tratra — accueil" className={cx("inline-flex items-center gap-2.5 rounded-control", RING_NIGHT)}>
      <span className="grid h-11 w-11 place-items-center rounded-control bg-white shadow-hair ring-1 ring-black/5">
        <Image src="/tratra_logo.webp" alt="" width={30} height={30} priority className="h-[30px] w-[30px]" />
      </span>
      <span aria-hidden className="font-display text-[1.35rem] font-extrabold tracking-tight text-white">
        Tra<span className="text-accent">tra</span>
      </span>
    </Link>
  );
}

/** Panneau de marque (>= lg) : image, halos, message de valeur et garanties. */
function BrandPanel({ lead }: { lead: string }) {
  return (
    <aside aria-label="Pourquoi Tratra" className="relative isolate hidden bg-night text-white lg:block">
      {/* Décor : photo + voiles (contraste AA du texte blanc) + halos vert / jaune */}
      <div aria-hidden className="absolute inset-0 -z-10 overflow-hidden">
        <Image
          src={HERO_IMAGE}
          alt=""
          fill
          sizes="(min-width: 1024px) 46vw, 1px"
          className="object-cover object-center"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-night/90 via-night/85 to-night/95" />
        <div className="absolute -left-24 -top-24 h-[26rem] w-[26rem] rounded-full bg-primary/40 blur-3xl" />
        <div className="absolute -bottom-28 -right-20 h-[22rem] w-[22rem] rounded-full bg-accent/20 blur-3xl" />
      </div>

      <div className="flex min-h-screen flex-col gap-10 p-10 xl:p-14 lg:sticky lg:top-0">
        <div>
          <BrandLink />
        </div>

        <div className="my-auto max-w-xl animate-rise">
          <Eyebrow tone="dark">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-accent" />
            Artisans à domicile
          </Eyebrow>

          <p className="mt-5 font-display text-4xl font-extrabold leading-[1.1] tracking-tight [text-wrap:balance] xl:text-[2.75rem]">
            L’artisan qu’il vous faut,{" "}
            <span className="relative inline-block whitespace-nowrap text-accent">
              vérifié
              <svg
                aria-hidden
                viewBox="0 0 200 14"
                preserveAspectRatio="none"
                className="absolute -bottom-2 left-0 h-3 w-full text-accent"
              >
                <path
                  d="M3 10 C 45 3, 120 2, 197 7"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={4}
                  strokeLinecap="round"
                  vectorEffect="non-scaling-stroke"
                />
              </svg>
            </span>{" "}
            et disponible près de chez vous
          </p>
          <p className="mt-6 text-base leading-relaxed text-white/80">{lead}</p>

          <ul className="mt-9 space-y-3">
            {PROMISES.map(({ icon: Icon, title, text }) => (
              <li
                key={title}
                className="flex items-start gap-4 rounded-panel bg-white/[0.06] p-4 ring-1 ring-inset ring-white/10 backdrop-blur"
              >
                <span
                  aria-hidden
                  className="grid h-11 w-11 shrink-0 place-items-center rounded-control bg-white/10 text-accent ring-1 ring-inset ring-white/15"
                >
                  <Icon className="h-5 w-5" />
                </span>
                <div className="min-w-0">
                  <p className="font-display text-base font-bold">{title}</p>
                  <p className="mt-1 text-sm leading-relaxed text-white/75">{text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </aside>
  );
}

export interface AuthFrameProps {
  /** Sur-titre de la carte (pastille). */
  eyebrow: string;
  /** Unique <h1> de la page. */
  title: string;
  subtitle: string;
  /** Phrase d'accroche du panneau de marque (>= lg). */
  lead: string;
  /** Largeur maximale du formulaire sur grand écran. */
  width?: "md" | "lg";
  children: ReactNode;
}

export function AuthFrame({ eyebrow, title, subtitle, lead, width = "md", children }: AuthFrameProps) {
  const cardWidth = width === "lg" ? "lg:max-w-lg" : "lg:max-w-md";
  const innerWidth = width === "lg" ? "max-w-lg" : "max-w-md";

  return (
    <div className="min-h-screen bg-canvas text-ink lg:grid lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <a href="#contenu" className="skip-link">
        Aller au contenu
      </a>

      <BrandPanel lead={lead} />

      <div className="flex min-h-screen min-w-0 flex-col">
        <header>
          {/* Mobile : en-tête de marque */}
          <div className="relative isolate overflow-hidden bg-night px-4 pb-14 pt-5 sm:px-6 lg:hidden">
            <div aria-hidden className="absolute -left-16 -top-20 -z-10 h-56 w-56 rounded-full bg-primary/50 blur-3xl" />
            <div aria-hidden className="absolute -bottom-16 -right-10 -z-10 h-44 w-44 rounded-full bg-accent/20 blur-3xl" />
            <div className="mx-auto flex w-full max-w-xl items-center justify-between gap-3">
              <BrandLink />
              <ButtonLink
                href="/"
                variant="outlineLight"
                leftIcon={<ArrowLeft aria-hidden className="h-4 w-4" />}
              >
                Accueil
              </ButtonLink>
            </div>
          </div>
          {/* Bureau : retour discret à l'accueil (le logo est dans le panneau) */}
          <div className="hidden justify-end px-10 pt-6 lg:flex">
            <ButtonLink href="/" variant="ghost" leftIcon={<ArrowLeft aria-hidden className="h-4 w-4" />}>
              Accueil
            </ButtonLink>
          </div>
        </header>

        <main id="contenu" className="flex flex-1 flex-col lg:items-center lg:justify-center lg:px-10 lg:pb-14 lg:pt-4">
          <Card
            padding="none"
            className={cx(
              "relative w-full animate-rise px-4 pb-12 pt-8 sm:px-8 lg:p-10",
              // Mobile : feuille blanche arrondie qui chevauche l'en-tête de marque
              // (`relative` : elle se peint au-dessus de l'en-tête, qui est positionné).
              "-mt-6 flex-1 max-lg:rounded-b-none max-lg:rounded-t-sheet max-lg:border-0 max-lg:shadow-none lg:mt-0 lg:flex-none",
              cardWidth,
            )}
          >
            <div className={cx("mx-auto w-full lg:max-w-none", innerWidth)}>
              <Eyebrow>{eyebrow}</Eyebrow>
              <h1 className="mt-4 font-display text-2xl font-extrabold leading-tight tracking-tight text-ink [text-wrap:balance] sm:text-[2rem]">
                {title}
              </h1>
              <span aria-hidden className="mt-3 block h-1 w-10 rounded-full bg-accent" />
              <p className="mt-3 text-sm leading-relaxed text-ash sm:text-base">{subtitle}</p>
              <div className="mt-7">{children}</div>
            </div>
          </Card>
        </main>
      </div>
    </div>
  );
}
