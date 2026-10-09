import type { Metadata } from "next";
import { Compass, House, Search } from "lucide-react";
import { ButtonLink } from "@/components/ds";
import { SystemScreen, SystemTile } from "@/components/system/SystemScreen";

export const metadata: Metadata = {
  title: "Page introuvable",
  description: "Cette page n’existe pas ou a été déplacée.",
  robots: { index: false, follow: false },
};

/** Page 404 de marque (composant serveur) : rendue pour toute URL sans route. */
export default function NotFound() {
  return (
    <SystemScreen
      eyebrow="Erreur 404"
      title="Page"
      accent="introuvable"
      titleId="introuvable-titre"
      description="L’adresse saisie n’existe pas ou la page a été déplacée. Vérifiez le lien, ou repartez de l’accueil ou de la recherche d’artisans."
      visual={
        <div
          aria-hidden
          className="flex items-center justify-center gap-3 font-display text-display-xl font-extrabold text-white/90 sm:gap-4"
        >
          <span>4</span>
          <SystemTile>
            <Compass className="h-8 w-8 sm:h-10 sm:w-10" strokeWidth={2.2} />
          </SystemTile>
          <span>4</span>
        </div>
      }
      actions={
        <>
          <ButtonLink href="/" variant="accent" size="lg" leftIcon={<House aria-hidden className="h-5 w-5" />}>
            Retour à l’accueil
          </ButtonLink>
          <ButtonLink href="/search" variant="outlineLight" size="lg" leftIcon={<Search aria-hidden className="h-5 w-5" />}>
            Trouver un artisan
          </ButtonLink>
        </>
      }
    />
  );
}
