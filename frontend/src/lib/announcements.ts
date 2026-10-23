import { notificationHref } from "@/lib/notifications";

/** Annonce telle que l'utilisateur la voit (GET /me/announcements/) : aucune donnée de ciblage ni statistique. */
export interface FeedAnnouncement {
  id: number;
  title: string;
  body: string;
  kind: "service" | "promotion";
  image: string | null;
  /** `web` : équivalent sur le site d'un écran de l'application (registre central du serveur) ; null = pas de page web. */
  action: { kind: "link" | "deeplink"; label: string; value: string; web?: string | null } | null;
  delivered_at: string;
  expires_at: string | null;
  seen_at: string | null;
  opened_at: string | null;
}

export type AnnouncementEvent = "seen" | "open" | "dismiss";

export type ResolvedAction = { external: boolean; href: string; label: string };

/**
 * Action d'une annonce. Le serveur la valide déjà ; le site la revérifie avant de l'afficher :
 *  - lien externe : https uniquement (jamais javascript:, http:, data:…) ;
 *  - écran du site : uniquement une destination connue (mêmes cibles que les notifications).
 * Une action illisible est ignorée : aucun bouton, jamais d'exécution à l'aveugle.
 */
export function resolveAnnouncementAction(a: Pick<FeedAnnouncement, "action">): ResolvedAction | null {
  const action = a.action;
  if (!action || !action.value?.trim()) return null;
  const label = action.label?.trim() || "Voir";
  if (action.kind === "link") {
    try {
      const url = new URL(action.value.trim());
      return url.protocol === "https:" && url.hostname ? { external: true, href: url.toString(), label } : null;
    } catch {
      return null;
    }
  }
  if (action.kind === "deeplink") {
    // Chemin du site fourni par le serveur : relatif au site uniquement (jamais « //autre-site », « /\autre-site » ni une adresse complète).
    if (typeof action.web === "string" && /^\/(?![\/\\])/.test(action.web)) return { external: false, href: action.web, label };
    if (action.web === null) return null;
    const [kind, rawId] = action.value.trim().split("/");
    const id = rawId !== undefined && /^\d+$/.test(rawId) ? Number(rawId) : undefined;
    const href = notificationHref({ data: { kind, id } });
    return href ? { external: false, href, label } : null;
  }
  return null;
}
