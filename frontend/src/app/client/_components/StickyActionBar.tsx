import type { ReactNode } from "react";
import { cx } from "@/components/ds";

/**
 * Barre d'action collante des tunnels (mobile) : reste visible au-dessus de la
 * navigation basse (hauteur issue du jeton `--tt-bottom-nav-height` + zone de
 * sécurité de l'appareil). Dès `lg`, il n'y a plus de navigation basse : la barre
 * redevient un simple bloc dans le flux.
 * À placer en dernier enfant d'un conteneur qui occupe la largeur de la page
 * (le débord latéral `-mx` reprend les gouttières de <main>).
 */
export function StickyActionBar({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cx(
        "sticky z-30 -mx-4 border-t border-lineSoft bg-white/90 px-4 py-3 shadow-soft backdrop-blur-md sm:-mx-6 sm:px-6",
        "bottom-[calc(var(--tt-bottom-nav-height)_+_env(safe-area-inset-bottom))]",
        "lg:static lg:mx-0 lg:border-0 lg:bg-transparent lg:p-0 lg:shadow-none lg:backdrop-blur-none",
        className,
      )}
    >
      {children}
    </div>
  );
}
