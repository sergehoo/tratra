import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { BadgeCheck, FileSignature, IdCard, Lock, ScanFace, ShieldCheck, Smartphone, UserRound, Wallet } from "lucide-react";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";
import { CONTAINER } from "@/components/ds/layout";
import { ESCROW_ENABLED } from "@/lib/config";
import { LEGAL_MENTIONS, SUPPORT_EMAIL, TERMS_PATH, TERMS_UPDATED_LABEL, TERMS_UPDATED_ON, TERMS_VERSION } from "@/lib/legal";

/**
 * Conditions générales d'utilisation — page publique (sans connexion), rendue en HTML statique.
 *
 * Rédigées à partir des règles RÉELLEMENT appliquées par le code (onboarding progressif, Flash, contrats, espèces, avis, litiges,
 * suppression). Aucun montant de commission, délai configurable, coordonnée d'éditeur ni engagement juridique n'est inventé : les
 * valeurs réglables au Back-Office sont désignées comme « affichées dans l'application ». Les mentions restant à valider par un
 * juriste sont listées dans docs/cgu-mentions-a-valider.md. Toute modification du fond = nouvelle version (src/lib/legal.ts).
 */

const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "https://tratra.net").replace(/\/+$/, "");
const TITLE = "Conditions d’utilisation";
const DESCRIPTION =
  "Conditions générales d’utilisation de Tratra : compte unique, publication et vérification des professionnels, réservations, Tratra Flash, contrats, paiements, annulations, litiges, avis, données personnelles et suppression du compte.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: TERMS_PATH },
  robots: { index: true, follow: true },
  openGraph: {
    type: "article",
    locale: "fr_FR",
    url: TERMS_PATH,
    siteName: "Tratra",
    title: `${TITLE} · Tratra`,
    description: DESCRIPTION,
    modifiedTime: `${TERMS_UPDATED_ON}T00:00:00Z`,
  },
};

const A = ({ href, children }: { href: string; children: ReactNode }) =>
  href.startsWith("/") ? (
    <Link href={href} className="font-semibold text-primaryDark underline underline-offset-2 hover:text-primaryDeep">
      {children}
    </Link>
  ) : (
    <a href={href} className="font-semibold text-primaryDark underline underline-offset-2 hover:text-primaryDeep">
      {children}
    </a>
  );

const Mail = () => <A href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</A>;

const List = ({ children }: { children: ReactNode }) => <ul className="list-disc space-y-1.5 pl-5 marker:text-primary">{children}</ul>;

interface Section {
  id: string;
  title: string;
  body: ReactNode;
}

const LEVELS = [
  {
    icon: UserRound,
    name: "Non vérifié",
    when: "Téléphone confirmé, commune et au moins un métier renseignés.",
    gives: "Profil et services visibles avec la mention « Non vérifié ». Aucune commande.",
    tone: "border-line bg-surface",
    chip: "bg-fog text-inkSoft",
  },
  {
    icon: IdCard,
    name: "Identité vérifiée",
    when: "Pièce d’identité examinée et approuvée par l’équipe Tratra.",
    gives: "Réception des commandes (sauf métiers qui exigent aussi la vérification faciale).",
    tone: "border-primary/30 bg-primarySoft/60",
    chip: "bg-primary text-white",
  },
  {
    icon: ScanFace,
    name: "Vérifié",
    when: "Vérification faciale validée, avec votre consentement explicite.",
    gives: "Badge « Vérifié » affiché sur le profil.",
    tone: "border-accent/50 bg-accentSoft/60",
    chip: "bg-accent text-night",
  },
];

