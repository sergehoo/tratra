// Modes des offres : `npm run test:bo` (node --test, sans dépendance).
import assert from "node:assert/strict";
import { test } from "node:test";
import { allowedModes, modesLabel, sanitizeModes } from "./serviceModes.ts";

test("le ponctuel est toujours ouvert ; récurrent et contractuel suivent la règle du métier", () => {
  assert.deepEqual([...allowedModes(null)], ["one_off"]);
  assert.deepEqual([...allowedModes({ allow_recurring: true, allow_long_term: false })], ["one_off", "recurring"]);
  assert.deepEqual([...allowedModes({ allow_recurring: true, allow_long_term: true })], ["one_off", "recurring", "contract"]);
});

test("un changement de métier retire les modes qu'il n'ouvre pas, ordre canonique conservé", () => {
  assert.deepEqual(sanitizeModes(["contract", "one_off"], { allow_recurring: true, allow_long_term: false }), ["one_off"]);
  assert.deepEqual(sanitizeModes(["contract", "one_off"], { allow_recurring: false, allow_long_term: true }), ["one_off", "contract"]);
  assert.deepEqual(sanitizeModes(["recurring"], null), ["recurring"]); // règle pas encore chargée : rien n'est retiré
});

test("libellés lisibles", () => {
  assert.equal(modesLabel(["one_off", "contract"]), "Ponctuel, Contractuel (mensuel)");
  assert.equal(modesLabel(undefined), "");
});
