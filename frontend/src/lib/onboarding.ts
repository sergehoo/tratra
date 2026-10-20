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
  trade: { id: number; name: string; min_experience_years?: number };
  prestations: { id: number; name: string; min_experience_years?: number }[];
  questions: OnbQuestion[];
  communes: string[];
  journey?: { key: string; label: string }[];
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
  /** Expérience déclarée (exacte) face au minimum des métiers exercés ; `ok: false` = publication bloquée par la règle. */
  experience?: { declared: string; years: number | null; minimum: number; trade: string; ok: boolean };
}

/** Les 9 étapes communes à l'application, au site et à Django (handy/onboarding.py JOURNEY) : même progression partout. */
export const JOURNEY: { key: string; label: string }[] = [
  { key: "trade", label: "Votre métier" },
  { key: "zone", label: "Votre quartier" },
  { key: "questions", label: "Vos réponses" },
  { key: "account", label: "Votre compte" },
  { key: "phone", label: "Votre téléphone" },
  { key: "offer", label: "Votre annonce" },
  { key: "photo", label: "Votre photo" },
  { key: "identity", label: "Votre identité" },
  { key: "approval", label: "Validation par l’équipe Tratra" },
];

/** Étape commune d'un écran du parcours (même table que l'application : lib/onboarding/onboarding_api.dart `journeyOf`). */
export function journeyOf(screen: string): string {
  if (screen.startsWith("q:")) return "questions";
  const table: Record<string, string> = {
    intro: "trade", trade: "trade", prestations: "trade", commune: "zone", quartier: "zone", preview: "questions",
    names: "account", phone: "account", password: "account", verify: "phone", photo: "photo", identity: "identity",
  };
  return table[screen] ?? "approval";
}

/** Libellé et avancement affichés : « Étape 3 sur 9 · Vos réponses (2/5) » et une barre continue. */
export function progressOf(screens: string[], screen: string): { title: string; ratio: number } {
  const key = journeyOf(screen);
  const i = Math.max(0, JOURNEY.findIndex((j) => j.key === key));
  const group = screens.filter((s) => journeyOf(s) === key);
  const within = group.length ? Math.max(1, group.indexOf(screen) + 1) / group.length : 1;
  const questions = screens.filter((s) => s.startsWith("q:"));
  const count = screen.startsWith("q:") ? ` (${questions.indexOf(screen) + 1}/${questions.length})` : "";
  return { title: `Étape ${i + 1} sur ${JOURNEY.length} · ${JOURNEY[i].label}${count}`, ratio: Math.min(1, (i + within) / JOURNEY.length) };
}

/** Minimum d'expérience du métier et des prestations choisies (même règle que handy/eligibility.py) : années et nom concerné. */
export function minimumFor(config: OnbConfig | null, prestations: number[]): { years: number; name: string } {
  let best = { years: config?.trade.min_experience_years ?? 0, name: config?.trade.min_experience_years ? config.trade.name : "" };
  for (const p of config?.prestations ?? []) {
    if (prestations.includes(p.id) && (p.min_experience_years ?? 0) > best.years) best = { years: p.min_experience_years ?? 0, name: p.name };
  }
  return best;
}

/** Expérience déclarée : libellé EXACT choisi et années = borne basse de la tranche (jamais arrondies vers le haut). */
export function declaredExperience(config: OnbConfig | null, answers: OnbAnswers): { years: number; label: string } | null {
  for (const q of config?.questions ?? []) {
    if (q.target !== "experience") continue;
    const o = q.options.find((x) => answers[q.key] === x.value);
    if (o) return { years: o.years ?? (/^\d+$/.test(o.value) ? Number(o.value) : 0), label: o.label };
  }
  return null;
}

// ------------------------------------------------------------------ brouillon gardé sur l'appareil (réseau coupé, session expirée)

/** Coffre local cloisonné par compte (src/lib/localVault.ts : effacé à la déconnexion volontaire, gardé si la session expire). */
export interface Vault {
  read: <T>(userId: number | string, name: string) => T | null;
  write: (userId: number | string, name: string, value: unknown) => void;
  del: (userId: number | string, name: string) => void;
}

export const PENDING_NAME = "onboarding";
export const PENDING_MAX_AGE_MS = 30 * 24 * 3600 * 1000;

/** Réponses non envoyées : rattachées au compte qui les a données, jamais lues par un autre. */
export function keepPending(vault: Vault, userId: number | string, draft: OnbDraft, now = Date.now()): void {
  vault.write(userId, PENDING_NAME, { draft, savedAt: now });
}

/** Réponses gardées pour CE compte (plus récentes que le serveur : elles n'existent que si un envoi a échoué). Périmées → effacées. */
export function takePending(vault: Vault, userId: number | string, now = Date.now()): OnbDraft | null {
  const kept = vault.read<{ draft: OnbDraft; savedAt: number }>(userId, PENDING_NAME);
  if (!kept?.draft || typeof kept.savedAt !== "number") return null;
  if (now - kept.savedAt > PENDING_MAX_AGE_MS || !kept.draft.trade) {
    vault.del(userId, PENDING_NAME);
    return null;
  }
  return kept.draft;
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
      return `${GUIDED_PATH}?step=identity`;          // même vérification guidée que l'application (pièce, photos, lecture, revue)
    case "wait":
    case "done":
    case "blocked":
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
