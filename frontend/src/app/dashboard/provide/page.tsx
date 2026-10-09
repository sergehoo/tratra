"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { BadgeCheck, Camera, FileCheck2, Hammer, ShieldCheck, UserRoundCheck } from "lucide-react";
import { apiErrorMessage, post } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard";
import { Alert, Button, Card, CardHeader, PageHeader, Skeleton } from "@/components/ds";

const STEPS = [
  { icon: UserRoundCheck, title: "Créez votre profil professionnel", text: "Un clic, avec votre compte actuel : aucune nouvelle inscription." },
  { icon: Camera, title: "Complétez-le", text: "Présentation, spécialités, expérience, zone d’intervention et photo." },
  { icon: FileCheck2, title: "Faites vérifier votre identité", text: "Déposez votre pièce d’identité : l’équipe Tratra la contrôle." },
  { icon: ShieldCheck, title: "Validation par l’équipe Tratra", text: "Dernière étape avant la publication." },
  { icon: Hammer, title: "Publiez vos services et recevez des missions", text: "Disponible uniquement une fois votre dossier validé." },
];

export default function ProvidePage() {
  const { data, loading, error, reload } = useDashboard();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const hasProfile = data?.capabilities.provider === true;

  // Profil existant : on ouvre sa gestion (jamais de doublon).
  useEffect(() => {
    if (hasProfile) router.replace("/dashboard/provider");
  }, [hasProfile, router]);

  async function create() {
    setBusy(true);
    setFailure("");
    try {
      await post("/me/handyman-profile/");
      await reload();
      router.push("/dashboard/profile");
    } catch (e) {
      setFailure(apiErrorMessage(e, "Le profil n’a pas pu être créé. Réessayez dans un instant."));
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Prestataire"
        title="Proposer un service"
        description="Gagnez des clients avec votre savoir-faire : votre profil professionnel est rattaché à votre compte Tratra."
      />
      {loading || hasProfile ? (
        <Skeleton className="h-72 !rounded-card" />
      ) : error ? (
        <Alert tone="danger" title="Impossible de vérifier votre compte">{error}</Alert>
      ) : (
        <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-5">
          <Card className="lg:col-span-3">
            <CardHeader title="Comment ça marche" description="Cinq étapes, dans l’ordre." icon={<BadgeCheck className="h-5 w-5" />} />
            <ol className="space-y-4">
              {STEPS.map((s, i) => (
                <li key={s.title} className="flex items-start gap-3.5">
                  <span aria-hidden className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-primarySoft text-primary">
                    <s.icon className="h-5 w-5" />
                  </span>
                  <div>
                    <p className="text-sm font-bold text-ink">
                      <span className="mr-2 text-ash">{i + 1}.</span>
                      {s.title}
                    </p>
                    <p className="mt-0.5 text-sm text-ash">{s.text}</p>
                  </div>
                </li>
              ))}
            </ol>
          </Card>
          <Card variant="soft" className="lg:col-span-2">
            <h2 className="font-display text-lg font-extrabold text-ink">Prêt à commencer ?</h2>
            <p className="mt-2 text-sm leading-relaxed text-inkSoft">
              Votre compte reste le même : vous pouvez continuer à réserver des artisans comme avant, et gérer vos prestations
              depuis le même espace.
            </p>
            {failure ? <Alert tone="danger" className="mt-4">{failure}</Alert> : null}
            <Button size="lg" block className="mt-5" loading={busy} onClick={() => void create()}>
              Créer mon profil professionnel
            </Button>
          </Card>
        </div>
      )}
    </>
  );
}
