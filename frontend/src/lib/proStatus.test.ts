// Accueil : carte du profil professionnel d'après les statuts réels du serveur (trois niveaux). `npm run test:bo` (node --test).
import assert from "node:assert/strict";
import { test } from "node:test";
import { actionHref, isVerified, mention, proHomeState, showsProgress, type EligibilityLike } from "./proStatus.ts";

type B = EligibilityLike["publication"]["blockers"];
const elig = (o: { published?: boolean; orders?: boolean; complete?: boolean; kyc?: string; face?: string; reason?: string | null; offers?: number;
  blockers?: B; ordersBlockers?: B } = {}): EligibilityLike => {
  const published = o.published ?? true, orders = o.orders ?? false, kyc = o.kyc ?? "draft", face = o.face ?? "unavailable";
  const level = orders && face === "done" ? "VERIFIE" : kyc === "approved" ? "IDENTITE_VERIFIEE" : "NON_VERIFIE";
  return {
    profile: { complete: o.complete ?? true },
    kyc: { status: kyc, reason: o.reason ?? null },
    publication: { authorized: published, blockers: o.blockers ?? [] },
    orders: { authorized: orders, blockers: o.ordersBlockers ?? (!orders && kyc === "approved" ? [{ code: "approval_pending", label: "…", action: null }] : []) },
    verification: { level, label: { VERIFIE: "Vérifié", IDENTITE_VERIFIEE: "Identité vérifiée", NON_VERIFIE: "Non vérifié" }[level]!, face: { state: face } },
    stages: [{ key: "face", benefit: "Attribue le badge « Vérifié »." }],
    offers: { total: o.offers ?? 1, active: o.offers ?? 1, action: null },
  };
};
const old = (e: EligibilityLike): EligibilityLike => ({ profile: e.profile, kyc: e.kyc, publication: e.publication, offers: e.offers });
const none = { publishable: false, servicesTotal: 0 };
const kind = (e: EligibilityLike | null, f = none) => proHomeState(e, f).kind;

test("publié sans vérification d'identité : mention « Non vérifié », « Activer mes commandes » — jamais « Vérifié »", () => {
  const s = proHomeState(elig(), none);
  assert.equal(s.kind, "activate");
  assert.equal(s.action?.label, "Activer mes commandes");
  assert.equal(actionHref(s.action!.code), "/dashboard/profile/identity");
  assert.equal(mention(s), "Non vérifié");
  assert.ok(!isVerified(s) && !showsProgress(s));
  const first = proHomeState(elig({ offers: 0 }), none);
  assert.equal(first.kind, "firstOffer");
  assert.equal(first.action?.label, "Publier un service");
  assert.equal(actionHref(first.action!.code), "/dashboard/provider/services/new");
});

test("commandes : pièce en revue, refusée (correction demandée), approuvée mais activation retenue", () => {
  const pending = proHomeState(elig({ kyc: "pending" }), none);
  assert.equal(pending.kind, "kycPending");
  assert.equal(pending.action, null);
  const rejected = proHomeState(elig({ kyc: "rejected", reason: "Photo floue : reprenez le recto." }), none);
  assert.equal(rejected.kind, "kycRejected");
  assert.equal(rejected.message, "Photo floue : reprenez le recto.");
  assert.equal(mention(rejected), "Non vérifié", "le service reste public");
  const held = proHomeState(elig({ kyc: "approved" }), none);
  assert.equal(held.kind, "approvalPending");
  assert.equal(held.action, null);
  assert.equal(mention(held), "Identité vérifiée");
});

test("badge « Vérifié » : uniquement commandes activées ET vérification faciale validée ; proposée dans l'application, sans bouton", () => {
  const v = proHomeState(elig({ orders: true, kyc: "approved", face: "done" }), none);
  assert.equal(v.kind, "none");
  assert.ok(isVerified(v));
  const badge = proHomeState(elig({ orders: true, kyc: "approved", face: "todo" }), none);
  assert.equal(badge.kind, "badge");
  assert.equal(badge.action, null);
  assert.match(badge.message, /application Tratra/);
  assert.equal(kind(elig({ orders: true, kyc: "approved", face: "retry" })), "badge");
  assert.equal(kind(elig({ orders: true, kyc: "approved", face: "pending" })), "facePending");
  assert.equal(kind(elig({ orders: true, kyc: "approved" })), "none", "vérification faciale non proposée : rien à faire");
  const sensitive = (face: string) => elig({ kyc: "approved", face, ordersBlockers: [{ code: "face_required", label: "Vérification faciale demandée",
    hint: "Votre métier la demande avant toute commande.", action: { code: "verify_identity", label: "Faire la vérification faciale", step: "face" } }] });
  assert.equal(kind(sensitive("todo")), "activate");
  assert.equal(proHomeState(sensitive("todo"), none).action, null);
  assert.equal(kind(sensitive("pending")), "facePending");
  for (const e of [elig(), elig({ kyc: "pending" }), elig({ kyc: "approved" }), elig({ orders: true, kyc: "approved" }), elig({ orders: true, kyc: "approved", face: "pending" }),
    sensitive("todo"), old(elig({ orders: true, kyc: "approved", face: "done" }))]) {
    assert.equal(isVerified(proHomeState(e, none)), false);
  }
});

test("publication : profil incomplet → progression ; blocage réel et son action ; rien n'est déduit de la liste de contrôle", () => {
  const incomplete = proHomeState(elig({ published: false, complete: false, kyc: "rejected" }), none);
  assert.equal(incomplete.kind, "progress", "la publication ne dépend plus de la pièce");
  assert.equal(incomplete.action?.label, "Continuer");
  assert.equal(mention(incomplete), null);
  const s = proHomeState(elig({ published: false, kyc: "approved", blockers: [{ code: "experience_minimum", label: "Expérience minimale non atteinte", hint: "…",
    action: { code: "edit_profile", label: "Compléter mon profil" } }] }), { publishable: false, servicesTotal: 1 });
  assert.equal(s.kind, "blocked");
  assert.equal(s.action?.label, "Compléter mon profil");
  assert.equal(isVerified(s), false);
});

test("serveur plus ancien (sans les niveaux) : la publication attendait la pièce ; jamais de badge", () => {
  assert.equal(kind(old(elig({ published: false, kyc: "rejected" }))), "kycRejected");
  assert.equal(proHomeState(old(elig({ published: false, kyc: "draft" })), none).action?.code, "verify_identity");
  assert.equal(kind(old(elig({ published: false, kyc: "pending" }))), "kycPending");
  const pub = proHomeState(old(elig({ kyc: "approved" })), none);
  assert.deepEqual([pub.kind, mention(pub), isVerified(pub)], ["none", "Identité vérifiée", false]);
  const bare = proHomeState(null, { publishable: true, servicesTotal: 2 });
  assert.deepEqual([bare.kind, isVerified(bare)], ["none", false]);
  assert.equal(kind(null, { publishable: true, servicesTotal: 0 }), "firstOffer");
  assert.equal(kind(null), "progress");
});
