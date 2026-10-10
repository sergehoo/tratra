import { ApiError, apiJson, upload } from "./api";
import { randomHex } from "./continuity";

/**
 * Prestations récurrentes et engagements de longue durée : types partagés avec l'API `/handy/engagements/…`, libellés français et
 * appels. Les règles (qui peut quoi, quand) restent côté serveur : `actions` et `can_*` renvoyés par l'API pilotent l'interface.
 */

export type MissionType = "recurring" | "long_term";
export type Relationship = "independent" | "employment";
export type PayPeriod = "monthly" | "hourly" | "per_visit";

export interface Person { id: number; name: string }
export interface ScheduleSlot { weekday: number; start: string; end: string }
export interface Page<T> { count: number; limit: number; offset: number; next_offset: number | null; results: T[] }

export interface Rules {
  allow_recurring: boolean; allow_long_term: boolean; allow_employment: boolean; max_duration_months: number;
  min_notice_days_independent: number; min_notice_days_employment: number; commission_percent_independent: string; commission_percent_employment: string;
  commission_payer: "principal" | "worker"; max_advance_percent: number; late_grace_days: number; min_days_for_evaluation: number;
  evaluation_interval_days: number; evaluation_edit_days: number; source: string;
}

export interface Posting {
  id: number; title: string; category: { id: number; name: string }; mission_type: MissionType; work_relationship: Relationship; city: string;
  start_date: string | null; end_date: string | null; hours_per_week: string | null; amount: string | null; period: PayPeriod; currency: string; status: string;
  application_deadline: string | null; published_at: string | null; created_at: string; version: number; publisher: Person | null;
  organization: { id: number; name: string } | null; mine: boolean; applications_count: number | null;
  description?: string; conditions?: string; schedule?: ScheduleSlot[]; employment_notice_ack?: boolean; location_note?: string; legal_notice?: string;
  can_apply?: boolean; applied?: boolean;
}

export interface Interview { id: number; scheduled_at: string; duration_minutes: number; mode: string; place_note: string; status: string; note: string; proposed_by_me: boolean; created_at: string }

export interface Application {
  id: number; posting: number; posting_title: string; message: string; proposed_amount: string | null; available_from: string | null; status: string; decision_note: string;
  decided_at: string | null; created_at: string; mine: boolean; interviews: Interview[]; contract_id: number | null; applicant?: Person;
  experience?: { contracts_completed: number; contracts_active: number; months_total: number; distinct_principals: number; categories: string[]; evaluations: { count: number; average: number | null } };
}

export interface Amendment {
  id: number; kind: "change" | "suspend" | "end" | "cancel_notice" | "renewal"; changes: Record<string, unknown>; reason: string; effective_date: string; status: string;
  proposed_by: Person | null; proposed_by_role: string | null; mine: boolean; can_respond: boolean; can_withdraw: boolean; created_at: string; responded_at: string | null; applied_at: string | null;
}

export interface Contract {
  id: number; title: string; status: string; my_role: "principal" | "worker"; mission_type: MissionType; work_relationship: Relationship; category: { id: number; name: string };
  start_date: string; end_date: string | null; ends_on: string | null; is_indefinite: boolean; amount: string; period: PayPeriod; currency: string; payment_day: number | null;
  hours_per_week: string | null; worker: Person; principal: Person; counterpart: Person; organization: { id: number; name: string } | null; version: number; terms_version: number;
  terms_hash: string; accepted_by: string[]; actions: string[]; pending_amendment: Amendment | null; created_at: string; updated_at: string; activated_at: string | null;
  ended_at: string | null; closed_at: string | null;
}

export interface ContractDetail extends Contract {
  description: string; conditions: string; schedule: ScheduleSlot[]; location_city: string; location_address: string; auto_renew: boolean; renewal_term_months: number | null;
  renewal_count: number; non_renewal_at: string | null; non_renewal_deadline: string | null; proration_mode: string; overtime_hourly_rate: string | null; notice_period_days: number;
  bookings_mode: string; legal_notice_ack: boolean; end_reason: string; notice_given_by: Person | null; notice_given_at: string | null;
  suspensions: { starts_on: string; ends_on: string | null; reason: string; source: "agreed" | "admin" }[]; service_id: number | null; posting_id: number | null; rules: Rules; legal_notice: string;
}

