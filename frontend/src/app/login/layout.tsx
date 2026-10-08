import type { Metadata } from "next";
import type { ReactNode } from "react";

// La page est un composant client : ses métadonnées sont déclarées ici, sinon
// elle reprendrait le titre, la description et l'og:url de l'accueil.
const TITLE = "Connexion";
const DESCRIPTION =
  "Connectez-vous à votre espace Tratra pour gérer vos réservations, vos missions et votre profil.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/login" },
  // Page utilitaire : hors index, mais ses liens restent suivis.
  robots: { index: false, follow: true },
  openGraph: {
    type: "website",
    locale: "fr_FR",
    siteName: "Tratra",
    url: "/login",
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

export default function LoginLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
