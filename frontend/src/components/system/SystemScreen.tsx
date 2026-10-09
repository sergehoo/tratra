import Image from "next/image";
import type { ReactNode } from "react";
import { CONTAINER, Eyebrow, cx } from "@/components/ds";

/**
 * Écran système plein cadre (page introuvable, erreur inattendue).
 * Surface « night » avec halos vert / jaune, comme la landing et le panneau d'authentification.
 *
 * Aucun hook ni état : le composant est utilisable depuis un composant serveur
 * (`not-found.tsx`) comme depuis un composant client (`error.tsx`).
 */

const RING_NIGHT =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-night";

/**
 * Logo + mot-symbole (retour à l'accueil).
 * Lien natif <a> et non <Link> : depuis une page d'erreur, une navigation complète
 * garantit de repartir d'un état sain, même si l'erreur est survenue sur « / ».
 */
function BrandLink() {
  return (
    <a href="/" aria-label="Tratra — accueil" className={cx("inline-flex items-center gap-2.5 rounded-control", RING_NIGHT)}>
      <span className="grid h-11 w-11 place-items-center rounded-control bg-white shadow-hair ring-1 ring-black/5">
        <Image src="/tratra_logo.webp" alt="" width={30} height={30} priority className="h-[30px] w-[30px]" />
      </span>
      <span aria-hidden className="font-display text-[1.35rem] font-extrabold tracking-tight text-white">
        Tra<span className="text-accent">tra</span>
      </span>
    </a>
  );
}

/** Pastille jaune portant une icône (visuel central des écrans système). */
export function SystemTile({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span
      aria-hidden
      className={cx(
        "grid h-16 w-16 animate-scaleIn place-items-center rounded-card bg-accent text-night shadow-glowAccent sm:h-20 sm:w-20",
        className,
      )}
    >
      {children}
    </span>
  );
}

export interface SystemScreenProps {
  /** Sur-titre (pastille) — ex. « Erreur 404 ». */
  eyebrow: string;
  /** Début du <h1> (unique titre de la page). */
  title: string;
  /** Fin du <h1>, mise en valeur en jaune et soulignée. */
  accent: string;
  /** Identifiant du <h1>, cible de aria-labelledby. */
  titleId: string;
  description: ReactNode;
  /** Visuel au-dessus du sur-titre (décoratif). */
  visual: ReactNode;
  /** Boutons d'action. */
  actions: ReactNode;
}

export function SystemScreen({ eyebrow, title, accent, titleId, description, visual, actions }: SystemScreenProps) {
  return (
    <div className="relative isolate flex min-h-[100svh] flex-col overflow-hidden bg-night text-white">
      {/* Décor : halos vert / jaune (aucune information) */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute -left-24 -top-24 h-[26rem] w-[26rem] rounded-full bg-primary/40 blur-3xl" />
        <div className="absolute -bottom-28 -right-20 h-[22rem] w-[22rem] rounded-full bg-accent/20 blur-3xl" />
      </div>

      <header className={cx(CONTAINER, "pt-5")}>
        <BrandLink />
      </header>

      <main id="contenu" className="flex flex-1 items-center justify-center px-4 py-12 sm:px-6">
        <section aria-labelledby={titleId} className="w-full max-w-xl animate-rise text-center">
          <div className="flex justify-center">{visual}</div>

          <Eyebrow tone="dark" className="mt-8">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-accent" />
            {eyebrow}
          </Eyebrow>

          <h1
            id={titleId}
            className="mt-5 font-display text-h1 font-extrabold [text-wrap:balance] sm:text-display-lg"
          >
            {title}{" "}
            <span className="relative inline-block whitespace-nowrap text-accent">
              {accent}
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
            </span>
          </h1>

          <p className="mx-auto mt-7 max-w-md text-base leading-relaxed text-white/80">{description}</p>

          <div className="mt-9 flex flex-col items-stretch justify-center gap-3 sm:flex-row sm:items-center">{actions}</div>
        </section>
      </main>
    </div>
  );
}
