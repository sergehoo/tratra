import { ApiError, post } from "./api";

export interface PendingEvaluation {
  booking_id: number;
  role: "client" | "provider";
  evaluated_role: "client" | "provider";
  service: string;
  completed_at: string;
  deadline: string;
  other_party_evaluated: boolean;
  criteria: { key: string; label: string }[];
}
export interface Score { count: number; average: number | null; public: boolean }
export interface Evaluations {
  pending: PendingEvaluation[];
  given: { id: number; booking_id: number; role: string; rating: number; comment: string; revealed: boolean; created_at: string; about: string }[];
  received_as_requester: { id: number; rating: number; comment: string; from: string; created_at: string; criteria: Record<string, number>; can_contest: boolean }[];
  provider_score: Score;
  requester_score: Score;
  missions_evaluated: number;
  history: { provider: { month: string; count: number; average: number }[]; requester: { month: string; count: number; average: number }[] };
  rules: { window_days: number; reveal_days: number; min_public_count: number };
}

export const submitEvaluation = (bookingId: number, body: { rating: number; comment?: string; criteria?: Record<string, number> }) => post(`/bookings/${bookingId}/evaluation/`, body);
export const contestEvaluation = (id: number, reason: string) => post(`/client-reviews/${id}/contest/`, { reason });

/** Message lisible d'une erreur d'évaluation (le serveur renvoie un code stable). */
export function evaluationError(e: unknown, fallback: string): string {
  if (e instanceof ApiError && e.data && typeof e.data === "object") {
    const d = e.data as { detail?: string; fields?: Record<string, string> };
    return d.fields ? Object.values(d.fields)[0] : d.detail ?? fallback;
  }
  return fallback;
}
