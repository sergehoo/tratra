/**
 * Ce que l'accueil montre de l'espace professionnel, d'après les statuts RÉELS du serveur (handy/eligibility.py,
 * `eligibility_summary`) — trois niveaux distincts : publication (sans vérification d'identité, mention « Non vérifié »),
 * commandes (pièce d'identité approuvée), badge « Vérifié » (vérification faciale validée). Même logique que l'application
 * (lib/screens/dashboard/pro_status.dart) ; testée par `npm run test:bo`. La vérification faciale se fait dans l'application :
 * le site l'annonce, sans bouton.
 */

export type ProHomeKind = "none" | "firstOffer" | "kycRejected" | "progress" | "activate" | "badge" | "kycPending" | "facePending" | "approvalPending" | "blocked";

type Action = { code: string; label: string; step?: string | null };
type Blocker = { code: string; label: string; hint?: string | null; action: Action | null };

export interface ProHomeState {
  kind: ProHomeKind;
  title: string;
  message: string;
  /** Action du serveur (edit_profile, verify_identity, add_service, manage_services, contact_support) ; null = aucun bouton. */
  action: Action | null;
  /** NON_VERIFIE | IDENTITE_VERIFIEE | VERIFIE — « Vérifié » uniquement après la vérification faciale. */
  level: string;
  levelLabel: string;
  published: boolean;
}

/** Sous-ensemble de la synthèse d'éligibilité utilisé ici (types complets : src/lib/dashboard.tsx). */
export interface EligibilityLike {
  profile: { complete: boolean };
  kyc: { status: string; reason: string | null };
  publication: { authorized: boolean; blockers: Blocker[] };
  orders?: { authorized: boolean; blockers: Blocker[] };
  verification?: { level: string; label: string; face?: { state?: string } | null };
  stages?: { key: string; benefit?: string }[];
  offers: { total: number; active?: number; action?: Action | null };
}

export const isVerified = (s: ProHomeState) => s.level === "VERIFIE";

/** Mention affichée près du nom tant que le badge n'est pas attribué : seulement si le profil est public. */
export const mention = (s: ProHomeState) => (s.published ? s.levelLabel : null);

/** Carte de progression (barre + « Continuer ») : seulement tant que le profil n'est pas publiable. */
export const showsProgress = (s: ProHomeState) => s.kind === "progress";

const IN_APP = "Elle se fait dans l’application Tratra.";

