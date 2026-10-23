import Image from "next/image";
import type { CSSProperties, ReactNode } from "react";
import { cx } from "@/components/ds/cx";
import { storeBadges, type PublicMobileApps } from "@/lib/mobileApps";

/** Hauteur commune aux deux badges (les chartes Google et Apple imposent la même hauteur, ≥ 40 px à l'écran). */
const HEIGHT = { md: "h-10", lg: "h-11 sm:h-12" } as const;

/**
 * Badges officiels « Disponible sur Google Play » / « Télécharger dans l’App Store ».
 * Visuels servis tels quels (ni recoloration, ni animation, ni recompression) ; chaque lien ouvre la fiche du store dans un
 * nouvel onglet (`noopener noreferrer`). Rien n'est rendu — pas même le titre — quand aucun badge n'est publié.
 * Compatible Server Component.
 */
export default function StoreBadges({
  apps,
  heading,
  size = "md",
  className = "",
  style,
}: {
  apps: PublicMobileApps | null | undefined;
  heading?: ReactNode;
  size?: keyof typeof HEIGHT;
  className?: string;
  style?: CSSProperties;
}) {
  const badges = storeBadges(apps);
  if (!badges.length) return null;
  return (
    <div className={className} style={style} data-testid="store-badges">
      {heading}
      <ul className={cx("flex flex-wrap items-center gap-3", heading ? "mt-3" : "")}>
        {badges.map((b) => (
          <li key={b.kind} className="shrink-0">
            <a
              href={b.href}
              target={b.target}
              rel={b.rel}
              aria-label={b.label}
              data-store={b.kind}
              className="block rounded-[10px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-night"
            >
              <Image src={b.src} alt="" width={b.width} height={b.height} unoptimized className={cx(HEIGHT[size], "w-auto")} />
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
