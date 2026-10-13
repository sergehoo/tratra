/**
 * Modèle de navigation du Back-Office : 7 rubriques, sous-menus, index de recherche globale et fil d'Ariane.
 *
 * Pur (aucun React, aucune icône) : testé avec `node --test` (boNavModel.test.ts). Les modules affichés viennent du serveur
 * (`/handy/backoffice/me/` → `modules`, déjà filtrés par rôle) : ce fichier ne fait que les REGROUPER. Les routes existantes
 * ne changent pas ; les sous-menus pointent vers les onglets réels des pages (`?tab=`).
 */

export type GroupId = "overview" | "people" | "missions" | "business" | "finance" | "communication" | "administration";

export interface ModuleLike {
  id: string;
  label: string;
  path: string;
}

export interface GroupDef {
  id: GroupId;
  label: string;
  /** Identifiants de modules (registre serveur `backoffice/modules.py`), dans l'ordre d'affichage. */
  modules: readonly string[];
}

/** Les 7 rubriques. Un module absent de cette table (futur module) tombe dans « Administration » : jamais perdu. */
export const GROUPS: readonly GroupDef[] = [
  { id: "overview", label: "Vue d’ensemble", modules: ["dashboard", "analytics"] },
  { id: "people", label: "Utilisateurs & Identités", modules: ["users", "kyc", "trust", "tratra_id"] },
  { id: "missions", label: "Prestations & Missions", modules: ["services", "bookings", "live", "reviews", "engagements", "continuity"] },
  { id: "business", label: "Tratra Business", modules: ["business"] },
  { id: "finance", label: "Finances", modules: ["finance"] },
  { id: "communication", label: "Communication", modules: ["messages", "announcements", "notifications", "support"] },
  { id: "administration", label: "Administration", modules: ["settings", "security"] },
];

export interface SubDef {
  /** Valeur de `?tab=` de la page. */
  tab: string;
  label: string;
  keywords?: string;
}

/** Sous-menus = onglets réels des pages (la page lit `?tab=`). Le premier est l'onglet par défaut. */
export const SUBS: Record<string, readonly SubDef[]> = {
  services: [{ tab: "services", label: "Services" }, { tab: "categories", label: "Catégories et métiers", keywords: "tarifs métiers" }],
  bookings: [{ tab: "bookings", label: "Réservations" }, { tab: "disputes", label: "Litiges", keywords: "médiation réclamation" }],
  kyc: [{ tab: "files", label: "Dossiers" }, { tab: "risks", label: "Risques et fraudes", keywords: "doublons fraude documents incohérents expirés identité" }],
  reviews: [{ tab: "reviews", label: "Avis" }, { tab: "reports", label: "Signalements", keywords: "modération abus" }, { tab: "watch", label: "Surveillance", keywords: "évaluations réputation fraude contestation recours bannissement" }],
  business: [
    { tab: "organizations", label: "Organisations", keywords: "entreprises sites équipements" },
    { tab: "requests", label: "Demandes d’intervention" },
    { tab: "invoices", label: "Factures entreprises" },
  ],
  engagements: [
    { tab: "overview", label: "Vue d’ensemble" },
    { tab: "contracts", label: "Contrats", keywords: "longue durée résiliation" },
    { tab: "postings", label: "Besoins publiés", keywords: "annonces candidatures" },
    { tab: "installments", label: "Échéances", keywords: "paiements mensuels" },
    { tab: "disputes", label: "Litiges" },
    { tab: "evaluations", label: "Évaluations" },
    { tab: "rules", label: "Règles", keywords: "paramètres délais plafonds" },
  ],
  finance: [
    { tab: "payments", label: "Paiements", keywords: "remboursement commission séquestre" },
    { tab: "payouts", label: "Retraits", keywords: "virement gains artisans" },
    { tab: "invoices", label: "Factures" },
  ],
  settings: [
    { tab: "integrations", label: "Intégrations", keywords: "firebase push sms e-mail paiements stockage" },
    { tab: "commissions", label: "Commissions", keywords: "tarifs frais plateforme" },
    { tab: "cancellation", label: "Annulation", keywords: "pénalité politique" },
    { tab: "trust", label: "Tratra Trust", keywords: "seuils poids badges score" },
    { tab: "coupons", label: "Codes promo", keywords: "promotion réduction" },
    { tab: "transport", label: "Transport", keywords: "déplacement frais kilomètre tranches horaires zones forfait" },
  ],
  security: [
    { tab: "staff", label: "Personnel et rôles", keywords: "administrateurs double authentification mfa" },
    { tab: "sessions", label: "Sessions" },
    { tab: "audit", label: "Journal d’audit", keywords: "traçabilité historique actions" },
  ],
};

