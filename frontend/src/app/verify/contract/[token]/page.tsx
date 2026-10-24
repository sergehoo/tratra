import type { Metadata } from "next";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";
import ContractTokenClient from "./ContractTokenClient";

export const metadata: Metadata = {
  title: "Vérifier un contrat Tratra",
  description: "Vérifiez l'authenticité, l'état et l'intégrité d'un contrat émis par Tratra grâce à son QR code.",
  robots: { index: false, follow: false },
};

export default function VerifyContractPage({ params }: { params: { token: string } }) {
  return (
    <>
      <SiteHeader variant="solid" />
      <main id="contenu" tabIndex={-1} className="min-h-screen bg-canvas py-8 outline-none sm:py-12">
        <div className="mx-auto w-full max-w-xl px-4 sm:px-6">
          <ContractTokenClient token={params.token} />
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