export function proHomeState(e: EligibilityLike | null | undefined, fallback: { publishable: boolean; servicesTotal: number }): ProHomeState {
  if (!e) {
    // Serveur sans synthèse : seule l'autorisation calculée par le serveur fait foi ; jamais de badge.
    const base = { level: "IDENTITE_VERIFIEE", levelLabel: "Identité vérifiée", published: true };
    if (!fallback.publishable) {
      return { kind: "progress", title: "Profil professionnel", message: "", action: { code: "edit_profile", label: "Continuer" }, level: "NON_VERIFIE", levelLabel: "Non vérifié", published: false };
    }
    return fallback.servicesTotal === 0
      ? { kind: "firstOffer", title: "Publiez votre premier service", message: "Ajoutez un service pour apparaître dans la recherche.", action: { code: "add_service", label: "Publier un service" }, ...base }
      : { kind: "none", title: "", message: "", action: null, ...base };
  }
  const hasLevels = Boolean(e.verification);
  const published = e.publication.authorized;
  const orders = e.orders ? e.orders.authorized : published;
  const level = e.verification?.level ?? (published ? "IDENTITE_VERIFIEE" : "NON_VERIFIE");
  const levelLabel = e.verification?.label ?? (published ? "Identité vérifiée" : "Non vérifié");
  const faceState = e.verification?.face?.state ?? "unavailable";
  const st = (kind: ProHomeKind, title = "", message = "", action: Action | null = null): ProHomeState => ({ kind, title, message, action, level, levelLabel, published });
  const rejected = () => st("kycRejected", "Nouvelle pièce d’identité demandée",
    (e.kyc.reason ?? "").trim() || "Reprenez des photos nettes et complètes de votre pièce.", { code: "verify_identity", label: "Reprendre ma pièce" });

  // 1. Publication : elle ne dépend plus de la pièce d'identité (sauf serveur plus ancien, sans les niveaux).
  if (!published) {
    const incomplete = e.publication.blockers.find((b) => b.code === "profile_incomplete");
    if (!hasLevels && e.kyc.status === "rejected") return rejected();
    if (incomplete || !e.profile.complete) return st("progress", "Profil professionnel", incomplete?.label ?? "", { code: "edit_profile", label: "Continuer" });
    if (!hasLevels && e.kyc.status === "draft") {
      return st("progress", "Profil professionnel", "Il reste à faire vérifier votre identité.", { code: "verify_identity", label: "Continuer" });
    }
    if (!hasLevels && e.kyc.status === "pending") {
      return st("kycPending", "Identité en cours de vérification", "L’équipe Tratra examine votre pièce. Vous serez prévenu(e) de la décision.");
    }
    const other = e.publication.blockers.find((b) => b.code !== "approval_pending" && b.code !== "profile_incomplete" && !b.code.startsWith("kyc_"));
    if (other) return st("blocked", other.label, other.hint ?? "", other.action);
    return st("approvalPending", "Validation en cours", "L’équipe Tratra valide votre profil : aucune action n’est nécessaire.");
  }

  // 2. Un service à montrer.
  if (e.offers.total === 0) {
    return st("firstOffer", "Publiez votre premier service",
      "Votre profil est visible des clients. Ajoutez un service pour apparaître dans la recherche.", { code: "add_service", label: "Publier un service" });
  }
  if (e.offers.active === 0 && e.offers.action) {
    return st("blocked", "Aucun service actif", "Réactivez un service pour redevenir visible dans la recherche.", e.offers.action);
  }

  // 3. Commandes : pièce d'identité approuvée (et visage pour un métier sensible).
  if (!orders) {
    if (e.kyc.status === "rejected") return rejected();
    if (e.kyc.status === "pending") {
      return st("kycPending", "Identité en cours de vérification",
        `L’équipe Tratra examine votre pièce. Votre service reste visible avec la mention « ${levelLabel} » ; vous serez prévenu(e) de la décision.`);
    }
    if (e.kyc.status === "draft") {
      return st("activate", "Activez vos commandes",
        `Votre service est en ligne avec la mention « ${levelLabel} ». Faites vérifier votre pièce d’identité pour recevoir des réservations et des missions.`,
        { code: "verify_identity", label: "Activer mes commandes" });
    }
    const blockers = e.orders?.blockers ?? [];
    const face = blockers.find((b) => b.code === "face_required");
    if (face) {
      return faceState === "pending"
        ? st("facePending", "Vérification faciale en cours de revue",
          "Votre métier demande cette vérification avant les commandes. L’équipe Tratra l’examine : vous serez prévenu(e).")
        : st("activate", "Dernière étape avant vos commandes", `${face.hint || face.label} ${IN_APP}`);
    }
    const b = blockers[0];
    if (!b || b.code === "approval_pending") {
      return st("approvalPending", "Activation des commandes en attente",
        b?.hint || "Votre identité est vérifiée. L’équipe Tratra active vos commandes : aucune action n’est nécessaire.");
    }
    return st("blocked", b.label, b.hint ?? "", b.action);
  }

  // 4. Badge « Vérifié » : vérification faciale validée.
  if (level === "VERIFIE") return st("none");
  if (faceState === "todo" || faceState === "retry") {
    const benefit = e.stages?.find((s) => s.key === "face")?.benefit ?? "";
    return st("badge", faceState === "retry" ? "Reprenez la vérification faciale" : "Obtenez le badge « Vérifié »",
      `${benefit || "Une vérification faciale confirme que la pièce d’identité est bien la vôtre."} ${IN_APP}`);
  }
  if (faceState === "pending") {
    return st("facePending", "Vérification faciale en cours de revue",
      "Vos commandes restent activées. Le badge « Vérifié » s’affichera après la décision de l’équipe Tratra.");
  }
  return st("none");
}

/** Page du site pour une action du serveur. */
export function actionHref(code: string): string {
  switch (code) {
    case "verify_identity":
      return "/dashboard/profile/identity";
    case "verify_phone":
      return "/verify-phone?next=/dashboard";
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
