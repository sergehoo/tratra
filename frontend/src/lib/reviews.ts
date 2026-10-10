/** Critères d'évaluation (mêmes clés que l'API et l'app mobile) — libellés affichés. */
export const REVIEW_CRITERIA = [
  { key: "quality", label: "Qualité du travail" },
  { key: "punctuality", label: "Ponctualité" },
  { key: "professionalism", label: "Professionnalisme" },
  { key: "communication", label: "Communication" },
  { key: "price", label: "Rapport qualité / prix" },
] as const;
export type CriterionKey = (typeof REVIEW_CRITERIA)[number]["key"];

export interface ReviewReply {
  text: string;
  at: string | null;
}

/** Avis tel que renvoyé par /me/reviews/ (reçus et donnés). */
export interface ReviewRow {
  id: number;
  rating: number;
  comment: string;
  created_at: string;
  booking_id: number;
  service: string | null;
  criteria: Partial<Record<CriterionKey, number>>;
  photos: string[];
  reply: ReviewReply | null;
  author?: string;
  artisan?: string;
  can_reply?: boolean;
  can_edit?: boolean;
}
