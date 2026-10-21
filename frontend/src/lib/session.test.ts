// « Se souvenir de moi » (site) : l'indice de session ne contient aucun secret ; persistant seulement si la case est cochée.
// Le jeton de rafraîchissement lui-même est un cookie HttpOnly posé par l'API (handy/test_remember_me.py). `npm run test:bo`.
import assert from "node:assert/strict";
import { test } from "node:test";
import { hasSessionHint, sessionHintCookie } from "./sessionHint.ts";

test("coché : indice persistant ; décoché : cookie de session (fin à la fermeture du navigateur)", () => {
  assert.equal(sessionHintCookie(true, true), "tratra_session=1; path=/; SameSite=Lax; max-age=2592000; Secure");
  assert.equal(sessionHintCookie(false, false), "tratra_session=1; path=/; SameSite=Lax");
  assert.doesNotMatch(sessionHintCookie(true, true), /access|refresh|eyJ/, "aucun jeton dans l'indice");
});

test("hors navigateur : aucune session à restaurer", () => {
  assert.equal(hasSessionHint(), false);
});
