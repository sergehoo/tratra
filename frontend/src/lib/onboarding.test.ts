// Inscription accompagnée (web) : ordre des écrans, reprise, prochaine action. `npm run test:bo` (node --test, sans dépendance).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  GUIDED_PATH, JOURNEY, PENDING_MAX_AGE_MS, answered, declaredExperience, draftFromState, journeyOf, keepPending, minimumFor, nextActionHref,
  nextStep, previousStep, progressOf, remainingAtEnd, resumeStep, stepsFor, takePending, toggleAnswer,
  type OnbConfig, type OnbQuestion, type OnbState, type Vault,
} from "./onboarding.ts";

const experience: OnbQuestion = { key: "experience", text: "Depuis combien de temps ?", help: "", kind: "single", target: "experience", required: true,
  options: [{ value: "1", label: "Moins d’un an" }, { value: "4", label: "3 à 5 ans" }] };
const days: OnbQuestion = { key: "days", text: "Quels jours ?", help: "", kind: "multi", target: "days", required: true,
  options: [{ value: "monday", label: "Lundi" }, { value: "saturday", label: "Samedi" }] };
const config: OnbConfig = { trade: { id: 12, name: "Nounou" }, prestations: [{ id: 121, name: "Garde d’enfants" }], questions: [experience, days], communes: ["Cocody"] };

test("les écrans suivent le métier : prestations et questions ajoutées, code SMS seulement s'il reste à faire", () => {
  assert.deepEqual(stepsFor(null, { verify: false }), ["intro", "trade", "commune", "quartier", "preview", "photo", "identity", "done"]);
  assert.deepEqual(stepsFor(config, { verify: true }),
    ["intro", "trade", "prestations", "commune", "quartier", "q:experience", "q:days", "preview", "verify", "photo", "identity", "done"]);
});

test("après le métier vient l'écran des prestations (la liste s'allonge une fois le métier connu)", () => {
  assert.equal(nextStep(config, "trade", { verify: false }), "prestations");
  assert.equal(nextStep(config, "quartier", { verify: false }), "q:experience");
  assert.equal(nextStep(config, "preview", { verify: true }), "verify");
  assert.equal(nextStep(config, "preview", { verify: false }), "photo", "numéro déjà vérifié : pas d'écran de code");
  assert.equal(nextStep(config, "verify", { verify: false }), "photo", "code validé ailleurs : on avance");
  assert.equal(previousStep(config, "q:experience", { verify: false }), "quartier");
  assert.equal(previousStep(config, "intro", { verify: false }), null);
});

test("reprise à l'écran enregistré ou à la prochaine action du serveur", () => {
  assert.equal(resumeStep(config, "q:days", { verify: false }), "q:days");
  assert.equal(resumeStep(config, "zone", { verify: false }), "commune");
  assert.equal(resumeStep(config, "questions", { verify: false }), "q:experience");
  assert.equal(resumeStep(config, "offer", { verify: false }), "preview");
  assert.equal(resumeStep(config, "phone", { verify: false }), "photo", "numéro vérifié entre-temps");
  assert.equal(resumeStep(config, "inconnu", { verify: false }), "intro");
  assert.equal(resumeStep(null, "", { verify: false }), "intro");
});

test("réponses : obligatoires, choix unique ou multiple", () => {
  assert.equal(answered(experience, {}), false);
  let a = toggleAnswer(experience, {}, "1");
  assert.equal(answered(experience, a), true);
  a = toggleAnswer(days, a, "monday");
  a = toggleAnswer(days, a, "saturday");
  a = toggleAnswer(days, a, "monday");
  assert.deepEqual(a, { experience: "1", days: ["saturday"] });
  assert.equal(answered({ ...days, required: false }, {}), true);
});

const state = (over: Partial<OnbState> = {}): OnbState => ({
  path: "guided", trade: { id: 12, name: "Nounou" }, prestations: [121], commune: "Cocody", quartier: "", answers: { experience: "1" }, step: "preview",
  offer: null, service_id: null, done: 5, total: 9, published: false, next_action: { code: "apply", label: "Créer mon annonce", step: "offer" },
  steps: [
    { key: "phone", label: "Votre téléphone", state: "done" },
    { key: "photo", label: "Votre photo", state: "todo" },
    { key: "identity", label: "Votre identité", state: "todo" },
  ],
  ...over,
});

test("« Continuer » du tableau de bord ouvre la page de la prochaine action", () => {
  assert.equal(nextActionHref({ code: "resume", label: "", step: "questions" }), `${GUIDED_PATH}?step=questions`);
  assert.equal(nextActionHref({ code: "apply", label: "", step: "offer" }), `${GUIDED_PATH}?step=offer`);
  assert.equal(nextActionHref({ code: "photo", label: "", step: "photo" }), `${GUIDED_PATH}?step=photo`);
  assert.equal(nextActionHref({ code: "verify_identity", label: "", step: "identity" }), `${GUIDED_PATH}?step=identity`);
  assert.equal(nextActionHref({ code: "wait", label: "", step: "identity" }), "/dashboard/provider");
  assert.equal(nextActionHref({ code: "blocked", label: "", step: "approval" }), "/dashboard/provider");
  assert.ok(nextActionHref({ code: "verify_phone", label: "", step: "phone" }).startsWith("/verify-phone?next=%2Fdashboard%2Fprovide%2Fguided"));
});

