import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ArrowRight } from "lucide-react";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";
import { ButtonLink } from "@/components/ds";
import { PassportReviews } from "@/components/trust/PassportReviews";
import { PassportView } from "@/components/trust/PassportView";
import { publicGet } from "@/lib/public";
import type { Passport } from "@/lib/trust";

type Params = { params: { id: string } };

async function load(id: string): Promise<Passport | null> {
  if (!/^\d+$/.test(id)) return null;
  // Jamais en cache : un badge retiré (suspension, KYC rejeté) ne doit pas rester affiché.
  return publicGet<Passport>(`/handymen/${id}/trust/`, { revalidate: 0 });
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const passport = await load(params.id);
  const title = passport ? `Passeport professionnel de ${passport.display_name}` : "Passeport professionnel";
  return {
    title,
    description: "Identité vérifiée, badges, score de confiance expliqué, compétences et avis réels : le passeport professionnel Tratra.",
    alternates: { canonical: `/artisans/${params.id}` },
  };
}

export default async function ArtisanPassportPage({ params }: Params) {
  const passport = await load(params.id);
  if (!passport) notFound();
  return (
    <>
      <SiteHeader variant="solid" />
      <main id="contenu" tabIndex={-1} className="min-h-screen bg-canvas py-8 outline-none sm:py-12">
        <div className="mx-auto w-full max-w-7xl px-4 sm:px-6">
          <PassportView
            passport={passport}
            actions={
              <ButtonLink
                href={`/search?handyman=${passport.user_id}`}
                size="lg"
                rightIcon={<ArrowRight aria-hidden className="h-4 w-4" />}
              >
                Voir ses prestations
              </ButtonLink>
            }
          >
            <PassportReviews profileId={passport.profile_id} />
          </PassportView>
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
