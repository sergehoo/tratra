/** Centre de notifications : types partagés avec l'API (/notifications/) et liens vers l'objet concerné. */
export interface Notif {
  id: number;
  notification_type: string;
  category: string;
  category_label: string;
  title: string;
  message: string;
  data: { kind?: string; id?: number; audience?: string; org?: number };
  deeplink: string;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
}

export interface UnreadCount {
  unread: number;
  by_category: Record<string, number>;
}

export interface NotificationPreference {
  category: string;
  label: string;
  push_enabled: boolean;
  locked: boolean;
}

export interface PreferencesResponse {
  preferences: NotificationPreference[];
  marketing_consent: { granted: boolean; granted_at: string | null; revoked_at: string | null };
}

/** Catégories du serveur (même ordre que Flutter). */
export const NOTIFICATION_CATEGORIES: { id: string; label: string }[] = [
  { id: "booking", label: "Réservations" },
  { id: "message", label: "Messages" },
  { id: "payment", label: "Paiements" },
  { id: "live", label: "Suivi" },
  { id: "review", label: "Avis" },
  { id: "account", label: "Compte" },
  { id: "business", label: "Entreprise" },
  { id: "engagement", label: "Contrats et engagements" },
  { id: "announcement", label: "Annonces" },
  { id: "system", label: "Infos" },
];

/** Page du site correspondant à l'objet d'une notification ; null = aucune cible (la notification est simplement lue). */
export function notificationHref(n: Pick<Notif, "data">): string | null {
  const { kind, id } = n.data ?? {};
  switch (kind) {
    case "booking":
      return id != null ? `/dashboard/bookings/${id}` : null;
    case "mission":
      return id != null ? `/dashboard/provider/missions/${id}` : null;
    case "conversation":
      return id != null ? `/dashboard/messages?c=${id}` : null;
    case "reviews":
      return "/dashboard/reviews";
    case "kyc":
      return "/dashboard/profile/kyc";
    case "business_request":
      return id != null ? `/dashboard/business/requests/${id}` : "/dashboard/business/requests";
    case "contract":
      return id != null ? `/dashboard/engagements/contracts/${id}` : "/dashboard/engagements";
    case "posting":
      return id != null ? `/dashboard/engagements/postings/${id}` : "/dashboard/engagements";
    case "replacements":
      return "/dashboard/engagements/replacements";
    case "announcement":
      return id != null ? `/dashboard/announcements?a=${id}` : "/dashboard/announcements";
    default:
      return null;
  }
}
