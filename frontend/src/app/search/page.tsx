import type { Metadata } from "next";
import { Suspense } from "react";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";
import { SearchPageSkeleton } from "@/components/search/SearchSkeleton";
import SearchClient from "./SearchClient";

const TITLE = "Trouver un artisan près de chez vous";
const DESCRIPTION =
  "Recherchez une prestation par métier, par commune ou autour de vous : comparez les tarifs et les profils des artisans, puis réservez en quelques minutes sur Tratra.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/search" },
  openGraph: {
    type: "website",
    locale: "fr_FR",
    siteName: "Tratra",
    url: "/search",
    title: `${TITLE} · Tratra`,
    description: DESCRIPTION,
    // openGraph/twitter d'une page remplacent ceux du layout : l'image de
    // partage doit être redéclarée ici.
    images: [{ url: "/og-image.jpg", width: 1200, height: 630, alt: "Artisan menuisier au travail dans son atelier — Tratra" }],
  },
  twitter: {
    card: "summary_large_image",
    title: `${TITLE} · Tratra`,
    description: DESCRIPTION,
    images: ["/og-image.jpg"],
  },
};

export default function SearchPage() {
  return (
    <>
      <SiteHeader variant="solid" />
      <main id="contenu" tabIndex={-1} className="min-h-screen bg-canvas outline-none">
        {/* useSearchParams (état de recherche dans l'URL) exige une frontière Suspense. */}
        <Suspense fallback={<SearchPageSkeleton />}>
          <SearchClient />
        </Suspense>
      </main>
      <SiteFooter />
    </>
  );
}
