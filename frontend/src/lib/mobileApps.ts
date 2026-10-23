/**
 * Badges officiels Google Play / App Store (landing) SANS dépendance : testables par `node --test`.
 *
 * Les liens viennent de `GET /public/mobile-apps/` (configurés dans l'administration Django) ; `null` = badge masqué.
 * Le serveur ne publie que des fiches officielles ; le site revérifie quand même chaque lien avant de l'afficher (HTTPS, hôte
 * exact, sans identifiant ni port, chemin de fiche) : un lien inattendu n'est jamais rendu cliquable.
 */
export interface PublicMobileApps {
  android_url: string | null;
  ios_url: string | null;
}

export type StoreKind = "android" | "ios";

export interface StoreBadge {
  kind: StoreKind;
  href: string;
  /** Nom accessible du lien (le visuel est décoratif). */
  label: string;
  src: string;
  width: number;
  height: number;
  target: "_blank";
  rel: "noopener noreferrer";
}

const PACKAGE = /^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$/;
const APPLE_PATH = /^\/(?:[a-z]{2}\/)?app\/(?:(?!\.{1,2}\/)[A-Za-z0-9\-._~%]{1,120}\/)?id\d{6,12}\/?$/;

/** Visuels officiels (public/images/stores, cf. images/CREDITS.md : seules les marges transparentes du PNG Google sont rognées,
 * pour que les deux badges VISIBLES aient la même hauteur) ; dimensions intrinsèques. */
const STORES: Record<StoreKind, Omit<StoreBadge, "href" | "target" | "rel">> = {
  android: {
    kind: "android",
    label: "Disponible sur Google Play (s’ouvre dans un nouvel onglet)",
    src: "/images/stores/google-play-badge-fr.png",
    width: 646,
    height: 192,
  },
  ios: {
    kind: "ios",
    label: "Télécharger dans l’App Store (s’ouvre dans un nouvel onglet)",
    src: "/images/stores/app-store-badge-fr.svg",
    width: 127,
    height: 40,
  },
};

/** Lien de fiche officielle, ou null (vide, autre hôte, autre protocole, redirection…). */
export function officialStoreUrl(kind: StoreKind, raw: string | null | undefined): string | null {
  const value = (raw ?? "").trim();
  if (!value || /[\s\u0000-\u001f]/.test(value)) return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" || url.username || url.password || url.port) return null;
  if (kind === "android") {
    const ids = url.searchParams.getAll("id");
    const ok = url.hostname === "play.google.com" && url.pathname.replace(/\/+$/, "") === "/store/apps/details"
      && ids.length === 1 && PACKAGE.test(ids[0]);
    return ok ? url.toString() : null;
  }
  return url.hostname === "apps.apple.com" && APPLE_PATH.test(url.pathname) ? url.toString() : null;
}

/** Badges à afficher, dans l'ordre Google Play puis App Store ; vide = rien à rendre (ni titre, ni espace réservé). */
export function storeBadges(apps: PublicMobileApps | null | undefined): StoreBadge[] {
  if (!apps) return [];
  return (["android", "ios"] as const).flatMap((kind) => {
    const href = officialStoreUrl(kind, kind === "android" ? apps.android_url : apps.ios_url);
    return href ? [{ ...STORES[kind], href, target: "_blank" as const, rel: "noopener noreferrer" as const }] : [];
  });
}
