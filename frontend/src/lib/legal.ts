/**
 * Conditions d'utilisation : version en vigueur. DOIT concorder avec `handy/legal.py` (vérifié par `handy/test_terms.py`).
 * Publier de nouvelles conditions = changer ces trois valeurs ici ET côté serveur, dans le même commit : l'inscription
 * annonce `TERMS_VERSION` et le serveur refuse une version périmée (`terms_outdated`).
 */
export const TERMS_VERSION = "2026-11-12";
export const TERMS_UPDATED_ON = "2026-11-12";
export const TERMS_PATH = "/conditions-utilisation";

/** « 12 novembre 2026 » (fuseau UTC : la date ne dépend pas du fuseau du visiteur). */
export const TERMS_UPDATED_LABEL = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }).format(
  new Date(`${TERMS_UPDATED_ON}T00:00:00Z`),
);

/**
 * Mentions d'identification de l'éditeur (dénomination, forme, capital, siège, immatriculation…), séparées par « | »,
 * fournies au build par NEXT_PUBLIC_LEGAL_MENTIONS. Vide = non publiées : la page le dit, rien n'est inventé.
 */
export const LEGAL_MENTIONS = (process.env.NEXT_PUBLIC_LEGAL_MENTIONS ?? "")
  .split("|")
  .map((s) => s.trim())
  .filter(Boolean);

export const SUPPORT_EMAIL = "support@tratra.net";
