// Accueil : carte du profil professionnel d'après les statuts réels du serveur. `npm run test:bo` (node --test).
import assert from "node:assert/strict";
import { test } from "node:test";
import { actionHref, isVerified, proHomeState, showsProgress, type EligibilityLike } from "./proStatus.ts";

const elig = (o: { authorized?: boolean; complete?: boolean; kyc?: string; reason?: string | null; offers?: number;
  blockers?: EligibilityLike["publication"]["blockers"] } = {}): EligibilityLike => ({
  profile: { complete: o.complete ?? true },
  kyc: { status: o.kyc ?? "approved", reason: o.reason ?? null },
  publication: { authorized: o.authorized ?? false, blockers: o.blockers ?? [] },
  offers: { total: o.offers ?? 1 },
});
const none = { publishable: false, servicesTotal: 0 };

test("vérifié = publication autorisée par le serveur : plus de carte, badge ; sans prestation : « Créer ma première prestation »", () => {
  const v = proHomeState(elig({ authorized: true }), none);
  assert.equal(v.kind, "verified");
  assert.ok(isVerified(v) && !showsProgress(v));
  const first = proHomeState(elig({ authorized: true, offers: 0 }), none);
  assert.equal(first.kind, "firstOffer");
  assert.equal(first.action?.label, "Créer ma première prestation");
  assert.equal(actionHref(first.action!.code), "/dashboard/provider/services/new");
});

test("7/7 sans autorisation : jamais « vérifié » (la validation n'est pas déduite de la liste de contrôle)", () => {
  const s = proHomeState(elig({ blockers: [{ code: "experience_minimum", label: "Expérience minimale non atteinte", hint: "…",
    action: { code: "edit_profile", label: "Compléter mon profil" } }] }), { publishable: false, servicesTotal: 1 });
  assert.equal(s.kind, "blocked");
  assert.equal(isVerified(s), false);
  assert.equal(s.action?.label, "Compléter mon profil");
});

test("pièce en revue ou validation finale : statut compact sans bouton ; pièce refusée : la correction demandée", () => {
  const pending = proHomeState(elig({ kyc: "pending" }), none);
  assert.equal(pending.kind, "kycPending");
  assert.equal(pending.action, null);
  const approval = proHomeState(elig({ blockers: [{ code: "approval_pending", label: "…", action: null }] }), none);
  assert.equal(approval.kind, "approvalPending");
  assert.equal(approval.action, null);
  const rejected = proHomeState(elig({ kyc: "rejected", reason: "Photo floue : reprenez le recto." }), none);
  assert.equal(rejected.kind, "kycRejected");
  assert.equal(rejected.message, "Photo floue : reprenez le recto.");
  assert.equal(actionHref(rejected.action!.code), "/dashboard/profile/identity");
});

test("profil incomplet ou identité à faire : progression et « Continuer » ; mêmes priorités que l'application", () => {
  const incomplete = proHomeState(elig({ complete: false, kyc: "pending" }), none);
  assert.equal(incomplete.kind, "progress");
  assert.equal(incomplete.action?.label, "Continuer");
  assert.equal(proHomeState(elig({ kyc: "draft" }), none).action?.code, "verify_identity");
  assert.equal(proHomeState(elig({ kyc: "rejected", complete: false }), none).kind, "kycRejected");
  assert.equal(proHomeState(elig(), none).kind, "approvalPending");
  assert.equal(proHomeState(null, { publishable: true, servicesTotal: 2 }).kind, "verified", "serveur sans synthèse : autorisation du serveur");
});
