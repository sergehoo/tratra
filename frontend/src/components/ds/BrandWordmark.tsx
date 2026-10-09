import { cx } from "./cx";

/**
 * Nom de l'application « Tratra » en script de marque (Bonskin) — seul endroit où cette police
 * est utilisée. `light` : fond clair (encre + vert) ; `night` : fond sombre (blanc + jaune).
 * Décoratif : le nom accessible est porté par le lien/le logo parent (aria-label).
 */
export function BrandWordmark({
  tone = "light",
  className = "text-[2.1rem]",
}: {
  tone?: "light" | "night";
  className?: string;
}) {
  return (
    <span aria-hidden className={cx("font-brand font-normal leading-none tracking-normal", tone === "night" ? "text-white" : "text-ink", className)}>
      Tra<span className={tone === "night" ? "text-accent" : "text-primary"}>tra</span>
    </span>
  );
}
