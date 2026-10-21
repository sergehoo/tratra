// Hybrid Matching (site) : `npm run test:bo` (node --test, sans dépendance).
import assert from "node:assert/strict";
import { test } from "node:test";
import { effectiveMatching, intentKey, priceFromOffer, query } from "./flashModel.ts";

test("le choix explicite du client l'emporte sur le conseil du serveur ; sans choix, le mode présélectionné", () => {
  const s = { suggested: "direct", preselected: "direct", reason: "", note: "", remembered: false, immediate: false, available_pros: 2 } as const;
  assert.equal(effectiveMatching("auto", s), "auto");
  assert.equal(effectiveMatching(null, s), "direct");
  assert.equal(effectiveMatching(null, null), "auto");
});

test("prix repris de l'offre choisie : fixe → montant, devis → mode devis, à l'heure → au client", () => {
  assert.deepEqual(priceFromOffer({ id: 1, title: "x", price: 12000, price_type: "fixed", category: 3 }), { amount: 12000, quote: false });
  assert.deepEqual(priceFromOffer({ id: 1, title: "x", price: null, price_type: "quote", category: 3 }), { amount: null, quote: true });
  assert.deepEqual(priceFromOffer({ id: 1, title: "x", price: 5000, price_type: "hourly", category: 3 }), { amount: null, quote: false });
  assert.deepEqual(priceFromOffer(null), { amount: null, quote: false });
});

test("requête : valeurs vides retirées, booléens en 1, encodage", () => {
  assert.equal(query({ category: 3, when: null, favorites: true, commune: "Cocody Riviera", badge: "" }), "?category=3&favorites=1&commune=Cocody+Riviera");
  assert.equal(query({ a: undefined, b: false }), "");
});

test("clé d'idempotence : préfixe, unique, bornée à 80 caractères", () => {
  const a = intentKey("flash-req"), b = intentKey("flash-req");
  assert.ok(a.startsWith("flash-req-") && a !== b && a.length <= 80 && /^[A-Za-z0-9_\-:.]+$/.test(a));
});
