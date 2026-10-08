import type { MetadataRoute } from "next";

/**
 * Manifeste PWA (servi par Next sur /manifest.webmanifest et lié
 * automatiquement dans le <head>). Icônes générées depuis le logo officiel,
 * sur fond blanc pour rester lisibles sur tous les lanceurs.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "Tratra — Artisans vérifiés à domicile",
    short_name: "Tratra",
    description:
      "Trouvez un artisan vérifié près de chez vous : plomberie, électricité, climatisation, ménage, bricolage… Réservez en quelques minutes et suivez votre intervention.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#2e8b57",
    lang: "fr",
    dir: "ltr",
    // Pas d'`orientation` : l'app installée suit la rotation de l'appareil
    // (WCAG 1.3.4 — un appareil fixé en paysage doit rester utilisable).
    categories: ["lifestyle", "business", "productivity"],
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
    shortcuts: [
      {
        name: "Trouver un artisan",
        short_name: "Rechercher",
        description: "Parcourir les services et artisans disponibles",
        url: "/search",
        icons: [{ src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
      },
      {
        name: "Intervention immédiate",
        short_name: "Immédiat",
        description: "Voir les artisans en ligne maintenant",
        url: "/search?online=1",
        icons: [{ src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
      },
    ],
  };
}
