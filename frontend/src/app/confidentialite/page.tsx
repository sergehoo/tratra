import type { Metadata } from "next";
import { LegalPage } from "@/components/legal/LegalPage";

export const metadata: Metadata = {
  title: "Politique de confidentialité",
  description: "Les données personnelles que Tratra collecte, pourquoi, et comment elles sont protégées.",
  alternates: { canonical: "/confidentialite" },
};

export default function PrivacyPage() {
  return (
    <LegalPage
      eyebrow="Informations légales"
      title="Politique de confidentialité"
      updated="Version provisoire du 9 octobre 2026"
      intro="Cette page décrit les données que Tratra traite pour faire fonctionner votre compte, vos réservations et vos missions."
      sections={[
        {
          title: "Données collectées",
          body: (
            <ul className="list-disc space-y-1 pl-5">
              <li>Identité : prénom, nom ; numéro de téléphone ; adresse e-mail (facultative).</li>
              <li>Utilisation : réservations, messages, avis, notifications, paiements et retraits.</li>
              <li>Localisation : adresse d’intervention et, avec votre accord, position pour trouver des artisans proches.</li>
              <li>Artisans : profil professionnel et pièce d’identité (KYC), conservée dans un espace de stockage privé.</li>
            </ul>
          ),
        },
        {
          title: "Pourquoi ces données",
          body: (
            <p>
              Créer et sécuriser votre compte, confirmer votre numéro par SMS, mettre en relation clients et artisans, suivre les interventions et
              les paiements, vérifier l’identité des artisans et prévenir la fraude.
            </p>
          ),
        },
        {
          title: "SMS de vérification",
          body: (
            <p>
              Le code de confirmation est envoyé par un prestataire d’envoi de SMS. Le numéro et le message lui sont transmis uniquement pour cet
              envoi. Le code n’est jamais affiché ni conservé en clair dans les journaux de l’application.
            </p>
          ),
        },
        {
          title: "Ce qui est visible des autres",
          body: (
            <p>
              Un artisan affiche publiquement son prénom, l’initiale de son nom, sa commune, sa note et ses services — jamais son numéro, son
              e-mail ni ses documents.
            </p>
          ),
        },
        {
          title: "Conservation et sécurité",
          body: (
            <p>
              Les données sont conservées tant que votre compte existe et pour les durées imposées par la loi (réservations, paiements). Les accès
              sont protégés par authentification et cloisonnés par compte.
            </p>
          ),
        },
        {
          title: "Vos droits",
          body: (
            <p>
              Vous pouvez consulter et corriger vos informations depuis votre profil, et demander l’effacement de votre compte auprès du support
              Tratra.
            </p>
          ),
        },
      ]}
    />
  );
}