export interface Evidence { name: string; url: string }
export interface Line { id: number; kind: string; amount: string; description: string; status: string; proposed_by_role: string | null; mine: boolean; can_respond: boolean; evidence: Evidence | null; created_at: string; responded_at: string | null }
export interface Payment {
  id: number; amount: string; method: string; reference: string; paid_on: string; is_advance: boolean; status: string; declared_by_role: string; mine: boolean; can_respond: boolean;
  rejection_reason: string; evidence: Evidence | null; declared_at: string; responded_at: string | null;
}
export interface Installment {
  id: number; contract: number; sequence: number; number: number; period_start: string; period_end: string; due_date: string; status: string; currency: string; base_amount: string | null;
  computed: boolean; adjustments: string; total: string; confirmed: string; declared: string; balance: string; remaining_to_declare: string; platform_fee: string; platform_fee_payer: string;
  platform_fee_status: string; note: string; closed_reason: string; can_waive: boolean; advance_remaining?: string | null; lines?: Line[]; payments?: Payment[];
}

export interface ScheduleEvent {
  id: number; kind: string; date: string; end_date: string | null; start_time: string | null; end_time: string | null; hours: string | null; status: string; source: string; note: string;
  requested_by_role: string | null; mine: boolean; can_respond: boolean; can_cancel: boolean; attendance_status: string; actual_start: string | null; actual_end: string | null;
  can_declare_attendance: boolean; can_confirm_attendance: boolean; replaces: number | null; replacement_worker: Person | null; replacement_status: string;
  can_answer_replacement: boolean; booking_id: number | null;
}
export interface ReplacementRow extends ScheduleEvent { contract_title: string; category: string; principal: Person; city: string }

export interface Evaluation {
  id: number; kind: "periodic" | "final"; period_key: string; rating: number; criteria: Record<string, number>; comment: string; reply: string; reply_at: string | null; author: Person;
  subject: Person; mine: boolean; about_me: boolean; editable: boolean; can_reply: boolean; is_hidden: boolean; created_at: string;
}
export interface Dispute { id: number; contract: number; installment: number | null; kind: string; reason: string; status: string; resolution: string; resolution_action: string; mine: boolean; created_at: string; resolved_at: string | null }
export interface HistoryEvent { id: number; type: string; actor: Person | null; data: Record<string, unknown>; at: string }

export interface TodoItem { kind: string; label: string; contract_id: number | null; title: string; at: string | null; installment_id?: number; event_id?: number; posting_id?: number; overdue?: boolean }
export interface Overview {
  counts: { pending_acceptance: number; active: number; suspended: number; notice: number }; todo_count: number; todo: TodoItem[]; organizations: { id: number; name: string }[]; postings_open: number; applications_active: number;
}

export interface Experience {
  source: string; contracts_completed: number; contracts_active: number; months_total: number; distinct_principals: number; categories: string[];
  evaluations: { count: number; average: number | null; min_public: number };
}

// ── Libellés ────────────────────────────────────────────────────────────────────────────────────────────────────────

