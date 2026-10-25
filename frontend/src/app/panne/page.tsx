import type { Metadata } from "next";
import { Suspense } from "react";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";
import { CONTAINER } from "@/components/ds/layout";
import PanneClient from "./PanneClient";

const TITLE = "J’ai une panne";
const DESCRIPTION = "Décrivez votre problème avec vos mots (« mon frigo ne refroidit plus », « écran cassé ») : Tratra trouve le bon métier et les artisans près de chez vous.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/panne" },
  openGraph: { type: "website", locale: "fr_FR", siteName: "Tratra", url: "/panne", title: `${TITLE} · Tratra`, description: DESCRIPTION },
};

export default function PannePage() {
  return (
    <>
      <SiteHeader variant="solid" />
      <main id="contenu" tabIndex={-1} className="min-h-screen bg-canvas outline-none">
        <div className={`${CONTAINER} py-10 sm:py-14`}>
          <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-primaryDark">Dépannage</p>
          <h1 className="mt-2 font-display text-3xl font-extrabold tracking-tight text-ink sm:text-4xl">{TITLE}</h1>
          <p className="mt-3 max-w-2xl text-base leading-relaxed text-ash">{DESCRIPTION}</p>
          <Suspense fallback={null}>
            <PanneClient />
          </Suspense>
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
