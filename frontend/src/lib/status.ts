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

export const CONTRACT_STATUS: Record<string, StatusView> = {
  draft: { label: "Brouillon", tone: "gray" },
  pending_acceptance: { label: "À accepter", tone: "accent" },
  accepted: { label: "Accepté · début à venir", tone: "info" },
  active: { label: "En cours", tone: "success" },
  suspended: { label: "Suspendu", tone: "warning" },
  notice: { label: "Préavis en cours", tone: "warning" },
  terminated: { label: "Résilié", tone: "gray" },
  completed: { label: "Terminé", tone: "primary" },
  cancelled: { label: "Annulé", tone: "gray" },
};

export const INSTALLMENT_STATUS: Record<string, StatusView> = {
  scheduled: { label: "Planifiée", tone: "gray" },
  due: { label: "À régler", tone: "accent" },
  partial: { label: "Partiellement réglée", tone: "info" },
  paid: { label: "Réglée", tone: "success" },
  overdue: { label: "En retard", tone: "danger" },
  on_hold: { label: "Suspendue", tone: "warning" },
  waived: { label: "Solde abandonné", tone: "gray" },
  cancelled: { label: "Annulée", tone: "gray" },
};

export const POSTING_STATUS: Record<string, StatusView> = {
  draft: { label: "Brouillon", tone: "gray" },
  open: { label: "Ouvert aux candidatures", tone: "success" },
  closed: { label: "Clos", tone: "gray" },
  filled: { label: "Pourvu", tone: "primary" },
  cancelled: { label: "Annulé", tone: "gray" },
  expired: { label: "Expiré", tone: "gray" },
};

export const APPLICATION_STATUS: Record<string, StatusView> = {
  submitted: { label: "Reçue", tone: "accent" },
  shortlisted: { label: "Présélectionnée", tone: "info" },
  interview: { label: "Entretien", tone: "info" },
  selected: { label: "Retenue", tone: "success" },
  rejected: { label: "Non retenue", tone: "gray" },
  withdrawn: { label: "Retirée", tone: "gray" },
};

export const STATUS_KINDS = {
  contract: CONTRACT_STATUS,
  installment: INSTALLMENT_STATUS,
  posting: POSTING_STATUS,
  application: APPLICATION_STATUS,
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
