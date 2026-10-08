import type { Metadata, Viewport } from "next";
import { Montserrat, Poppins } from "next/font/google";
import "./globals.css";
import Providers from "@/components/Providers";
import ServiceWorkerRegister from "@/components/ServiceWorkerRegister";
import { ESCROW_ENABLED, SHARE } from "@/lib/config";

// Typographies de la marque Tratra (auto-hébergées par next/font : aucune
// requête tierce au runtime, compatible CSP font-src 'self').
const display = Montserrat({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  variable: "--font-display",
  display: "swap",
});
const body = Poppins({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-body",
  display: "swap",
});

const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "https://tratra.net").replace(/\/+$/, "");

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  // Promesse de paiement fidèle à ce que la plateforme permet (cf. ESCROW_ENABLED).
  title: {
    default: ESCROW_ENABLED
      ? "Tratra — Artisans vérifiés à domicile, réservation et paiement sécurisés"
      : "Tratra — Artisans vérifiés à domicile, réservation en quelques minutes",
    template: "%s · Tratra",
  },
  description: `Plombiers, électriciens, climaticiens, serruriers, peintres, ménage, jardinage… Trouvez un artisan vérifié près de chez vous, réservez en quelques minutes et ${
    ESCROW_ENABLED ? "payez en toute sécurité" : "payez à la fin de l’intervention"
  }.`,
  applicationName: "Tratra",
  keywords: [
    "artisan", "plombier", "électricien", "climatisation", "serrurier", "peintre", "ménage",
    "jardinage", "dépannage", "bricolage", "déménagement", "services à domicile", "Abidjan",
  ],
  // Pas d'og:url global : une page sans Open Graph propre ne doit pas se
  // déclarer comme l'accueil (l'accueil redéclare son bloc avec url "/").
  openGraph: {
    type: "website",
    locale: "fr_FR",
    siteName: "Tratra",
    title: SHARE.title,
    description: SHARE.description,
    images: [SHARE.image],
  },
  twitter: {
    card: "summary_large_image",
    title: SHARE.title,
    description: SHARE.description,
    images: [SHARE.image.url],
  },
  // PWA iOS : lancement plein écran depuis l'écran d'accueil (icône : src/app/apple-icon.png).
  appleWebApp: { capable: true, title: "Tratra", statusBarStyle: "default" },
  // Équivalent standard de apple-mobile-web-app-capable (sinon avertissement
  // « deprecated » de Chrome sur chaque page).
  other: { "mobile-web-app-capable": "yes" },
  // Pas de canonical global : chaque page publique déclare le sien (sinon
  // /login, /register… se déclareraient copies de l'accueil).
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  themeColor: "#2e8b57",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" className={`${display.variable} ${body.variable}`}>
      <body className="font-sans text-ink antialiased">
        <Providers>{children}</Providers>
        <ServiceWorkerRegister />
      </body>
    </html>
  );
}
