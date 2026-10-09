import { HOME_BY_ROLE } from "./config";
import type { User, UserType } from "./types";

/** Espaces protégés et rôles qui y ont accès (miroir des RoleGuard). */
const AREA_ROLES: Record<string, UserType[]> = {
  // Espace utilisateur UNIFIÉ : un même compte peut réserver (client) ET proposer des services (artisan).
  "/dashboard": ["client", "employeur", "entreprise", "handyman"],
  // Espace entreprise = capacité du compte unique (organisation liée) : accessible à tout compte non admin.
  "/company": ["client", "employeur", "entreprise", "handyman"],
  "/admin": ["admin"],
};

export const PROTECTED_PREFIXES = Object.keys(AREA_ROLES);

function areaOf(path: string): string | null {
  return PROTECTED_PREFIXES.find((p) => path === p || path.startsWith(`${p}/`) || path.startsWith(`${p}?`)) ?? null;
}

export function isProtectedPath(path: string): boolean {
  return areaOf(path) !== null;
}

/**
 * Chemin interne sûr : relatif au site, sans schéma ni « // » (anti open-redirect),
 * sans antislash ni caractère de contrôle.
 */
export function isSafeInternalPath(path: string | null | undefined): path is string {
  if (!path || typeof path !== "string") return false;
  if (!path.startsWith("/") || path.startsWith("//")) return false;
  if (path.includes("\\") || /[\u0000-\u001f]/.test(path)) return false;
  return true;
}

export function homeFor(role?: string | null): string {
  return (role && HOME_BY_ROLE[role]) || "/dashboard";
}

/**
 * Destination après connexion/inscription : `next` s'il est sûr ET accessible
 * au rôle, sinon l'espace par défaut du rôle.
 */
export function safeNext(next: string | null | undefined, role?: string | null): string {
  if (!isSafeInternalPath(next) || next === "/login" || next.startsWith("/register")) return homeFor(role);
  const area = areaOf(next);
  if (area && !(role && AREA_ROLES[area].includes(role as UserType))) return homeFor(role);
  return next;
}

export function loginHref(next?: string | null): string {
  return isSafeInternalPath(next) ? `/login?next=${encodeURIComponent(next)}` : "/login";
}

export type SignupType = "client" | "handyman" | "entreprise";

/** Après inscription, l'intention annoncée par le lien (devenir artisan, créer une entreprise) ouvre la
 *  page correspondante du MÊME compte : aucun type de compte n'est choisi à l'inscription. */
const INTENT_DESTINATION: Record<SignupType, string | null> = {
  client: null,
  handyman: "/dashboard/provide",
  entreprise: "/dashboard/company/new",
};

export function registerHref(type?: SignupType, next?: string | null): string {
  const sp = new URLSearchParams();
  const destination = isSafeInternalPath(next) ? next : type ? INTENT_DESTINATION[type] : null;
  if (destination) sp.set("next", destination);
  const s = sp.toString();
  return s ? `/register?${s}` : "/register";
}

export function spaceHref(user: Pick<User, "user_type"> | null | undefined): string | null {
  return user ? homeFor(user.user_type) : null;
}

/**
 * Lien de réservation d'un service :
 * - visiteur -> connexion puis retour sur la fiche de réservation ;
 * - tout compte non administrateur (client, employeur, entreprise, artisan) -> fiche de réservation
 *   (un artisan peut aussi réserver ; la fiche refuse de réserver son propre service) ;
 * - administrateur -> null (masquer le CTA).
 */
export function bookingHref(serviceId: number, user: Pick<User, "user_type"> | null | undefined): string | null {
  const target = `/dashboard/services/${serviceId}`;
  if (!user) return loginHref(target);
  return AREA_ROLES["/dashboard"].includes(user.user_type) ? target : null;
}