const SECTIONS: Section[] = [
  {
    id: "objet",
    title: "Objet et acceptation",
    body: (
      <>
        <p>
          Tratra est un service de mise en relation, accessible sur le site tratra.net et dans l’application mobile, entre des personnes et des
          entreprises qui ont besoin d’un service (les « clients ») et des artisans et prestataires qui le proposent (les « professionnels »).
          Tratra fournit les outils de recherche, de réservation, de messagerie, de suivi, de contrat et de vérification. La prestation elle-même
          est réalisée par le professionnel.
        </p>
        <p>
          Les présentes conditions s’appliquent à toute utilisation de Tratra. Pour créer un compte, vous cochez la case « J’accepte les
          Conditions d’utilisation » : cette case n’est jamais précochée, et la version acceptée ainsi que la date de votre acceptation sont
          enregistrées par nos serveurs. Tratra s’adresse aux personnes âgées de 18 ans et plus.
        </p>
      </>
    ),
  },
  {
    id: "compte",
    title: "Un compte unique, lié à votre téléphone",
    body: (
      <>
        <p>
          Un seul compte, identifié par votre numéro de téléphone, vous permet à la fois de réserver des professionnels, de proposer vos propres
          services et, si vous le souhaitez, d’ouvrir un espace entreprise. Le compte est personnel : vous ne pouvez ni le prêter, ni le céder, ni
          en ouvrir un second.
        </p>
        <List>
          <li>Votre numéro est confirmé par un code reçu par SMS. Tant que ce code n’est pas validé, votre numéro n’est pas considéré comme vérifié et les actions sensibles (réserver, écrire, proposer une offre, payer) restent bloquées.</li>
          <li>Vous fournissez des informations exactes et les tenez à jour ; changer de numéro demande une nouvelle confirmation par SMS.</li>
          <li>Votre mot de passe est confidentiel. Signalez sans attendre toute utilisation que vous n’avez pas autorisée à <Mail />.</li>
        </List>
      </>
    ),
  },
  {
    id: "professionnels",
    title: "Professionnels : publication et niveaux de vérification",
    body: (
      <>
        <p>
          Vous pouvez publier votre profil et vos services avant toute vérification d’identité. Trois niveaux, distincts et affichés sans
          ambiguïté, déterminent ce que vous pouvez faire :
        </p>
        <ol className="grid gap-3 sm:grid-cols-3" aria-label="Niveaux de vérification des professionnels">
          {LEVELS.map((l, i) => (
            <li key={l.name} className={`rounded-card border p-4 ${l.tone}`}>
              <div className="flex items-center gap-2">
                <span className={`inline-flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ${l.chip}`} aria-hidden>
                  {i + 1}
                </span>
                <l.icon aria-hidden className="h-4 w-4 text-primaryDark" />
                <span className="font-display text-sm font-bold text-ink">{l.name}</span>
              </div>
              <p className="mt-2 text-[13px] leading-snug text-inkSoft">
                <span className="font-semibold text-ink">Condition : </span>
                {l.when}
              </p>
              <p className="mt-1 text-[13px] leading-snug text-inkSoft">
                <span className="font-semibold text-ink">Effet : </span>
                {l.gives}
              </p>
            </li>
          ))}
        </ol>
        <List>
          <li>
            <strong>Non vérifié</strong> signifie que Tratra n’a pas encore contrôlé votre identité. Cette mention reste visible tant que la
            pièce d’identité n’est pas approuvée. Pendant cette période, le nombre d’annonces actives est limité (la limite est indiquée dans
            votre espace) et vos annonces ne doivent contenir ni numéro de téléphone ni lien : les clients vous contactent par Tratra.
          </li>
          <li>
            La pièce d’identité est examinée par l’équipe Tratra. Son approbation active les commandes, sauf si un examen complémentaire est
            nécessaire. Certains métiers, signalés dans l’application, exigent aussi la vérification faciale avant toute commande.
          </li>
          <li>
            La vérification faciale n’est jamais déclenchée sans votre consentement explicite, que vous pouvez retirer. Vous pouvez demander à
            la place une vérification par un membre de l’équipe.
          </li>
          <li>
            Ces niveaux attestent uniquement des contrôles d’identité effectués. Ils ne certifient ni la qualité du travail, ni des diplômes,
            ni une assurance. Tratra ne garantit aucun volume de missions.
          </li>
        </List>
      </>
    ),
  },
  {
    id: "clients",
    title: "Clients : réservations et missions",
    body: (
      <>
        <p>
          Seuls les professionnels au niveau « Identité vérifiée » ou « Vérifié » peuvent recevoir une commande. Une réservation précise la
          prestation, la date, l’adresse d’intervention et le tarif affichés au moment de la demande ; elle engage le client et le
          professionnel sur ces éléments.
        </p>
        <List>
          <li>Le professionnel confirme la réservation, démarre puis termine la mission. Le client peut annuler (voir « Annulations »).</li>
          <li>Le client donne des informations exactes sur son besoin et l’accès au lieu d’intervention ; le professionnel respecte les horaires annoncés ou prévient en cas d’empêchement.</li>
          <li>Le suivi en direct du professionnel en route n’est activé qu’avec le consentement des personnes concernées.</li>
        </List>
      </>
    ),
  },
  {
    id: "flash",
    title: "Tratra Flash",
    body: (
      <>
        <p>
          Avec Tratra Flash, le client décrit son besoin (métier, lieu, moment, prix ferme ou demande de devis). Tratra le propose ensuite, par
          vagues successives, aux professionnels disponibles et autorisés à recevoir des commandes, à proximité.
        </p>
        <List>
          <li>Chaque professionnel sollicité dispose d’un délai de réponse, affiché dans l’application. Refuser ou laisser passer une proposition n’est jamais une faute.</li>
          <li>En prix ferme, le premier professionnel qui accepte obtient la mission ; il peut aussi proposer un autre montant, que le client accepte ou refuse dans le délai affiché. Sur devis, le client choisit librement parmi les devis reçus.</li>
          <li>Une demande n’est attribuée qu’une seule fois. L’adresse exacte et le téléphone du client ne sont communiqués qu’au professionnel retenu, après l’attribution.</li>
          <li>Faute de professionnel disponible dans les délais, la demande expire et aucune réservation n’est créée.</li>
        </List>
      </>
    ),
  },
  {
    id: "contrats",
    title: "Engagements récurrents et contrats",
    body: (
      <>
        <p>
          Pour une mission récurrente ou de longue durée, les parties peuvent établir un contrat dans Tratra. Chaque partie accepte la version
          exacte des conditions affichées ; toute modification ultérieure passe par un avenant accepté par l’autre partie, sans effet
          rétroactif. Le document final est scellé électroniquement et peut être vérifié publiquement à partir de sa référence.
        </p>
        <List>
          <li>Les modèles de contrat sont une aide à la rédaction. Les parties restent responsables du respect de leurs obligations légales (droit du travail, déclarations sociales et fiscales) : Tratra ne calcule aucune cotisation ni aucun impôt.</li>
          <li>Tratra ne verse ni n’encaisse la rémunération prévue au contrat : un paiement est déclaré par une partie et ne compte qu’une fois confirmé par l’autre.</li>
          <li>Les éventuels frais de service liés à un contrat, et la partie qui les supporte, sont ceux figurant dans l’application pour ce contrat.</li>
        </List>
      </>
    ),
  },
  {
    id: "paiements",
    title: "Prix, paiements et frais",
    body: (
      <>
        <p>
          Le professionnel fixe ses prix (forfait, tarif horaire ou devis). Les estimations affichées par Tratra sont indicatives tant que le
          professionnel ne les a pas confirmées.
        </p>
        {ESCROW_ENABLED ? (
          <p>
            Lorsque le paiement en ligne est proposé, le montant réglé par le client est conservé jusqu’à la fin de la mission puis versé au
            professionnel, selon les moyens de paiement proposés dans l’application.
          </p>
        ) : (
          <p>
            Le client règle le professionnel à la fin de l’intervention, avec le moyen de paiement indiqué lors de la réservation. Tratra
            n’encaisse pas ce paiement : l’une des parties le déclare dans l’application, l’autre le confirme ou le conteste, et cet
            historique est conservé.
          </p>
        )}
        <p>
          Le montant des éventuels frais de service ou commissions de Tratra, ainsi que le prix des abonnements entreprise, sont précisés dans
          l’application ou dans l’offre concernée.
        </p>
      </>
    ),
  },
  {
    id: "annulations",
    title: "Annulations",
    body: (
      <List>
        <li>Une réservation peut être annulée tant que la mission n’est pas terminée ; une mission terminée ou déjà annulée ne peut plus l’être.</li>
        <li>Lorsqu’une politique d’annulation est en vigueur, une annulation faite trop près de l’heure prévue peut entraîner des frais d’annulation, calculés selon le délai d’annulation gratuite et le pourcentage qu’elle fixe.</li>
        <li>Les annulations répétées ou abusives peuvent conduire aux mesures décrites dans « Sanctions ».</li>
      </List>
    ),
  },
  {
    id: "litiges",
    title: "Réclamations et litiges",
    body: (
      <>
        <p>
          En cas de problème sur une mission, ouvrez un litige depuis la réservation concernée (ou depuis le contrat). Il est examiné par
          l’équipe Tratra, qui peut demander des précisions aux deux parties et vous informe de sa décision. Une déclaration de paiement peut
          aussi être contestée, motif à l’appui.
        </p>
        <p>
          Cette démarche amiable ne vous prive d’aucun recours. Pour toute réclamation sur le service Tratra lui-même, écrivez à <Mail />.
        </p>
      </>
    ),
  },
  {
    id: "avis",
    title: "Avis et réputation",
    body: (
      <List>
        <li>Seul le client d’une mission terminée peut laisser un avis, un seul par réservation. Il peut le corriger pendant 7 jours ; le professionnel peut y répondre publiquement.</li>
        <li>Un avis doit refléter une expérience réelle. Sont interdits : les faux avis, les avis obtenus contre une contrepartie, sous la menace, ou rédigés sur son propre profil.</li>
        <li>Tratra peut masquer un avis contraire à ces règles ; un avis masqué n’est plus publié ni pris en compte dans la note.</li>
        <li>Les badges et scores de confiance sont calculés à partir de l’activité réelle sur Tratra et réévalués régulièrement ; ils ne s’achètent pas.</li>
      </List>
    ),
  },
  {
    id: "contenus",
    title: "Messages, statuts et comportements interdits",
    body: (
      <>
        <p>
          Vous êtes responsable des contenus que vous publiez (profil, annonces, photos, messages, statuts, avis). Vous pouvez bloquer un membre
          et signaler un message, un statut ou un profil à l’équipe Tratra. Il est notamment interdit :
        </p>
        <List>
          <li>de fournir de fausses informations, d’usurper l’identité d’autrui ou de présenter des documents falsifiés ;</li>
          <li>de proposer des services illicites, de publier des contenus haineux, discriminatoires, violents, à caractère sexuel ou portant atteinte aux droits d’autrui ;</li>
          <li>de harceler, menacer ou tromper un autre membre, ou de solliciter des paiements hors des moyens prévus pour contourner les protections de Tratra ;</li>
          <li>de créer plusieurs comptes, notamment pour échapper à une sanction, de manipuler les avis ou les classements ;</li>
          <li>de contourner les mesures de sécurité, d’abuser des envois de codes SMS ou d’accéder au service par des moyens automatisés non autorisés.</li>
        </List>
      </>
    ),
  },
  {
    id: "responsabilites",
    title: "Responsabilités",
    body: (
      <List>
        <li><strong>Le professionnel</strong> réalise la prestation sous sa responsabilité : qualité du travail, respect des règles de son métier, autorisations, assurances et déclarations qui lui incombent.</li>
        <li><strong>Le client</strong> décrit son besoin avec exactitude, permet l’accès au lieu d’intervention dans des conditions sûres et règle le prix convenu.</li>
        <li><strong>Tratra</strong> met en œuvre les moyens raisonnables pour assurer le fonctionnement, la sécurité et la confidentialité du service, contrôle l’identité des professionnels selon les niveaux décrits plus haut et traite les signalements et litiges. Le service peut être interrompu pour maintenance ou en cas d’incident.</li>
      </List>
    ),
  },
  {
    id: "donnees",
    title: "Données personnelles",
    body: (
      <>
        <p>
          Les données nécessaires au service sont traitées comme le décrit la{" "}
          <A href="/confidentialite">politique de confidentialité</A>. En résumé : les pièces d’identité sont conservées dans un espace privé,
          jamais publiées ; les images de la vérification faciale sont chiffrées, supprimées au plus tard 30 jours après la vérification et
          aussitôt si vous retirez votre consentement ; un professionnel n’affiche jamais publiquement son numéro, son e-mail ni ses documents.
          Tratra n’affiche aucune publicité et ne vend aucune donnée personnelle.
        </p>
        <p>Vous pouvez exercer vos droits (accès, rectification, opposition, retrait des consentements) en écrivant à <Mail />.</p>
      </>
    ),
  },
  {
    id: "sanctions",
    title: "Sanctions",
    body: (
      <>
        <p>
          En cas de manquement aux présentes conditions, de fraude ou de risque pour d’autres membres, Tratra peut, selon la gravité : masquer
          une annonce ou un contenu, retirer un badge, suspendre la réception de commandes, suspendre le compte (le profil professionnel n’est
          alors plus publié) ou y mettre fin.
        </p>
        <p>
          Vous pouvez contester une décision vous concernant en écrivant à <Mail /> : elle est alors réexaminée par un membre de l’équipe.
        </p>
      </>
    ),
  },
  {
    id: "suppression",
    title: "Suppression du compte",
    body: (
      <p>
        Vous pouvez supprimer votre compte à tout moment : dans l’application (Mon compte → Supprimer mon compte), sur le site (Mon profil →
        Supprimer mon compte) ou en suivant la page <A href="/suppression-compte">Suppression de compte</A>. Ce qui est encore en cours
        (réservation, litige que vous avez ouvert, contrat, abonnement) doit d’abord être terminé : l’écran de suppression vous l’indique. La suppression est immédiate et définitive ; les informations que la loi impose de garder
        (réservations, paiements, avis, litiges) sont conservées sans lien avec votre identité.
      </p>
    ),
  },
  {
    id: "evolution",
    title: "Évolution des conditions",
    body: (
      <p>
        Ces conditions peuvent évoluer avec le service. Chaque version porte une référence et une date, indiquées en haut de cette page. Une
        nouvelle version vous est présentée dans l’application ou sur le site, et votre acceptation (version et date) n’est enregistrée que si
        vous la donnez vous-même : aucune acceptation n’est jamais enregistrée à votre place.
      </p>
    ),
  },
  {
    id: "editeur",
    title: "Éditeur et contact",
    body: (
      <>
        {LEGAL_MENTIONS.length ? (
          <ul className="space-y-1">
            {LEGAL_MENTIONS.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        ) : (
          <p>
            Le service est édité sous la marque Tratra. Les mentions d’identification de l’éditeur (dénomination, forme, siège, immatriculation)
            seront publiées sur cette page.
          </p>
        )}
        <p>
          Contact : <Mail /> · Site : <A href="/">tratra.net</A>
        </p>
      </>
    ),
  },
];

const ESSENTIALS = [
  { icon: Smartphone, title: "Un compte unique", text: "Votre téléphone, confirmé par SMS, pour réserver et pour proposer vos services." },
  { icon: BadgeCheck, title: "Des niveaux clairs", text: "« Non vérifié », « Identité vérifiée » ou « Vérifié » : jamais de badge sans contrôle." },
  {
    icon: Wallet,
    title: ESCROW_ENABLED ? "Un paiement encadré" : "Paiement après l’intervention",
    text: ESCROW_ENABLED
      ? "Le montant est conservé jusqu’à la fin de la mission, puis versé au professionnel."
      : "Le client règle le professionnel à la fin de l’intervention ; chaque paiement est déclaré puis confirmé.",
  },
  { icon: Lock, title: "Vos données protégées", text: "Pièces privées, consentements révocables, suppression du compte à tout moment." },
];

const TOC_LINK =
  "flex min-h-[36px] items-center gap-2 rounded-control px-2 text-inkSoft transition-colors hover:bg-primarySoft hover:text-primaryDark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary";

function TocList() {
  return (
    <ol className="mt-3 space-y-0.5 text-sm">
      {SECTIONS.map((s, i) => (
        <li key={s.id}>
          <a href={`#${s.id}`} className={TOC_LINK}>
            <span className="w-5 shrink-0 text-xs font-bold text-ash">{i + 1}.</span>
            {s.title}
          </a>
        </li>
      ))}
    </ol>
  );
}

/** Sommaire : repliable sur mobile (fermé, le texte vient d'abord), colonne fixe à partir de lg. Sans JavaScript. */
function TableOfContents() {
  return (
    <>
      <nav aria-label="Sommaire" className="lg:hidden">
        <details className="group rounded-card border border-line bg-surface p-4">
          <summary className="flex min-h-[32px] cursor-pointer list-none items-center justify-between font-display text-sm font-bold uppercase tracking-[0.14em] text-ink">
            Sommaire · {SECTIONS.length} sections
            <span aria-hidden className="text-ash transition-transform group-open:rotate-180">
              ▾
            </span>
          </summary>
          <TocList />
        </details>
      </nav>
      <nav aria-labelledby="sommaire" className="hidden lg:sticky lg:top-24 lg:block lg:self-start">
        <p id="sommaire" className="font-display text-sm font-bold uppercase tracking-[0.14em] text-ink">
          Sommaire
        </p>
        <TocList />
      </nav>
    </>
  );
}

function jsonLd(): string {
  return JSON.stringify({
    "@context": "https://schema.org",
    "@type": "WebPage",
    "@id": `${SITE_URL}${TERMS_PATH}#page`,
    url: `${SITE_URL}${TERMS_PATH}`,
    name: `${TITLE} · Tratra`,
    description: DESCRIPTION,
    inLanguage: "fr",
    dateModified: TERMS_UPDATED_ON,
    version: TERMS_VERSION,
    isPartOf: { "@id": `${SITE_URL}/#website` },
  }).replace(/</g, "\\u003c");
}

export default function TermsOfUsePage() {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd() }} />
      <SiteHeader variant="solid" />
      <main id="contenu" tabIndex={-1} className="bg-canvas outline-none">
        <header className="relative overflow-hidden bg-night text-white">
          <div
            aria-hidden
            className="pointer-events-none absolute -top-32 right-0 h-72 w-[36rem] rounded-full bg-primary/25 blur-3xl"
          />
          <div className={`relative py-12 sm:py-16 ${CONTAINER}`}>
            <p className="inline-flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-accent">
              <ShieldCheck aria-hidden className="h-4 w-4" /> Informations légales
            </p>
            <h1 className="mt-3 font-display text-3xl font-extrabold leading-tight sm:text-5xl">{TITLE}</h1>
            <p className="mt-4 max-w-2xl text-base leading-relaxed text-white/80 sm:text-lg">
              Les règles qui s’appliquent aux clients et aux professionnels sur Tratra, sur le site comme dans l’application.
            </p>
            <dl className="mt-6 flex flex-wrap gap-2 text-sm">
              <div className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-1.5">
                <dt className="text-white/60">Mise à jour</dt>
                <dd className="font-semibold">
                  <time dateTime={TERMS_UPDATED_ON}>{TERMS_UPDATED_LABEL}</time>
                </dd>
              </div>
              <div className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-1.5">
                <dt className="text-white/60">Version</dt>
                <dd className="font-semibold">{TERMS_VERSION}</dd>
              </div>
            </dl>
          </div>
        </header>

        <section aria-labelledby="essentiel" className={`-mt-6 ${CONTAINER}`}>
          <h2 id="essentiel" className="sr-only">
            L’essentiel
          </h2>
          <ul className="relative grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {ESSENTIALS.map((e) => (
              <li key={e.title} className="rounded-card border border-line bg-surface p-4 shadow-sm">
                <e.icon aria-hidden className="h-5 w-5 text-primary" />
                <p className="mt-2 font-display text-[15px] font-bold text-ink">{e.title}</p>
                <p className="mt-1 text-sm leading-snug text-inkSoft">{e.text}</p>
              </li>
            ))}
          </ul>
        </section>

        <div className={`grid gap-10 py-10 sm:py-14 lg:grid-cols-[16rem_minmax(0,1fr)] ${CONTAINER}`}>
          <TableOfContents />

          <article className="min-w-0 max-w-3xl">
            <p className="text-base leading-relaxed text-inkSoft">
              En utilisant Tratra, vous acceptez ces conditions ainsi que la{" "}
              <A href="/confidentialite">politique de confidentialité</A>. Lisez-les attentivement : elles décrivent ce que chacun peut
              attendre de Tratra et des autres membres.
            </p>
            <div className="mt-10 space-y-10">
              {SECTIONS.map((s, i) => (
                <section key={s.id} id={s.id} aria-labelledby={`${s.id}-titre`} className="scroll-mt-24">
                  <h2 id={`${s.id}-titre`} className="flex items-baseline gap-3 font-display text-xl font-bold text-ink sm:text-2xl">
                    <span className="text-base font-extrabold text-primary">{String(i + 1).padStart(2, "0")}</span>
                    {s.title}
                  </h2>
                  <div className="mt-3 space-y-3 text-[15px] leading-relaxed text-inkSoft">{s.body}</div>
                </section>
              ))}
            </div>
            <aside className="mt-12 flex items-start gap-3 rounded-card border border-primary/20 bg-primarySoft/50 p-5 text-sm text-inkSoft">
              <FileSignature aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-primaryDark" />
              <p>
                Version {TERMS_VERSION}, mise à jour le <time dateTime={TERMS_UPDATED_ON}>{TERMS_UPDATED_LABEL}</time>. Une question sur ces
                conditions ? Écrivez à <Mail />.
              </p>
            </aside>
          </article>
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
