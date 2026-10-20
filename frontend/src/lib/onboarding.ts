/**
 * « Inscription accompagnée » côté web : mêmes données et mêmes règles que l'application (handy/onboarding.py).
 * Logique pure (ordre des écrans, reprise, prochaine action → page) : testée par `npm run test:bo`.
 */

export const GUIDED_PATH = "/dashboard/provide/guided";

export interface OnbOption {
  value: string;
  label: string;
  emoji?: string;
  phrase?: string;
  years?: number;
  amount?: number;
  unit?: string;
}

export interface OnbQuestion {
  key: string;
  text: string;
  help: string;
  kind: "single" | "multi";
  target: string;
  required: boolean;
  options: OnbOption[];
}

export interface OnbConfig {
  trade: { id: number; name: string };
  prestations: { id: number; name: string }[];
  questions: OnbQuestion[];
  communes: string[];
}

export type OnbAnswers = Record<string, string | string[]>;

export interface OnbDraft {
  trade: number | null;
  prestations: number[];
  commune: string;
  quartier: string;
  answers: OnbAnswers;
  step: string;
}

export interface OnbStep {
  key: string;
  label: string;
  state: "done" | "waiting" | "todo";
}

/** Réponse de `GET/PUT /me/onboarding/` et de `POST /me/onboarding/apply/`. */
export interface OnbState {
  path: string;
  trade: { id: number; name: string } | null;
  prestations: number[];
  commune: string;
  quartier: string;
  answers: OnbAnswers;
  step: string;
  offer: { title: string; description: string; price_type: string; price: number | null } | null;
  service_id: number | null;
  steps: OnbStep[];
  done: number;
  total: number;
  next_action: { code: string; label: string; step: string | null };
  published: boolean;
}

export const emptyDraft = (): OnbDraft => ({ trade: null, prestations: [], commune: "", quartier: "", answers: {}, step: "" });

export function draftFromState(s: OnbState | null): OnbDraft {
  if (!s || !s.trade) return emptyDraft();
  return { trade: s.trade.id, prestations: s.prestations ?? [], commune: s.commune ?? "", quartier: s.quartier ?? "", answers: s.answers ?? {}, step: s.step ?? "" };
}

/** Ordre complet des écrans ; le code SMS n'y figure que s'il reste à faire (le compte existe déjà sur le web). */
export function stepsFor(config: OnbConfig | null, opts: { verify: boolean }): string[] {
  return [
    "intro",
    "trade",
    ...(config && config.prestations.length ? ["prestations"] : []),
    "commune",
    "quartier",
    ...(config?.questions ?? []).map((q) => `q:${q.key}`),
    "preview",
    ...(opts.verify ? ["verify"] : []),
    "photo",
    "identity",
    "done",
  ];
}

const ALIASES: Record<string, (config: OnbConfig | null) => string> = {
  zone: () => "commune",
  questions: (c) => (c && c.questions.length ? `q:${c.questions[0].key}` : "preview"),
  phone: () => "verify",
  offer: () => "preview",
  account: () => "preview",
};

/** Écran de reprise : celui demandé (ou enregistré), sinon le suivant encore à faire, sinon le début. */
export function resumeStep(config: OnbConfig | null, wanted: string | null | undefined, opts: { verify: boolean }): string {
  const steps = stepsFor(config, opts);
  if (!wanted) return steps[0];
  const target = ALIASES[wanted]?.(config) ?? wanted;
  const all = stepsFor(config, { verify: true });
  const i = all.indexOf(target);
  if (i < 0) return steps[0];
  return all.slice(i).find((s) => steps.includes(s)) ?? steps[0];
}

/** Écran suivant : le premier, dans l'ordre complet, encore à faire. */
export function nextStep(config: OnbConfig | null, current: string, opts: { verify: boolean }): string {
  const steps = stepsFor(config, opts);
  const all = stepsFor(config, { verify: true });
  return all.slice(all.indexOf(current) + 1).find((s) => steps.includes(s)) ?? steps[steps.length - 1];
}

export function previousStep(config: OnbConfig | null, current: string, opts: { verify: boolean }): string | null {
  const steps = stepsFor(config, opts);
  const i = steps.indexOf(current);
  return i > 0 ? steps[i - 1] : null;
}

/** Une réponse est-elle donnée (les questions facultatives peuvent rester vides) ? */
export function answered(q: OnbQuestion, answers: OnbAnswers): boolean {
  const a = answers[q.key];
  if (!q.required) return true;
  return q.kind === "multi" ? Array.isArray(a) && a.length > 0 : typeof a === "string" && a !== "";
}

export function toggleAnswer(q: OnbQuestion, answers: OnbAnswers, value: string): OnbAnswers {
  if (q.kind !== "multi") return { ...answers, [q.key]: value };
  const list = Array.isArray(answers[q.key]) ? [...(answers[q.key] as string[])] : [];
  return { ...answers, [q.key]: list.includes(value) ? list.filter((v) => v !== value) : [...list, value] };
}

/** « Continuer » du tableau de bord débutant : la page de la prochaine action calculée par le serveur. */
export function nextActionHref(action: OnbState["next_action"]): string {
  switch (action.code) {
    case "verify_phone":
      return `/verify-phone?next=${encodeURIComponent(`${GUIDED_PATH}?step=photo`)}`;
    case "verify_identity":
      return "/dashboard/profile/kyc";
    case "wait":
    case "done":
      return "/dashboard/provider";
    default:
      return action.step ? `${GUIDED_PATH}?step=${encodeURIComponent(action.step)}` : GUIDED_PATH;
  }
}

/** Fin du parcours : ce qui reste vraiment à faire d'après le serveur (jamais « c'est fini » si la pièce n'a pas été envoyée). */
export function remainingAtEnd(state: OnbState | null): string[] {
  const todo: Record<string, string> = { phone: "confirmer votre numéro", photo: "ajouter votre photo", identity: "faire vérifier votre pièce d’identité" };
  return (state?.steps ?? []).filter((s) => s.state === "todo" && todo[s.key]).map((s) => todo[s.key]);
}
