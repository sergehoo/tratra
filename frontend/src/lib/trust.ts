/** Tratra Trust : types de l'API (passeport public, « Ma réputation ») et libellés des badges. */

export type BadgeCode = "NOUVEAU" | "VERIFIE" | "EXPERT" | "SUR";
export type DataSource = "vérifié" | "plateforme" | "déclaré";

export interface PublicBadge {
  code: BadgeCode;
  label: string;
}

/** Libellés et explications des badges (mêmes règles que le backend : trust/engine.py). */
export const BADGE_INFO: Record<BadgeCode, { label: string; help: string }> = {
  NOUVEAU: { label: "Nouveau", help: "Profil créé, identité pas encore vérifiée." },
  VERIFIE: { label: "Vérifié", help: "Pièce d'identité contrôlée par l'équipe Tratra et profil complet." },
  EXPERT: { label: "Expert", help: "Expertise démontrée : justificatifs professionnels approuvés et résultats atteints." },
  SUR: { label: "Sûr", help: "Fiabilité mesurée : ponctualité, absence de litiges et avis des clients." },
};

export const SOURCE_LABEL: Record<DataSource, string> = {
  vérifié: "Vérifié par Tratra",
  plateforme: "Mesuré sur Tratra",
  déclaré: "Déclaré par l'artisan",
};

export interface ScoreComponent {
  key: string;
  label: string;
  weight: number;
  available: boolean;
  ratio: number | null;
  detail: string;
  source: DataSource;
  points: number | null;
  max_points: number | null;
}

export interface Criterion {
  key: string;
  label: string;
  current: number | null;
  required: number;
  met: boolean;
  source: DataSource;
  unit: string;
  higher_better: boolean;
}

export interface Certification {
  id: number;
  title: string;
  category: { id: number; name: string } | null;
  issuer: string;
  issued_on: string | null;
  expires_on: string | null;
  source: DataSource;
}

export interface HistoryRow {
  code: BadgeCode;
  label: string;
  started_at: string;
  ended_at: string | null;
  start_reason?: string;
  end_reason?: string;
}

export interface ReviewStats {
  count: number;
  average: number | null;
  criteria: Record<string, { average: number | null; count: number }>;
  distribution: Record<string, number>;
  replied: number;
  response_rate: number | null;
}

export interface Passport {
  profile_id: number;
  user_id: number;
  display_name: string;
  photo: string | null;
  commune: string | null;
  member_since: string;
  evaluated_at: string | null;
  identity: { verified: boolean; verified_on: string | null; source: DataSource };
  badges: { code: BadgeCode; label: string; since: string }[];
  score: {
    value: number | null;
    confidence: "faible" | "moyenne" | "élevée" | null;
    reason: string;
    note: string;
    components: ScoreComponent[];
  };
  skills: {
    declared: { id: number; name: string; slug: string; source: DataSource }[];
    certified: Certification[];
  };
  experience: { years: number; source: DataSource };
  missions: { completed: number; completed_window: number; window_days: number; source: DataSource };
  satisfaction: ReviewStats & { source: DataSource };
  punctuality: { rate: number | null; sample: number; on_time: number; tolerance_minutes: number; min_sample: number; source: DataSource };
  reactivity: { median_minutes: number | null; sample: number; min_sample: number; source: DataSource };
  disputes: { rate: number | null; source: DataSource };
  history: HistoryRow[];
  sources: Record<DataSource, string>;
}

export interface OwnerTrust extends Passport {
  next_badges: Record<"EXPERT" | "SUR", { label: string; earned: boolean; requires_verified: boolean; criteria: Criterion[] }>;
  checklist: { key: string; label: string; hint: string; done: boolean }[];
  pending_certifications: { id: number; title: string; status: string; uploaded_at: string }[];
}

/** « 4,5 » / « 92 % » / « 12 min » — formats d'affichage des mesures. */
export function formatPercent(ratio: number | null | undefined): string {
  return ratio == null ? "—" : `${Math.round(ratio * 100)} %`;
}

export function formatMinutes(minutes: number | null | undefined): string {
  if (minutes == null) return "—";
  if (minutes < 1) return "< 1 min";
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return m ? `${h} h ${String(m).padStart(2, "0")}` : `${h} h`;
}

export function formatCriterion(c: Criterion): string {
  const fmt = (v: number | null) => {
    if (v == null) return "—";
    if (c.unit === "%") return `${Math.round(v * 100)} %`;
    return `${String(v).replace(".", ",")}${c.unit ? ` ${c.unit}` : ""}`;
  };
  return `${fmt(c.current)} · ${c.higher_better ? "minimum" : "maximum"} ${fmt(c.required)}`;
}
