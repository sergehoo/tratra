"use client";
import StoreBadges from "@/components/site/StoreBadges";
import { useLanding } from "./LandingData";

/**
 * Badges Google Play / App Store de la landing (section principale et pied de page), à partir des liens publics partagés par
 * <LandingDataProvider> : rechargés côté client si le rendu serveur n'a pas pu les lire. Rien n'est rendu sans badge publié.
 */
export default function LandingStoreBadges({ placement }: { placement: "hero" | "footer" }) {
  const { data } = useLanding("apps");
  if (placement === "hero") {
    return (
      <StoreBadges
        apps={data}
        size="lg"
        className="tt-rise mt-8"
        style={{ animationDelay: "480ms" }}
        heading={<p className="text-sm font-medium text-white/75">Téléchargez l’application Tratra&nbsp;:</p>}
      />
    );
  }
  return (
    <StoreBadges
      apps={data}
      className="mt-8"
      heading={<h3 className="font-display text-sm font-bold uppercase tracking-[0.14em] text-white">Application mobile</h3>}
    />
  );
}