export const MISSION_TYPE_FR: Record<MissionType, string> = { recurring: "Prestation récurrente", long_term: "Engagement de longue durée" };
export const RELATIONSHIP_FR: Record<Relationship, string> = { independent: "Prestation indépendante", employment: "Emploi salarié" };
export const PERIOD_FR: Record<PayPeriod, string> = { monthly: "par mois", hourly: "par heure", per_visit: "par intervention" };
export const PERIOD_LABEL: Record<PayPeriod, string> = { monthly: "Montant mensuel fixe", hourly: "Taux horaire", per_visit: "Prix par intervention" };
export const WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];
export const EVENT_KIND_FR: Record<string, string> = { shift: "Intervention", absence: "Absence", leave: "Congé", rest: "Repos", overtime: "Heures supplémentaires", replacement: "Remplacement" };
export const EVENT_STATUS_FR: Record<string, string> = { planned: "Prévue", requested: "À valider", approved: "Validée", rejected: "Refusée", cancelled: "Annulée", replaced: "Remplacée" };
export const ATTENDANCE_FR: Record<string, string> = { none: "À venir", declared: "Présence déclarée", confirmed: "Présence confirmée", disputed: "Présence contestée" };
export const LINE_KIND_FR: Record<string, string> = { bonus: "Prime", expense: "Remboursement de frais", deduction: "Retenue convenue", overtime: "Heures supplémentaires", correction: "Correction" };
export const PAYMENT_METHOD_FR: Record<string, string> = { cash: "Espèces", bank_transfer: "Virement", mobile_money: "Mobile Money", other: "Autre" };
export const AMENDMENT_KIND_FR: Record<string, string> = { change: "Modification des conditions", suspend: "Suspension", end: "Fin d’un commun accord", cancel_notice: "Annulation du préavis", renewal: "Renouvellement" };
export const DISPUTE_KIND_FR: Record<string, string> = { payment: "Paiement", conditions: "Conditions du contrat", conduct: "Comportement", planning: "Planning et présences", other: "Autre" };
export const INTERVIEW_MODE_FR: Record<string, string> = { phone: "Par téléphone", video: "En visioconférence", in_person: "En personne" };
export const ROLE_FR: Record<string, string> = { principal: "Donneur d’ordre", worker: "Prestataire" };
export const CONTRACT_EVENT_FR: Record<string, string> = {
  created: "Brouillon créé", proposed: "Contrat proposé", accepted: "Accepté", activated: "Contrat démarré", sent_back: "Modification demandée", cancelled: "Contrat annulé",
  amendment_proposed: "Avenant proposé", amendment_accepted: "Avenant accepté", amendment_rejected: "Avenant refusé", amendment_withdrawn: "Avenant retiré", amendment_applied: "Avenant en vigueur",
  suspended: "Contrat suspendu", resumed: "Contrat repris", resume_requested: "Reprise demandée", notice_given: "Préavis donné", non_renewal: "Non-renouvellement", renewed: "Contrat renouvelé",
  ended: "Contrat terminé", closed: "Contrat clôturé", admin_suspended: "Suspendu par Tratra", admin_resumed: "Repris par Tratra", admin_terminated: "Résilié par Tratra",
  payment_declared: "Paiement déclaré", payment_confirmed: "Paiement confirmé", payment_contested: "Paiement contesté", adjustment_proposed: "Ajustement proposé",
  adjustment_accepted: "Ajustement accepté", adjustment_rejected: "Ajustement refusé", installment_waived: "Solde abandonné", schedule_requested: "Demande de planning",
  schedule_approved: "Planning validé", schedule_rejected: "Planning refusé", schedule_cancelled: "Demande annulée", attendance_declared: "Présence déclarée",
  attendance_confirmed: "Présence confirmée", attendance_disputed: "Présence contestée", replacement_proposed: "Remplacement proposé", replacement_accepted: "Remplacement accepté",
  replacement_declined: "Remplacement refusé", evaluation_created: "Évaluation publiée", dispute_opened: "Litige ouvert", dispute_review: "Litige pris en charge", dispute_resolved: "Litige traité",
};

