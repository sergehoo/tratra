/**
 * Ce que l'accueil montre de l'espace professionnel, d'après les statuts RÉELS du serveur (handy/eligibility.py,
 * `eligibility_summary`) — jamais déduit du seul « 7/7 ». Même logique que l'application
 * (lib/screens/dashboard/pro_status.dart) ; testée par `npm run test:bo`.
 */

export type ProHomeKind = "verified" | "firstOffer" | "kycRejected" | "progress" | "kycPending" | "approvalPending" | "blocked";

export interface ProHomeState {
  kind: ProHomeKind;
  title: string;
  message: string;
  /** Action du serveur (edit_profile, verify_identity, add_service, manage_services, contact_support) ; null = aucun bouton. */
  action: { code: string; label: string } | null;
}

/** Sous-ensemble de la synthèse d'éligibilité utilisé ici (types complets : src/lib/dashboard.tsx). */
export interface EligibilityLike {
  profile: { complete: boolean };
  kyc: { status: string; reason: string | null };
  publication: { authorized: boolean; blockers: { code: string; label: string; hint?: string | null; action: { code: string; label: string } | null }[] };
  offers: { total: number };
}

export const isVerified = (s: ProHomeState) => s.kind === "verified" || s.kind === "firstOffer";

/** Carte de progression (barre + « Continuer ») : seulement tant qu'il reste quelque chose à faire soi-même. */
export const showsProgress = (s: ProHomeState) => s.kind === "progress" || s.kind === "kycRejected";

export function proHomeState(e: EligibilityLike | null | undefined, fallback: { publishable: boolean; servicesTotal: number }): ProHomeState {
  const state = (kind: ProHomeKind, title = "", message = "", action: ProHomeState["action"] = null): ProHomeState => ({ kind, title, message, action });
  if (!e) {
    // Serveur sans synthèse : seule l'autorisation de publication calculée par le serveur fait foi.
    if (fallback.publishable) return fallback.servicesTotal === 0 ? firstOffer() : state("verified");
    return state("progress", "Profil professionnel", "", { code: "edit_profile", label: "Continuer" });
  }
  if (e.publication.authorized) return e.offers.total === 0 ? firstOffer() : state("verified");
  if (e.kyc.status === "rejected") {
    return state("kycRejected", "Nouvelle pièce d’identité demandée",
      (e.kyc.reason ?? "").trim() || "Reprenez des photos nettes et complètes de votre pièce.", { code: "verify_identity", label: "Reprendre ma pièce" });
  }
  const incomplete = e.publication.blockers.find((b) => b.code === "profile_incomplete");
  if (incomplete || !e.profile.complete) {
    return state("progress", "Profil professionnel", incomplete?.label ?? "", { code: "edit_profile", label: "Continuer" });
  }
  if (e.kyc.status === "draft") {
    return state("progress", "Profil professionnel", "Il reste à faire vérifier votre identité.", { code: "verify_identity", label: "Continuer" });
  }
  if (e.kyc.status === "pending") {
    return state("kycPending", "Identité en cours de vérification", "L’équipe Tratra examine votre pièce. Vous serez prévenu(e) de la décision.");
  }
  const other = e.publication.blockers.find((b) => b.code !== "approval_pending" && b.code !== "profile_incomplete" && !b.code.startsWith("kyc_"));
  if (other) return state("blocked", other.label, other.hint ?? "", other.action);
  return state("approvalPending", "Validation finale en cours",
    "Votre identité est vérifiée. L’équipe Tratra valide votre profil : aucune action n’est nécessaire.");

  function firstOffer(): ProHomeState {
    return state("firstOffer", "Créez votre première prestation",
      "Votre profil est vérifié : ajoutez une prestation pour recevoir vos premières missions.", { code: "add_service", label: "Créer ma première prestation" });
  }
}

/** Page du site pour une action du serveur. */
export function actionHref(code: string): string {
  switch (code) {
    case "verify_identity":
      return "/dashboard/profile/identity";
    case "add_service":
      return "/dashboard/provider/services/new";
    case "manage_services":
      return "/dashboard/provider";
    case "contact_support":
      return "mailto:support@tratra.net?subject=Mon%20espace%20professionnel%20Tratra";
    default:
      return "/dashboard/profile";
  }
}
