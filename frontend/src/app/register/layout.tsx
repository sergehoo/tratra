import type { Metadata } from "next";
import type { ReactNode } from "react";

// La page est un composant client : ses métadonnées sont déclarées ici, sinon
// elle reprendrait le titre, la description et l'og:url de l'accueil.
const TITLE = "Créer un compte";
const DESCRIPTION =
  "Créez votre compte Tratra pour réserver un artisan près de chez vous et suivre vos interventions, ou pour proposer vos services d'artisan.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/register" },
  openGraph: {
    type: "website",
    locale: "fr_FR",
    siteName: "Tratra",
    url: "/register",
    title: `${TITLE} · Tratra`,
    description: DESCRIPTION,
    // openGraph/twitter d'un segment remplacent ceux du layout racine :
    // l'image de partage doit être redéclarée ici.
    images: [{ url: "/og-image.jpg", width: 1200, height: 630, alt: "Tratra — Artisans vérifiés à domicile" }],
  },
  twitter: {
    card: "summary_large_image",
    title: `${TITLE} · Tratra`,
    description: DESCRIPTION,
    images: ["/og-image.jpg"],
  },
};

export default function RegisterLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
