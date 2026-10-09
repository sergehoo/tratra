import type { MetadataRoute } from "next";

const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "https://tratra.net").replace(/\/+$/, "");

/**
 * robots.txt — les pages publiques (accueil, recherche) sont indexables ;
 * les espaces connectés et la page hors-ligne du service worker ne le sont pas.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/search"],
        disallow: ["/dashboard", "/client", "/worker", "/company", "/admin", "/offline"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
