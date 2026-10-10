import type { Metadata } from "next";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";
import VerifyIdClient from "./VerifyIdClient";

export const metadata: Metadata = {
  title: "Vérifier un professionnel Tratra",
  description: "Confirmez en direct qu'un professionnel est bien vérifié par Tratra grâce à son QR Tratra ID.",
  robots: { index: false, follow: false },
};

export default function VerifyIdPage({ params }: { params: { code: string } }) {
  return (
    <>
      <SiteHeader variant="solid" />
      <main id="contenu" tabIndex={-1} className="min-h-screen bg-canvas py-8 outline-none sm:py-12">
        <div className="mx-auto w-full max-w-xl px-4 sm:px-6">
          <VerifyIdClient code={params.code} />
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
