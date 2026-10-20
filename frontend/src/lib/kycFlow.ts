/**
 * « Vérifier mon identité » (web), mêmes API et mêmes contrôles que l'application (handy/kyc_flow.py) :
 *   GET/PATCH /me/kyc/ · POST /me/kyc/capture/ (side, file) · POST /me/kyc/send/ · POST /me/kyc/restart/.
 * Mode accompagné : la pièce d'abord (CNI ou passeport), photos guidées avec contrôle qualité, informations PRÉREMPLIES par la lecture du
 * recto puis confirmées, envoi, suivi de la revue humaine. Logique pure testée par `npm run test:bo`.
 */

export interface KycProblem {
  code: string;
  label: string;
  blocking: boolean;
}

export interface KycCapture {
  side: "front" | "back";
  label: string;
  present: boolean;
  quality: "ok" | "warn" | "fail" | null;
  problems: KycProblem[];
  reading: { status: string; notes: string[] } | null;
}

export interface KycFlowState {
  status: "draft" | "in_review" | "changes_requested" | "verified";
  status_label: string;
  current_step: string;
  steps: { key: string; label: string; state: string }[];
  personal: { first_name: string; last_name: string; birth_date: string | null; complete: boolean };
  document: {
    kind: "cni" | "passport" | null;
    kinds: { value: "cni" | "passport"; label: string; sides: number }[];
    captures: KycCapture[];
    ready_to_send: boolean;
  };
  review: { state: "none" | "pending" | "rejected" | "approved"; reason: string; sent_at: string | null; attempts: number; previous_reason: string | null };
  editable: boolean;
  /** Réponse à une photo du recto : nom, prénoms, date de naissance LUS sur la pièce (proposés, jamais enregistrés sans confirmation). */
  suggestions?: { first_name?: string; last_name?: string; birth_date?: string };
  check?: { quality: string };
}

export type GuidedKycView = "document" | "capture" | "personal" | "send" | "review" | "verified";

/** Écran du mode accompagné : la pièce d'abord, puis les informations (préremplies), puis l'envoi ; ensuite le suivi de la revue. */
export function guidedKycView(s: KycFlowState): GuidedKycView {
  if (s.review.state === "approved" || s.status === "verified") return "verified";
  if (!s.editable || s.review.state === "pending") return "review";
  if (!s.document.kind) return "document";
  const captures = s.document.captures;
  if (!captures.length || captures.some((c) => !c.present || c.quality === "fail")) return "capture";
  if (!s.personal.complete) return "personal";
  return "send";
}

/** Une photo à reprendre (refusée par l'équipe, illisible) bloque l'envoi ; un défaut léger est seulement signalé. */
export function captureVerdict(c: KycCapture): { tone: "success" | "warning" | "danger" | "neutral"; text: string } {
  if (!c.present) return { tone: "neutral", text: "Photo à prendre" };
  if (c.quality === "fail") return { tone: "danger", text: `À reprendre : ${c.problems.filter((p) => p.blocking).map((p) => p.label).join(" ") || "photo inexploitable."}` };
  if (c.quality === "warn") return { tone: "warning", text: `Acceptée, mais : ${c.problems.map((p) => p.label).join(" ")}` };
  return { tone: "success", text: "Photo nette et lisible" };
}

/** Préremplissage proposé : uniquement les champs encore vides ou différents, l'utilisateur confirme toujours lui-même. */
export function prefill(
  current: { first_name: string; last_name: string; birth_date: string },
  read: KycFlowState["suggestions"],
): { values: { first_name: string; last_name: string; birth_date: string }; filled: boolean } {
  if (!read) return { values: current, filled: false };
  const values = {
    first_name: read.first_name || current.first_name,
    last_name: read.last_name || current.last_name,
    birth_date: read.birth_date && /^\d{4}-\d{2}-\d{2}$/.test(read.birth_date) ? read.birth_date : current.birth_date,
  };
  const filled = values.first_name !== current.first_name || values.last_name !== current.last_name || values.birth_date !== current.birth_date;
  return { values, filled };
}

export const CAPTURE_TIPS = "Posez la pièce à plat, bien éclairée, sans reflet ni flash. Les quatre coins doivent être visibles et le texte lisible.";
