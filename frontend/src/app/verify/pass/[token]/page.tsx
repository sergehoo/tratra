import type { Metadata } from "next";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";
import { RoleGuard } from "@/components/RoleGuard";
import PassClient from "./PassClient";

export const metadata: Metadata = {
  title: "Vérifier l'artisan de ma réservation",
  robots: { index: false, follow: false },
};

export default function PassPage({ params }: { params: { token: string } }) {
  return (
    <>
      <SiteHeader variant="solid" />
      <main id="contenu" tabIndex={-1} className="min-h-screen bg-canvas py-8 outline-none sm:py-12">
        <div className="mx-auto w-full max-w-xl px-4 sm:px-6">
          {/* Connexion exigée : seul le client de la réservation peut consommer ce QR. */}
          <RoleGuard>
            <PassClient token={params.token} />
          </RoleGuard>
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
