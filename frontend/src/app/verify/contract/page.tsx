import type { Metadata } from "next";
import { Card } from "@/components/ds";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";
import { PdfCheck } from "./ContractVerifyResult";

export const metadata: Metadata = {
  title: "Vérifier un contrat Tratra",
  description: "Déposez le PDF d'un contrat Tratra pour vérifier qu'il n'a pas été modifié.",
  robots: { index: false, follow: false },
};

export default function VerifyContractFilePage() {
  return (
    <>
      <SiteHeader variant="solid" />
      <main id="contenu" tabIndex={-1} className="min-h-screen bg-canvas py-8 outline-none sm:py-12">
        <div className="mx-auto w-full max-w-xl space-y-4 px-4 sm:px-6">
          <h1 className="font-display text-2xl font-bold text-ink">Vérifier un contrat</h1>
          <p className="text-sm text-inkSoft">
            Scannez le QR code du document, ou déposez ici le PDF reçu : Tratra vérifie qu’il correspond exactement à un document qu’elle a
            émis et scellé.
          </p>
          <Card padding="lg">
            <PdfCheck />
          </Card>
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
