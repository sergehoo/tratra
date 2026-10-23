/**
 * Annonces (Back-Office) SANS dépendance, testables par `node --test` : destinations de l'application issues du registre central
 * du serveur (`GET /backoffice/announcements/destinations/`), filtrées selon les destinataires, et aperçu de la notification.
 */
export type Role = "clients" | "artisans" | "companies";

export interface AppDestination {
  key: string;
  label: string;
  group: string;
  roles: Role[];
  /** Paramètre attendu : métier/prestation du catalogue, offre précise, annonce. */
  param: "category" | "service" | "announcement" | null;
  param_required: boolean;
}

export interface DestinationCheck {
  key: string | null;
  label: string;
  detail: string;
  roles: Role[];
  valid: boolean;
  error: string;
  web: string | null;
}

export const ROLE_LABEL: Record<Role, string> = { clients: "clients", artisans: "artisans", companies: "entreprises" };

export function rolesOf(f: { to_clients: boolean; to_artisans: boolean; to_companies: boolean }): Role[] {
  return ([["clients", f.to_clients], ["artisans", f.to_artisans], ["companies", f.to_companies]] as const)
    .filter(([, on]) => on)
    .map(([r]) => r);
}

/** Une destination n'est proposée que si TOUS les destinataires choisis peuvent l'ouvrir. */
export function allowedFor(d: AppDestination, roles: Role[]): boolean {
  return roles.every((r) => d.roles.includes(r));
}

/** Destinations groupées (ordre du registre), filtrées selon les destinataires. */
export function groupedDestinations(all: AppDestination[], roles: Role[]): [string, AppDestination[]][] {
  const groups = new Map<string, AppDestination[]>();
  for (const d of all) {
    if (!allowedFor(d, roles)) continue;
    groups.set(d.group, [...(groups.get(d.group) ?? []), d]);
  }
  return [...groups.entries()];
}

/** « clé » ou « clé/12 » ↔ { key, id }. */
export function splitValue(value: string): { key: string; id: string } {
  const [key = "", id = ""] = (value || "").split("/");
  return { key, id: /^\d+$/.test(id) ? id : "" };
}

export function joinValue(key: string, id: string): string {
  return key && /^\d+$/.test(id) ? `${key}/${id}` : key;
}

/** Ce qu'Android affiche : titre tel quel, texte limité à 200 caractères (complet dans l'application). */
export function pushText(title: string, body: string): { title: string; body: string; truncated: boolean } {
  const t = title.trim();
  const b = body.trim();
  return { title: t, body: b.slice(0, 200), truncated: b.length > 200 };
}

export interface PreviewInput {
  title: string;
  body: string;
  kind: string;
  send_push: boolean;
  hasImage: boolean;
  action_kind: string;
  action_label: string;
  roles: Role[];
  destinationError?: string;
}

/** Points d'attention affichés sous l'aperçu (rien n'est bloqué ici : le serveur valide à l'enregistrement et à la publication). */
export function previewNotes(p: PreviewInput): { tone: "info" | "warning" | "danger"; text: string }[] {
  const notes: { tone: "info" | "warning" | "danger"; text: string }[] = [];
  if (!p.roles.length) notes.push({ tone: "danger", text: "Choisissez au moins un type de destinataires." });
  if (p.destinationError) notes.push({ tone: "danger", text: p.destinationError });
  if (!p.send_push) notes.push({ tone: "info", text: "Sans notification push : l’annonce apparaît seulement dans l’application et sur le site." });
  if (p.send_push && p.title.trim().length > 50) notes.push({ tone: "warning", text: "Titre long : il peut être coupé dans la notification repliée." });
  if (p.send_push && pushText(p.title, p.body).truncated) notes.push({ tone: "warning", text: "Texte de plus de 200 caractères : la notification en montre le début, l’application le texte complet." });
  if (p.send_push && !p.hasImage) notes.push({ tone: "info", text: "Sans image : notification texte." });
  if (p.send_push && p.hasImage) notes.push({ tone: "info", text: "Image recadrée au centre : format 2:1 dans la notification, bandeau pleine largeur dans l’application." });
  if (p.action_kind === "link") notes.push({ tone: "info", text: "Lien web : toucher la notification ouvre l’annonce dans l’application, d’où le bouton mène au site." });
  if (p.action_kind === "deeplink" && !p.action_label.trim()) notes.push({ tone: "info", text: "Bouton sans libellé : « Voir » sera affiché." });
  if (p.kind === "promotion") notes.push({ tone: "info", text: "Promotion : seuls les comptes ayant donné leur consentement marketing la recevront." });
  return notes;
}
