// Vérification d'identité guidée (web) : même ordre et mêmes contrôles que l'application. `npm run test:bo` (node --test).
import assert from "node:assert/strict";
import { test } from "node:test";
import { captureVerdict, guidedKycView, prefill, type KycCapture, type KycFlowState } from "./kycFlow.ts";

const side = (s: "front" | "back", extra: Partial<KycCapture> = {}): KycCapture =>
  ({ side: s, label: s === "front" ? "Recto" : "Verso", present: false, quality: null, problems: [], reading: null, ...extra });

const state = (over: Partial<KycFlowState> & { kind?: "cni" | "passport" | null; captures?: KycCapture[]; complete?: boolean } = {}): KycFlowState => ({
  status: "draft", status_label: "À compléter", current_step: "personal", steps: [],
  personal: { first_name: "", last_name: "", birth_date: null, complete: over.complete ?? false },
  document: { kind: over.kind ?? null, kinds: [], captures: over.captures ?? [], ready_to_send: false },
  review: { state: "none", reason: "", sent_at: null, attempts: 0, previous_reason: null },
  editable: true,
  ...over,
});

test("mode accompagné : la pièce d'abord, les photos, puis les informations, l'envoi et le suivi", () => {
  assert.equal(guidedKycView(state()), "document");
  assert.equal(guidedKycView(state({ kind: "cni", captures: [side("front"), side("back")] })), "capture");
  assert.equal(guidedKycView(state({ kind: "cni", captures: [side("front", { present: true, quality: "ok" }), side("back")] })), "capture");
  assert.equal(guidedKycView(state({ kind: "passport", captures: [side("front", { present: true, quality: "fail" })] })), "capture", "photo à reprendre");
  assert.equal(guidedKycView(state({ kind: "passport", captures: [side("front", { present: true, quality: "warn" })] })), "personal");
  assert.equal(guidedKycView(state({ kind: "passport", captures: [side("front", { present: true, quality: "ok" })], complete: true })), "send");
  assert.equal(guidedKycView(state({ editable: false, status: "in_review", review: { state: "pending", reason: "", sent_at: "2026-10-20T10:00:00Z", attempts: 1, previous_reason: null } })), "review");
  assert.equal(guidedKycView(state({ status: "verified", editable: false, review: { state: "approved", reason: "", sent_at: null, attempts: 1, previous_reason: null } })), "verified");
  const rejected = state({ kind: "cni", captures: [side("front"), side("back")], complete: true, status: "changes_requested",
    review: { state: "rejected", reason: "Photo floue", sent_at: "2026-10-20T10:00:00Z", attempts: 1, previous_reason: null } });
  assert.equal(guidedKycView(rejected), "capture", "nouvelle pièce demandée : on reprend les photos");
});

test("contrôle qualité expliqué : bloquant à reprendre, léger signalé", () => {
  assert.equal(captureVerdict(side("front")).tone, "neutral");
  assert.equal(captureVerdict(side("front", { present: true, quality: "ok" })).tone, "success");
  const warn = captureVerdict(side("front", { present: true, quality: "warn", problems: [{ code: "dark", label: "Photo un peu sombre.", blocking: false }] }));
  assert.equal(warn.tone, "warning");
  assert.match(warn.text, /un peu sombre/);
  const fail = captureVerdict(side("front", { present: true, quality: "fail", problems: [{ code: "blurry", label: "Photo floue.", blocking: true }] }));
  assert.deepEqual(fail, { tone: "danger", text: "À reprendre : Photo floue." });
});

test("lecture de la pièce : préremplissage proposé, à confirmer", () => {
  const empty = { first_name: "", last_name: "", birth_date: "" };
  assert.deepEqual(prefill(empty, { first_name: "Awa Marie", last_name: "KONE", birth_date: "1990-04-12" }),
    { values: { first_name: "Awa Marie", last_name: "KONE", birth_date: "1990-04-12" }, filled: true });
  assert.deepEqual(prefill(empty, {}), { values: empty, filled: false });
  assert.equal(prefill(empty, { birth_date: "12/04/1990" }).values.birth_date, "", "date illisible : jamais proposée");
  assert.equal(prefill({ ...empty, first_name: "Awa" }, undefined).filled, false);
});
