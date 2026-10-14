import type { Metadata } from "next";
import Link from "next/link";
import { LegalPage } from "@/components/legal/LegalPage";

export const metadata: Metadata = {
  title: "Politique de confidentialité",
  description: "Les données personnelles que Tratra collecte, pourquoi, qui les reçoit, combien de temps elles sont conservées et comment les supprimer.",
  alternates: { canonical: "/confidentialite" },
};

const Li = ({ children }: { children: React.ReactNode }) => <li>{children}</li>;

export default function PrivacyPage() {
  return (
    <LegalPage
      eyebrow="Informations légales"
      title="Politique de confidentialité"
      updated="Version du 14 octobre 2026"
      intro="Cette page décrit les données que Tratra traite lorsque vous utilisez l’application mobile et le site : lesquelles, pourquoi, qui les reçoit, combien de temps elles sont conservées et comment les faire supprimer. Tratra n’affiche aucune publicité et ne vend aucune donnée personnelle."
      sections={[
        {
          title: "Données collectées",
          body: (
            <ul className="list-disc space-y-1 pl-5">
              <Li><strong>Identité et compte</strong> : prénom, nom, numéro de téléphone, adresse e-mail (facultative), photo de profil (facultative), mot de passe (conservé sous forme chiffrée irréversible).</Li>
              <Li><strong>Réservations et paiements</strong> : réservations, missions, adresses d’intervention, avis, litiges, paiements, retraits.</Li>
              <Li><strong>Localisation</strong> : adresses que vous enregistrez ; avec votre accord, la position de votre appareil <em>au premier plan uniquement</em> pour trouver des artisans proches ; pendant une mission, avec le consentement des deux personnes concernées, le suivi en direct de l’artisan en route.</Li>
              <Li><strong>Messages et statuts</strong> : messages échangés dans l’application (texte, photos, vidéos, documents PDF) et statuts éphémères (texte, photo ou vidéo) que vous publiez.</Li>
              <Li><strong>Artisans — vérification d’identité</strong> : profil professionnel, pièces d’identité et justificatifs (conservés dans un espace de stockage privé, jamais publics) et, avec votre consentement explicite, vérification faciale (voir ci-dessous).</Li>
              <Li><strong>Appareil et technique</strong> : identifiant technique de notification (jeton Firebase Cloud Messaging), adresse IP et journaux de sécurité, rapports d’erreurs.</Li>
              <Li><strong>Appareil photo</strong> : l’application n’y accède que lorsque vous prenez une photo ou une vidéo, ou pendant la vérification faciale. Aucun accès au micro ni à votre galerie complète.</Li>
            </ul>
          ),
        },
        {
          title: "Pourquoi ces données",
          body: (
            <p>
              Créer et sécuriser votre compte, confirmer votre numéro par SMS, mettre en relation clients et artisans, gérer réservations, messages,
              statuts, suivi des interventions et paiements, vérifier l’identité des artisans et prévenir la fraude, vous envoyer des notifications utiles
              (réservations, messages, vérification) et respecter nos obligations légales. Les annonces promotionnelles ne sont envoyées qu’avec votre
              consentement, que vous pouvez retirer à tout moment.
            </p>
          ),
        },
        {
          title: "Vérification faciale (artisans)",
          body: (
            <>
              <p>
                Elle est facultative pour la création du compte et jamais déclenchée sans votre consentement explicite, que vous pouvez retirer à tout
                moment depuis l’écran de vérification. Elle consiste à capturer quelques images de votre visage, avec des gestes guidés, pour vérifier
                que la personne est bien présente et correspond à sa pièce d’identité.
              </p>
              <ul className="list-disc space-y-1 pl-5">
                <Li>Les images sont chiffrées, stockées dans un espace privé et accessibles uniquement aux personnes habilitées de l’équipe Tratra.</Li>
                <Li>Elles ne sont <strong>jamais</strong> envoyées à un service d’intelligence artificielle générative. Elles peuvent être transmises à un prestataire spécialisé de vérification de présence, uniquement lorsqu’il est configuré ; sinon un membre de l’équipe examine votre dossier.</Li>
                <Li>Aucune décision défavorable n’est prise par une machine seule : un résultat défavorable ou incertain est examiné par un humain et vous pouvez demander un nouvel essai ou une vérification sans biométrie.</Li>
                <Li>Conservation : 30 jours au plus après la vérification, puis suppression automatique ; suppression immédiate si vous retirez votre consentement.</Li>
                <Li>Aucune base générale de reconnaissance faciale des utilisateurs n’est constituée et deux comptes ne sont jamais rapprochés sur la seule ressemblance de visage.</Li>
              </ul>
            </>
          ),
        },
        {
          title: "Statuts et messages",
          body: (
            <p>
              Un statut est visible 24 heures par vos contacts Tratra (personnes avec qui vous avez une réservation, un contrat ou une conversation) ou,
              si vous le choisissez, par tous les membres ; vous pouvez exclure des contacts, supprimer un statut à tout moment et vous seul voyez la
              liste de ceux qui l’ont consulté. Les médias d’un statut expiré sont supprimés dans les 24 heures qui suivent, les enregistrements associés
              au bout de 30 jours. Vos messages sont conservés tant que votre compte existe. Vous pouvez bloquer un membre et signaler un message ou
              un statut à l’équipe Tratra.
            </p>
          ),
        },
        {
          title: "Qui reçoit vos données",
          body: (
            <>
              <p>
                Vos données sont traitées par Tratra et par des prestataires techniques qui n’agissent que sur nos instructions et pour les besoins
                du service :
              </p>
              <ul className="list-disc space-y-1 pl-5">
                <Li>hébergement et stockage des données et des fichiers ;</Li>
                <Li>envoi de SMS de vérification (votre numéro et le message) ;</Li>
                <Li>notifications push (Google Firebase Cloud Messaging : jeton technique de l’appareil et contenu de la notification) ;</Li>
                <Li>cartographie et recherche d’adresses (les requêtes d’adresse sont envoyées par nos serveurs, sans vos identifiants) ;</Li>
                <Li>suivi des erreurs techniques ;</Li>
                <Li>le cas échéant, vérification de présence lors de la vérification faciale (voir plus haut).</Li>
              </ul>
              <p>
                Un artisan affiche publiquement son prénom, l’initiale de son nom, sa commune, sa note et ses services — jamais son numéro, son
                e-mail ni ses documents. Les autorités ne reçoivent des données que sur demande légale.
              </p>
            </>
          ),
        },
        {
          title: "Conservation et sécurité",
          body: (
            <p>
              Les données sont conservées tant que votre compte existe, puis supprimées ou anonymisées, sauf celles que la loi impose de garder
              (réservations, paiements, retraits, avis et litiges : conservés sans lien avec votre identité après la suppression du compte). Les
              positions du suivi en direct sont supprimées au plus tard 24 heures après la fin de la mission. Les échanges avec nos serveurs sont
              chiffrés, les accès sont authentifiés et cloisonnés par compte, et les actions sensibles de l’équipe sont journalisées.
            </p>
          ),
        },
        {
          title: "Vos droits et la suppression de votre compte",
          body: (
            <>
              <p>
                Vous pouvez consulter et corriger vos informations depuis votre profil, retirer vos consentements (position, vérification faciale,
                annonces promotionnelles), demander une copie de vos données, vous opposer à un traitement ou demander sa limitation en écrivant à{" "}
                <a className="font-semibold text-primaryDark underline" href="mailto:support@tratra.net">support@tratra.net</a>.
              </p>
              <p>
                <strong>Supprimer votre compte</strong> : dans l’application (Mon compte → Supprimer mon compte) ou sur le site (Mon profil → Supprimer
                mon compte), ou en suivant les étapes de la page{" "}
                <Link className="font-semibold text-primaryDark underline" href="/suppression-compte">Suppression de compte</Link>. La suppression est
                immédiate et définitive : nom, téléphone, e-mail, photo, adresses, messages, statuts, pièces d’identité et images du visage sont effacés.
              </p>
              <p>
                Si vous estimez que vos droits ne sont pas respectés, vous pouvez saisir l’autorité de protection des données personnelles compétente
                (en Côte d’Ivoire : l’ARTCI).
              </p>
            </>
          ),
        },
        {
          title: "Enfants",
          body: <p>Tratra s’adresse aux personnes de 18 ans et plus. Le service n’est pas destiné aux enfants et nous ne collectons pas sciemment leurs données.</p>,
        },
        {
          title: "Modifications et contact",
          body: (
            <p>
              Nous mettons cette page à jour lorsque nos traitements évoluent ; la date en haut de page fait foi. Une question ?{" "}
              <a className="font-semibold text-primaryDark underline" href="mailto:support@tratra.net">support@tratra.net</a>.
            </p>
          ),
        },
      ]}
    />
  );
}