/** Mots-clés de recherche (en plus du libellé). */
export const KEYWORDS: Record<string, string> = {
  dashboard: "accueil indicateurs kpi alertes à traiter",
  analytics: "statistiques exports csv rapports",
  users: "comptes clients artisans entreprises téléphone e-mail suspendre",
  kyc: "vérification identité pièces documents dossiers artisans",
  trust: "badges réputation score certifications confiance",
  tratra_id: "qr identifiant professionnel pass mission",
  services: "prestations catégories métiers modération",
  bookings: "missions réservations litiges annulations",
  live: "suivi gps position interventions incidents",
  reviews: "avis notes commentaires signalements modération",
  engagements: "contrats longue durée échéances récurrents",
  continuity: "activités en cours synchronisation erreurs",
  business: "entreprise organisations sites équipements budgets",
  finance: "paiements commissions remboursements retraits factures séquestre",
  messages: "messagerie écrire message membre destinataires envoi individuel réponses boîte",
  announcements: "annonces campagnes bandeaux publication",
  notifications: "push sms e-mail envois historique",
  support: "tickets réclamations médiation notes",
  settings: "réglages tarifs annulation coupons règles intégrations",
  security: "rôles sessions audit journal mfa administrateurs",
};

export interface NavSub {
  tab: string;
  label: string;
  href: string;
  keywords: string;
}

export interface NavEntry {
  id: string;
  label: string;
  href: string;
  subs: NavSub[];
}

export interface NavGroup {
  id: GroupId;
  label: string;
  /** Premier module du groupe : cible de l'icône quand la barre latérale est réduite. */
  href: string;
  items: NavEntry[];
}

/** Regroupe les modules AUTORISÉS (déjà filtrés par le serveur) en rubriques ; une rubrique sans module visible disparaît. */
export function buildNav(modules: readonly ModuleLike[]): NavGroup[] {
  const byId = new Map(modules.map((m) => [m.id, m]));
  const placed = new Set<string>();
  const groups: NavGroup[] = [];
  for (const def of GROUPS) {
    const items: NavEntry[] = [];
    for (const id of def.modules) {
      const m = byId.get(id);
      if (!m) continue;
      placed.add(id);
      items.push(entry(m));
    }
    if (def.id === "administration") {
      for (const m of modules) if (!placed.has(m.id)) items.push(entry(m)); // module inconnu : jamais invisible
    }
    if (items.length) groups.push({ id: def.id, label: def.label, href: items[0].href, items });
  }
  return groups;
}

function entry(m: ModuleLike): NavEntry {
  const subs = (SUBS[m.id] ?? []).map((s) => ({ tab: s.tab, label: s.label, href: `${m.path}?tab=${s.tab}`, keywords: s.keywords ?? "" }));
  return { id: m.id, label: m.label, href: m.path, subs };
}

/** Module actif = le plus long chemin préfixe (limite de segment) du chemin courant. */
export function activeModule(nav: readonly NavGroup[], pathname: string): { group: NavGroup; item: NavEntry } | null {
  let best: { group: NavGroup; item: NavEntry } | null = null;
  for (const group of nav) {
    for (const item of group.items) {
      const hit = item.href === "/backoffice" ? pathname === "/backoffice" : pathname === item.href || pathname.startsWith(`${item.href}/`);
      if (hit && (!best || item.href.length > best.item.href.length)) best = { group, item };
    }
  }
  return best;
}

