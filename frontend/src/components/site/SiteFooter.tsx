import Image from "next/image";
import Link from "next/link";
import { BadgeCheck, Navigation, ShieldCheck, Wallet } from "lucide-react";
import { BrandWordmark } from "@/components/ds/BrandWordmark";
import { CONTAINER } from "@/components/ds/layout";
import { ESCROW_ENABLED } from "@/lib/config";
import { registerHref } from "@/lib/links";

export interface FooterLink {
  label: string;
  href: string;
}

/**
 * Métiers par défaut : uniquement des slugs de catégories existants côté
 * backend (aucun lien mort). La landing transmet les familles réellement
 * résolues via la prop `trades`.
 */
const DEFAULT_TRADES: FooterLink[] = [
  { label: "Plomberie", href: "/search?metier=plomberie" },
  { label: "Électricité", href: "/search?metier=electricite" },
  { label: "Climatisation", href: "/search?metier=climatisation" },
  { label: "Serrurerie", href: "/search?metier=serrurerie" },
  { label: "Peinture", href: "/search?metier=peinture" },
  { label: "Ménage", href: "/search?metier=menage" },
];

const PLATFORM: FooterLink[] = [
  { label: "Rechercher un artisan", href: "/search" },
  { label: "Devenir artisan", href: registerHref("handyman") },
  { label: "Créer un compte entreprise", href: registerHref("entreprise") },
  { label: "Connexion", href: "/login" },
];

const TRUST: FooterLink[] = [
  { label: "Nos garanties", href: "/#confiance" },
  { label: "Comment ça marche", href: "/#comment" },
  { label: "Avis clients", href: "/#avis" },
];

const LINK =
  "inline-flex min-h-[40px] items-center rounded-lg text-[15px] text-white/70 transition-colors duration-base hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

function Column({ title, links, id }: { title: string; links: FooterLink[]; id: string }) {
  return (
    <nav aria-labelledby={id}>
      <h3 id={id} className="font-display text-sm font-bold uppercase tracking-[0.14em] text-white">
        {title}
      </h3>
      <ul className="mt-4 space-y-0.5">
        {links.map((l) => (
          <li key={l.href}>
            <Link href={l.href} className={LINK}>
              {l.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** Pied de page public (landing, recherche). Compatible Server Component. */
export default function SiteFooter({ trades }: { trades?: FooterLink[] }) {
  const tradeLinks = (trades && trades.length ? trades : DEFAULT_TRADES).slice(0, 8);
  const year = new Date().getFullYear();

  return (
    <footer className="relative overflow-hidden bg-night text-white/70">
      <h2 className="sr-only">Plan du site Tratra</h2>
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 h-80 w-[48rem] -translate-x-1/2 rounded-full bg-primary/20 blur-3xl"
      />
      <div className={`relative grid gap-12 py-16 md:py-20 lg:grid-cols-12 ${CONTAINER}`}>
        <div className="lg:col-span-4">
          <Link
            href="/"
            className="inline-flex items-center gap-3 rounded-panel focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <span className="grid h-12 w-12 place-items-center rounded-panel bg-white">
              <Image src="/tratra_logo.webp" alt="Tratra" width={36} height={36} className="h-9 w-9" />
            </span>
            <BrandWordmark tone="night" className="text-[2.3rem]" />
          </Link>
          <p className="mt-5 max-w-sm text-[15px] leading-relaxed">
            {ESCROW_ENABLED
              ? "Tratra met en relation particuliers et entreprises avec des artisans vérifiés, avec un paiement sécurisé et un suivi transparent de chaque intervention."
              : "Tratra met en relation particuliers et entreprises avec des artisans vérifiés, avec un paiement à la fin de l’intervention et un suivi transparent de chaque mission."}
          </p>
          <ul className="mt-6 flex flex-wrap gap-x-5 gap-y-2 text-sm text-white/80">
            <li className="inline-flex items-center gap-2">
              <BadgeCheck aria-hidden className="h-4 w-4 text-accent" /> Artisans vérifiés
            </li>
            <li className="inline-flex items-center gap-2">
              {ESCROW_ENABLED ? (
                <>
                  <ShieldCheck aria-hidden className="h-4 w-4 text-accent" /> Paiement sécurisé
                </>
              ) : (
                <>
                  <Wallet aria-hidden className="h-4 w-4 text-accent" /> Paiement après l’intervention
                </>
              )}
            </li>
            <li className="inline-flex items-center gap-2">
              <Navigation aria-hidden className="h-4 w-4 text-accent" /> Suivi en temps réel
            </li>
          </ul>
        </div>

        <div className="grid grid-cols-2 gap-x-6 gap-y-10 sm:grid-cols-3 lg:col-span-8 lg:pl-10">
          <Column
            id="footer-metiers"
            title="Métiers"
            links={[...tradeLinks, { label: "Tous les métiers", href: "/search" }]}
          />
          <Column id="footer-plateforme" title="Plateforme" links={PLATFORM} />
          <Column id="footer-confiance" title="Confiance" links={TRUST} />
        </div>
      </div>

      <div className="relative border-t border-white/10">
        <div className={`py-6 text-sm text-white/60 ${CONTAINER}`}>
          <p>© {year} Tratra. Tous droits réservés.</p>
        </div>
      </div>
    </footer>
  );
}