const money = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
/** « 150000.00 » → « 150 000 FCFA » (jamais de montant inventé : valeur absente → « — »). */
export function fcfa(value: string | number | null | undefined, currency = "XOF"): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${money.format(n)} ${currency === "XOF" ? "FCFA" : currency}`;
}

const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric" });
const DATE_SHORT = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short" });
/** Date « AAAA-MM-JJ » (sans fuseau) → « 4 janvier 2027 ». */
export function dateFr(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(`${value.slice(0, 10)}T12:00:00`);
  return Number.isNaN(d.getTime()) ? "—" : DATE.format(d);
}
export function dateShortFr(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(`${value.slice(0, 10)}T12:00:00`);
  return Number.isNaN(d.getTime()) ? "—" : DATE_SHORT.format(d);
}
export const timeFr = (value: string | null | undefined): string => (value ? value.slice(0, 5).replace(":", " h ") : "");
export function dateTimeFr(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : `${DATE.format(d)} à ${d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}`;
}

/** Durée lisible d'un contrat : « 12 mois », « durée indéterminée ». */
export function durationLabel(c: Pick<Contract, "start_date" | "end_date" | "is_indefinite">): string {
  if (c.is_indefinite || !c.end_date) return "Durée indéterminée";
  const a = new Date(`${c.start_date}T12:00:00`);
  const b = new Date(`${c.end_date}T12:00:00`);
  const days = Math.round((b.getTime() - a.getTime()) / 86400000) + 1;
  const months = Math.round(days / 30.4375);
  return months >= 2 ? `${months} mois` : `${days} jours`;
}

/** Résumé du planning : « Lun, mar, mer · 08 h 00 – 12 h 00 ». */
export function scheduleLabel(schedule: ScheduleSlot[] | undefined): string {
  if (!schedule || schedule.length === 0) return "Aucun planning fixe";
  const groups = new Map<string, number[]>();
  for (const s of schedule) groups.set(`${s.start}-${s.end}`, [...(groups.get(`${s.start}-${s.end}`) ?? []), s.weekday]);
  return Array.from(groups.entries())
    .map(([hours, days]) => `${days.sort((a, b) => a - b).map((d) => WEEKDAYS[d].slice(0, 3).toLowerCase()).join(", ")} · ${timeFr(hours.split("-")[0])} – ${timeFr(hours.split("-")[1])}`)
    .join(" ; ");
}

// ── Appels ──────────────────────────────────────────────────────────────────────────────────────────────────────────

const base = "/engagements";
const key = (scope: string) => `${scope}-${randomHex(10)}`;

export const eng = {
  get: <T>(path: string) => apiJson<T>(`${base}${path}`),
  /** Écriture : `idempotent` génère une clé UNIQUE par intention — réutilisez la même instance (via `useIntent`) pour rejouer sans doublon. */
  post: <T>(path: string, body?: unknown, idempotencyKey?: string) =>
    apiJson<T>(`${base}${path}`, { method: "POST", body: JSON.stringify(body ?? {}), headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined }),
  patch: <T>(path: string, body: unknown) => apiJson<T>(`${base}${path}`, { method: "PATCH", body: JSON.stringify(body) }),
  /** Envoi avec pièce jointe (justificatif privé) : multipart, mêmes garanties d'idempotence. */
  form: <T>(path: string, fields: Record<string, string>, file: File | null, idempotencyKey?: string) => {
    const f = new FormData();
    for (const [k, v] of Object.entries(fields)) if (v !== "") f.set(k, v);
    if (file) f.set("evidence", file);
    return upload<T>(`${base}${path}`, f, true, idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {});
  },
  newKey: key,
};

/** Erreurs métier typées du serveur : `{code, detail, fields?}`. */
export function errCode(e: unknown): string | null {
  const data = e instanceof ApiError ? (e.data as { code?: unknown } | null) : null;
  return data && typeof data.code === "string" ? data.code : null;
}
export function errFields(e: unknown): Record<string, string> {
  if (!(e instanceof ApiError) || !e.data || typeof e.data !== "object") return {};
  const fields = (e.data as { fields?: Record<string, unknown> }).fields;
  if (!fields || typeof fields !== "object") return {};
  return Object.fromEntries(Object.entries(fields).map(([k, v]) => [k, Array.isArray(v) ? String(v[0]) : String(v)]));
}
export const isConflictVersion = (e: unknown): boolean => e instanceof ApiError && e.status === 409 && errCode(e) === "version_conflict";