/** Sous-menu actif : l'onglet de l'URL, sinon le premier (onglet par défaut de la page). */
export function activeSub(item: NavEntry, tab: string | null): NavSub | null {
  if (!item.subs.length) return null;
  return item.subs.find((s) => s.tab === tab) ?? item.subs[0];
}

// ── Recherche globale ────────────────────────────────────────────────────────────────────────────────────────────────

export interface SearchEntry {
  label: string;
  group: string;
  href: string;
  haystack: string;
}

/** Minuscules, sans accents ni ponctuation : « Vérification KYC » ≈ « verification kyc ». */
export function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[’'`´]/g, " ")
    .replace(/[^a-z0-9@+.#\s-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Pages cherchables : chaque module et chaque sous-menu autorisés. */
export function searchEntries(nav: readonly NavGroup[]): SearchEntry[] {
  const out: SearchEntry[] = [];
  for (const g of nav) {
    for (const item of g.items) {
      out.push({ label: item.label, group: g.label, href: item.href, haystack: normalize(`${item.label} ${g.label} ${KEYWORDS[item.id] ?? ""}`) });
      for (const s of item.subs) {
        out.push({ label: `${item.label} › ${s.label}`, group: g.label, href: s.href, haystack: normalize(`${item.label} ${s.label} ${s.keywords} ${KEYWORDS[item.id] ?? ""}`) });
      }
    }
  }
  return out;
}

/** Toutes les saisies (séparées par des espaces) doivent apparaître ; le libellé qui COMMENCE par la saisie passe en tête. */
export function searchLocal(entries: readonly SearchEntry[], query: string, limit = 8): SearchEntry[] {
  const words = normalize(query).split(" ").filter(Boolean);
  if (!words.length) return [];
  const scored: { e: SearchEntry; score: number }[] = [];
  for (const e of entries) {
    if (!words.every((w) => e.haystack.includes(w))) continue;
    const label = normalize(e.label);
    const score = (label.startsWith(words[0]) ? 0 : label.includes(words[0]) ? 1 : 2) + (e.href.includes("?tab=") ? 0.5 : 0);
    scored.push({ e, score });
  }
  return scored.sort((a, b) => a.score - b.score || a.e.label.localeCompare(b.e.label, "fr")).slice(0, limit).map((s) => s.e);
}

// ── Fil d'Ariane ─────────────────────────────────────────────────────────────────────────────────────────────────────

export interface Crumb {
  label: string;
  href?: string;
}

/** `Back-Office › Rubrique › Module › onglet | fiche`. `detailLabel` (ex. nom du compte) remplace « Fiche #id ». */
export function breadcrumb(nav: readonly NavGroup[], pathname: string, tab: string | null, detailLabel?: string | null): Crumb[] {
  const crumbs: Crumb[] = [{ label: "Back-Office", href: "/backoffice" }];
  const hit = activeModule(nav, pathname);
  if (!hit) return crumbs;
  const { group, item } = hit;
  const isHome = item.href === "/backoffice";
  // Rubrique d'un seul module portant le même nom (Finances, Tratra Business) : pas de maillon en double.
  const sameName = group.items.length === 1 && normalize(group.label) === normalize(item.label);
  if (!isHome && !sameName) crumbs.push({ label: group.label });
  const rest = pathname.slice(item.href.length).split("/").filter(Boolean);
  const sub = activeSub(item, tab);
  if (isHome) {
    crumbs.push({ label: item.label });
  } else if (rest.length) {
    crumbs.push({ label: item.label, href: item.href });
    crumbs.push({ label: detailLabel || (/^\d+$/.test(rest[0]) ? `Fiche #${rest[0]}` : rest.join(" › ")) });
  } else if (sub && item.subs.length > 1) {
    crumbs.push({ label: item.label, href: item.href });
    crumbs.push({ label: sub.label });
  } else {
    crumbs.push({ label: item.label });
  }
  return crumbs;
}