test("fin honnête : ce qui reste vient du serveur ; brouillon repris du serveur", () => {
  assert.deepEqual(remainingAtEnd(state()), ["ajouter votre photo", "faire vérifier votre pièce d’identité"]);
  assert.deepEqual(remainingAtEnd(state({ steps: [{ key: "identity", label: "", state: "waiting" }] })), []);
  assert.deepEqual(draftFromState(state()), { trade: 12, prestations: [121], commune: "Cocody", quartier: "", answers: { experience: "1" }, step: "preview" });
  assert.equal(draftFromState(state({ trade: null })).trade, null);
});

test("mêmes 9 étapes que Django (handy/onboarding.py) et même table écran → étape que l'application", () => {
  const python = readFileSync(new URL("../../../handy/onboarding.py", import.meta.url), "utf8");
  const block = python.slice(python.indexOf("JOURNEY = ["), python.indexOf("]", python.indexOf("JOURNEY = [")));
  const fromDjango = [...block.matchAll(/\("(\w+)", "([^"]+)"\)/g)].map((m) => ({ key: m[1], label: m[2] }));
  assert.deepEqual(JOURNEY, fromDjango);
  const table: Record<string, string> = {
    intro: "trade", trade: "trade", prestations: "trade", commune: "zone", quartier: "zone", "q:experience": "questions", preview: "questions",
    names: "account", phone: "account", password: "account", verify: "phone", photo: "photo", identity: "identity", done: "approval",
  };
  for (const [screen, step] of Object.entries(table)) assert.equal(journeyOf(screen), step, screen);
});

test("progression affichée : « Étape x sur 9 » et l'avancement des questions", () => {
  const screens = stepsFor(config, { verify: false });
  assert.equal(progressOf(screens, "intro").title, "Étape 1 sur 9 · Votre métier");
  assert.equal(progressOf(screens, "q:days").title, "Étape 3 sur 9 · Vos réponses (2/2)");
  assert.equal(progressOf(screens, "identity").title, "Étape 8 sur 9 · Votre identité");
  assert.ok(progressOf(screens, "trade").ratio < progressOf(screens, "commune").ratio);
  assert.equal(progressOf(screens, "done").ratio, 1);
});

test("expérience : déclaration exacte (borne basse) et minimum du métier ou d'une prestation choisie", () => {
  const exp: OnbQuestion = { ...experience, options: [{ value: "1", label: "Moins d’un an", years: 0 }, { value: "4", label: "3 à 5 ans", years: 3 }] };
  const withMin: OnbConfig = {
    ...config, questions: [exp], trade: { id: 12, name: "Nounou", min_experience_years: 1 },
    prestations: [{ id: 121, name: "Garde de nuit", min_experience_years: 3 }, { id: 122, name: "Sortie d’école" }],
  };
  assert.deepEqual(declaredExperience(withMin, { experience: "1" }), { years: 0, label: "Moins d’un an" });
  assert.deepEqual(declaredExperience(withMin, { experience: "4" }), { years: 3, label: "3 à 5 ans" });
  assert.equal(declaredExperience(withMin, {}), null);
  assert.deepEqual(minimumFor(withMin, [122]), { years: 1, name: "Nounou" });
  assert.deepEqual(minimumFor(withMin, [121, 122]), { years: 3, name: "Garde de nuit" });
  assert.deepEqual(minimumFor(config, []), { years: 0, name: "" });
});

/** Coffre en mémoire, cloisonné par compte comme src/lib/localVault.ts. */
function memoryVault(): Vault & { keys: () => string[] } {
  const data = new Map<string, string>();
  return {
    read: <T,>(u: number | string, n: string) => (data.has(`${u}:${n}`) ? (JSON.parse(data.get(`${u}:${n}`)!) as T) : null),
    write: (u, n, v) => void data.set(`${u}:${n}`, JSON.stringify(v)),
    del: (u, n) => void data.delete(`${u}:${n}`),
    keys: () => [...data.keys()],
  };
}

test("brouillon gardé hors ligne : rattaché à son compte, jamais lu par un autre, effacé s'il est périmé", () => {
  const vault = memoryVault();
  const d = { trade: 12, prestations: [121], commune: "Cocody", quartier: "", answers: { experience: "1" }, step: "q:days" };
  keepPending(vault, 9, d, 1000);
  assert.equal(takePending(vault, 10, 2000), null, "autre compte : rien");
  assert.deepEqual(takePending(vault, 9, 2000), d);
  keepPending(vault, 9, d, 0);
  assert.equal(takePending(vault, 9, PENDING_MAX_AGE_MS + 1), null);
  assert.deepEqual(vault.keys(), [], "périmé : effacé");
});

