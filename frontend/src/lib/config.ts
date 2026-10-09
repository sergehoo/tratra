const configuredApiBase =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/handy";

/**
 * Base de l'API sans slash final afin que les appels restent valides quelle que
 * soit la forme de NEXT_PUBLIC_API_BASE fournie au déploiement.
 */
export const API_BASE = configuredApiBase.replace(/\/+$/, "");

export type PaymentMethod = "om" | "mtn" | "card" | "cash";

const PAYMENT_METHOD_LABELS: Record<PaymentMethod, string> = {
  om: "Orange Money",
  mtn: "MTN MoMo",
  card: "Carte bancaire",
  cash: "Espèces à la prestation",
};

const configuredPaymentMethods = (process.env.NEXT_PUBLIC_PAYMENT_METHODS ?? "cash")
  .split(",")
  .map((method) => method.trim().toLowerCase())
  .filter((method): method is PaymentMethod => method in PAYMENT_METHOD_LABELS);

/**
 * Methods explicitly enabled at build time.  Online providers stay hidden by
 * default until their server adapter, webhook and reconciliation are live.
 */
export const PAYMENT_METHODS = (configuredPaymentMethods.length
  ? configuredPaymentMethods
  : ["cash"] as PaymentMethod[]
).map((value) => ({ value, label: PAYMENT_METHOD_LABELS[value] }));

/**
 * Séquestre des paiements (fonds conservés par la plateforme jusqu'à la fin de
 * la mission). FAUX par défaut : aujourd'hui seul le paiement à la prestation
 * est possible. N'activer (NEXT_PUBLIC_ESCROW_ENABLED=true au build) que
 * lorsqu'un prestataire en ligne de handy/services/gateway.py est disponible et
 * que son webhook place réellement les fonds sous séquestre.
 */
export const ESCROW_ENABLED = process.env.NEXT_PUBLIC_ESCROW_ENABLED === "true";

/**
 * Partage social par défaut, repris par le layout et par l'accueil (un
 * `openGraph` de page remplace entièrement celui du layout).
 */
export const SHARE = {
  title: "Tratra — Artisans vérifiés à domicile",
  description: `Réservez un artisan vérifié près de chez vous. ${
    ESCROW_ENABLED ? "Paiement sécurisé" : "Paiement à la fin de l’intervention"
  }, suivi en temps réel.`,
  image: { url: "/og-image.jpg", width: 1200, height: 630, alt: "Tratra — Artisans vérifiés à domicile" },
};

/** Espace d'accueil par défaut selon le type d'utilisateur. */
export const HOME_BY_ROLE: Record<string, string> = {
  client: "/dashboard",
  employeur: "/dashboard",
  handyman: "/dashboard",
  entreprise: "/company",
  admin: "/admin",
};
