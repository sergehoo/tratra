import type { Metadata } from "next";
import { LegalPage } from "@/components/legal/LegalPage";

export const metadata: Metadata = {
  title: "Conditions d’utilisation",
  description: "Les règles d’utilisation de Tratra pour les clients et les artisans.",
  alternates: { canonical: "/conditions" },
};

export default function ConditionsPage() {
  return (
    <LegalPage
      eyebrow="Informations légales"
      title="Conditions d’utilisation"
      updated="Version provisoire du 9 octobre 2026"
      intro="Tratra met en relation des clients et des artisans. En créant un compte, vous acceptez les règles ci-dessous."
      sections={[
        {
          title: "Un compte unique",
          body: (
            <p>
              Un seul compte, identifié par votre numéro de téléphone, vous permet de réserver des artisans, de proposer vos propres services et,
              si vous le souhaitez, de créer un espace entreprise. Aucun second compte n’est nécessaire.
            </p>
          ),
        },
        {
          title: "Votre numéro de téléphone",
          body: (
            <p>
              Votre numéro est confirmé par un code reçu par SMS. Tant que ce code n’est pas validé, votre numéro n’est pas considéré comme vérifié.
              Vous vous engagez à fournir des informations exactes et à garder votre mot de passe confidentiel.
            </p>
          ),
        },
        {
          title: "Artisans",
          body: (
            <p>
              Vos services ne sont visibles des clients et vous ne recevez des missions qu’après vérification de votre identité (KYC), complétude de
              votre profil et validation par l’équipe Tratra. Tratra ne garantit aucun volume de missions.
            </p>
          ),
        },
        {
          title: "Réservations et paiement",
          body: (
            <p>
              Une réservation engage le client et l’artisan selon les informations affichées au moment de la demande (prestation, date, adresse,
              tarif). Les modalités de paiement applicables sont celles affichées lors de la réservation.
            </p>
          ),
        },
        {
          title: "Comportements interdits",
          body: (
            <p>
              Il est interdit de fournir de fausses informations, d’usurper une identité, de détourner la plateforme, de publier des contenus illicites
              ou de contourner les mesures de sécurité. Tratra peut suspendre un compte en cas de manquement.
            </p>
          ),
        },
        {
          title: "Évolution des conditions",
          body: <p>Ces conditions peuvent évoluer ; la date de la version en vigueur figure en tête de cette page.</p>,
        },
      ]}
    />
  );
}
