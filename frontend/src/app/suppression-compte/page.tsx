import type { Metadata } from "next";
import Link from "next/link";
import { LegalPage } from "@/components/legal/LegalPage";

export const metadata: Metadata = {
  title: "Suppression de compte",
  description: "Comment supprimer votre compte Tratra et vos données, ce qui est effacé et ce qui est conservé.",
  alternates: { canonical: "/suppression-compte" },
};

export default function AccountDeletionPage() {
  return (
    <LegalPage
      eyebrow="Informations légales"
      title="Supprimer mon compte Tratra"
      updated="Version du 14 octobre 2026"
      intro="Vous pouvez supprimer votre compte et vos données à tout moment, vous-même, sans contacter personne. La suppression est immédiate et définitive."
      sections={[
        {
          title: "Dans l’application mobile",
          body: (
            <ol className="list-decimal space-y-1 pl-5">
              <li>Ouvrez Tratra et connectez-vous.</li>
              <li>Allez dans <strong>Plus → Mon compte</strong>.</li>
              <li>Touchez <strong>Supprimer mon compte</strong>, saisissez votre mot de passe et tapez « SUPPRIMER » pour confirmer.</li>
            </ol>
          ),
        },
        {
          title: "Sur le site",
          body: (
            <p>
              <Link className="font-semibold text-primaryDark underline" href="/login?next=/dashboard/profile%23suppression">Connectez-vous</Link>, ouvrez{" "}
              <strong>Mon profil</strong>, puis <strong>Supprimer mon compte</strong> en bas de page.
            </p>
          ),
        },
        {
          title: "Ce qui est supprimé",
          body: (
            <ul className="list-disc space-y-1 pl-5">
              <li>Votre nom, numéro de téléphone, adresse e-mail et photo de profil ;</li>
              <li>vos adresses enregistrées, favoris, blocages et préférences de notification ;</li>
              <li>vos messages, vos statuts et leurs médias ;</li>
              <li>pour les artisans : pièces d’identité, justificatifs, images de vérification faciale, profil professionnel et badge Tratra ID (vos services sont retirés du catalogue) ;</li>
              <li>vos appareils enregistrés pour les notifications et toutes vos sessions : vous êtes déconnecté partout.</li>
            </ul>
          ),
        },
        {
          title: "Ce qui est conservé",
          body: (
            <p>
              L’historique des réservations, des paiements, des retraits, des avis et des litiges est conservé <strong>sans lien avec votre identité</strong>{" "}
              (le compte devient « Compte supprimé »), car la loi nous l’impose et pour protéger les autres membres. Les messages que d’autres membres
              vous ont envoyés restent chez eux.
            </p>
          ),
        },
        {
          title: "Quand la suppression est refusée",
          body: (
            <p>
              Pour protéger les personnes avec qui vous êtes engagé, la suppression est refusée tant qu’une réservation ou une mission est en cours,
              qu’un litige ouvert vous concerne, que des gains restent à retirer, qu’un abonnement ou un contrat est en vigueur ou que vous êtes
              propriétaire d’une organisation Tratra Business. L’application et le site vous indiquent précisément quoi régler.
            </p>
          ),
        },
        {
          title: "Vous ne pouvez plus vous connecter ?",
          body: (
            <p>
              Écrivez à <a className="font-semibold text-primaryDark underline" href="mailto:support@tratra.net?subject=Suppression%20de%20mon%20compte">support@tratra.net</a>{" "}
              depuis l’adresse e-mail de votre compte, ou en indiquant le numéro de téléphone du compte : nous vérifions votre identité puis
              supprimons le compte. Plus d’informations dans la{" "}
              <Link className="font-semibold text-primaryDark underline" href="/confidentialite">politique de confidentialité</Link>.
            </p>
          ),
        },
      ]}
    />
  );
}
