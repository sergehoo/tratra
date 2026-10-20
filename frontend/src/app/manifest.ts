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
    // Raccourcis (appui long sur l'icône installée) : les mêmes que l'application mobile. Les pages de l'espace demandent la connexion
    // si nécessaire ; aucune donnée n'est exposée par le raccourci lui-même.
    shortcuts: [
      {
        name: "Nouvelle demande",
        short_name: "Demander",
        description: "Trouver un artisan et réserver une intervention",
        url: "/search",
        icons: [{ src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
      },
      {
        name: "Mes réservations et missions",
        short_name: "Missions",
        description: "Suivre mes réservations et les missions à traiter",
        url: "/dashboard/bookings",
        icons: [{ src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
      },
      {
        name: "Messages",
        short_name: "Messages",
        description: "Mes conversations",
        url: "/dashboard/messages",
        icons: [{ src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
      },
      {
        name: "Mon espace professionnel",
        short_name: "Espace pro",
        description: "Mes offres, ma vérification et mes missions",
        url: "/dashboard/provider",
        icons: [{ src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
      },
    ],
  };
}
