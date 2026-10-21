"use client";
import { useRouter } from "next/navigation";
import { GuidedIdentity } from "@/components/kyc/GuidedIdentity";
import { useDashboard } from "@/lib/dashboard";
import { Card, PageHeader } from "@/components/ds";

/** « Vérifier mon identité » : la vérification guidée (même parcours et mêmes API que l'application), hors inscription accompagnée. */
export default function IdentityPage() {
  const router = useRouter();
  const { reload } = useDashboard();
  return (
    <>
      <PageHeader
        eyebrow="Profil professionnel"
        title="Vérifier mon identité"
        description="Carte nationale d’identité ou passeport : photos guidées, informations à confirmer, puis vérification par l’équipe Tratra."
      />
      <Card className="mx-auto max-w-2xl" padding="lg">
        <GuidedIdentity
          onFinished={() => {
            void reload();
            router.push("/dashboard");
          }}
        />
      </Card>
    </>
  );
}
