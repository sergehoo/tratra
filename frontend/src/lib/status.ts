import type { BadgeTone } from "@/components/ds/Badge";

/** Libellé français + ton visuel d'un statut métier. Aucune règle métier ici : affichage uniquement. */
export interface StatusView {
  label: string;
  tone: BadgeTone;
  /** Pastille animée : activité en direct. */
  pulse?: boolean;
}

export const BOOKING_STATUS: Record<string, StatusView> = {
  pending: { label: "En attente", tone: "accent" },
  confirmed: { label: "Confirmée", tone: "primary" },
  in_progress: { label: "En cours", tone: "night", pulse: true },
  completed: { label: "Terminée", tone: "success" },
  cancelled: { label: "Annulée", tone: "gray" },
};

export const DOCUMENT_STATUS: Record<string, StatusView> = {
  pending: { label: "En vérification", tone: "accent" },
  approved: { label: "Validé", tone: "success" },
  rejected: { label: "Refusé", tone: "danger" },
};

export const DISPUTE_STATUS: Record<string, StatusView> = {
  open: { label: "Ouvert", tone: "danger" },
  under_review: { label: "En cours d’examen", tone: "warning" },
  resolved: { label: "Résolu", tone: "success" },
  rejected: { label: "Rejeté", tone: "gray" },
};

export const SUBSCRIPTION_STATUS: Record<string, StatusView> = {
  active: { label: "Actif", tone: "success" },
  trialing: { label: "Période d’essai", tone: "info" },
  past_due: { label: "Paiement en retard", tone: "warning" },
  canceled: { label: "Résilié", tone: "gray" },
  cancelled: { label: "Résilié", tone: "gray" },
  expired: { label: "Expiré", tone: "gray" },
};

export const PAYMENT_STATUS: Record<string, StatusView> = {
  pending: { label: "En attente", tone: "accent" },
  held: { label: "Sous séquestre", tone: "info" },
  released: { label: "Versé à l’artisan", tone: "success" },
  completed: { label: "Payé", tone: "success" },
  failed: { label: "Échoué", tone: "danger" },
  refunded: { label: "Remboursé", tone: "gray" },
};

export const PAYOUT_STATUS: Record<string, StatusView> = {
  pending: { label: "En attente", tone: "accent" },
  sent: { label: "Envoyé", tone: "success" },
  failed: { label: "Échoué", tone: "danger" },
};

export const STATUS_KINDS = {
  booking: BOOKING_STATUS,
  document: DOCUMENT_STATUS,
  dispute: DISPUTE_STATUS,
  subscription: SUBSCRIPTION_STATUS,
  payment: PAYMENT_STATUS,
  payout: PAYOUT_STATUS,
} as const;

export type StatusKind = keyof typeof STATUS_KINDS;

/** Statut inconnu : on affiche la valeur brute en gris plutôt que de la cacher. */
export function statusView(kind: StatusKind, status: string | null | undefined): StatusView {
  const key = status ?? "";
  return STATUS_KINDS[kind][key] ?? { label: key || "—", tone: "gray" };
}
