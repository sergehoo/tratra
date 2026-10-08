import type { MetadataRoute } from "next";

const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "https://tratra.net").replace(/\/+$/, "");

/**
 * sitemap.xml — uniquement les pages publiques indexables, sous leur URL
 * canonique. Exclus : /login (noindex) et les variantes /search?metier=…,
 * qui déclarent /search comme canonical (contenu rendu côté client). Indexer
 * un métier exigerait une route dédiée rendue côté serveur (/metiers/[slug]).
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  return [
    { url: `${SITE_URL}/`, lastModified: now, changeFrequency: "daily", priority: 1 },
    { url: `${SITE_URL}/search`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: `${SITE_URL}/register`, lastModified: now, changeFrequency: "monthly", priority: 0.5 },
  ];
}
