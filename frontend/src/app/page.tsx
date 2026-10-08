import BusinessSection from "@/components/landing/BusinessSection";
import FeaturedArtisans from "@/components/landing/FeaturedArtisans";
import FinalCta from "@/components/landing/FinalCta";
import Hero from "@/components/landing/Hero";
import HowItWorks from "@/components/landing/HowItWorks";
import { LandingDataProvider, type LandingEndpoints } from "@/components/landing/LandingData";
import LatestServices from "@/components/landing/LatestServices";
import ReviewsSection from "@/components/landing/ReviewsSection";
import StatsBand from "@/components/landing/StatsBand";
import TradesSection from "@/components/landing/TradesSection";
import TrustSection from "@/components/landing/TrustSection";
import UrgencySection from "@/components/landing/UrgencySection";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";
import { SHARE } from "@/lib/config";
import { publicGet, resultsOf } from "@/lib/public";
import { resolveTrades } from "@/lib/trades";
import type {
  Category,
  FeaturedArtisansResponse,
  Paginated,
  PublicReviewsResponse,
  PublicStats,
  Service,
  SubscriptionPlan,
} from "@/lib/types";
import type { Metadata } from "next";

/** Landing régénérée au plus toutes les 5 minutes (ISR). */
export const revalidate = 300;

/**
 * Titre et description hérités du layout ; canonical et og:url propres à
 * l'accueil. Un `openGraph` de page remplace entièrement celui du layout : le
 * bloc est donc redéclaré en entier.
 */
export const metadata: Metadata = {
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    locale: "fr_FR",
    url: "/",
    siteName: "Tratra",
    title: SHARE.title,
    description: SHARE.description,
    images: [SHARE.image],
  },
};

const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "https://tratra.net").replace(/\/+$/, "");

/** Endpoints publics (sans authentification) consommés par la landing. */
const ENDPOINTS: LandingEndpoints = {
  stats: "/public/stats/",
  categories: "/categories/?page_size=100&ordering=name",
  featured: "/handymen/featured/?limit=8",
  reviews: "/reviews/public/?limit=6",
  services: "/services/?is_active=true&page_size=6&sort=recent",
  plans: "/subscription-plans/?audience=business",
};

/** Données structurées (Organization + WebSite/SearchAction), « < » échappé. */
function jsonLd(): string {
  const data = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Organization",
        "@id": `${SITE_URL}/#organization`,
        name: "Tratra",
        url: SITE_URL,
        logo: `${SITE_URL}/tratra_logo.webp`,
      },
      {
        "@type": "WebSite",
        "@id": `${SITE_URL}/#website`,
        name: "Tratra",
        url: SITE_URL,
        inLanguage: "fr",
        publisher: { "@id": `${SITE_URL}/#organization` },
        potentialAction: {
          "@type": "SearchAction",
          target: `${SITE_URL}/search?q={search_term_string}`,
          "query-input": "required name=search_term_string",
        },
      },
    ],
  };
  return JSON.stringify(data).replace(/</g, "\\u003c");
}

export default async function HomePage() {
  const opts = { revalidate: 300, timeoutMs: 3500 };
  const [stats, categories, featured, reviews, services, plans] = await Promise.all([
    publicGet<PublicStats>(ENDPOINTS.stats, opts),
    publicGet<Paginated<Category> | Category[]>(ENDPOINTS.categories, opts),
    publicGet<FeaturedArtisansResponse>(ENDPOINTS.featured, opts),
    publicGet<PublicReviewsResponse>(ENDPOINTS.reviews, opts),
    publicGet<Paginated<Service> | Service[]>(ENDPOINTS.services, opts),
    publicGet<Paginated<SubscriptionPlan> | SubscriptionPlan[]>(ENDPOINTS.plans, opts),
  ]);

  // Liens « Métiers » du pied de page : familles réellement présentes
  // (sinon le pied de page utilise ses slugs existants par défaut).
  const footerTrades = resolveTrades(resultsOf(categories))
    .slice(0, 6)
    .map(({ label, href }) => ({ label, href }));

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd() }} />
      {/* Sans JavaScript, les blocs animés au défilement restent visibles. */}
      <noscript
        dangerouslySetInnerHTML={{
          __html: '<style>[style*="opacity:0"]{opacity:1!important;transform:none!important}</style>',
        }}
      />
      <LandingDataProvider endpoints={ENDPOINTS} initial={{ stats, categories, featured, reviews, services, plans }}>
        <SiteHeader variant="overlay" />
        <main id="contenu" tabIndex={-1} className="overflow-x-clip bg-white outline-none">
          <Hero />
          <StatsBand />
          <TradesSection />
          <UrgencySection />
          <FeaturedArtisans />
          <LatestServices />
          <HowItWorks />
          <TrustSection />
          <ReviewsSection />
          <BusinessSection />
          <FinalCta />
        </main>
        <SiteFooter trades={footerTrades.length ? footerTrades : undefined} />
      </LandingDataProvider>
    </>
  );
}
