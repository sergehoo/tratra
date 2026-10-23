// Badges Google Play / App Store (landing) : `npm run test:bo` (node --test, sans dépendance).
import assert from "node:assert/strict";
import { test } from "node:test";
import { officialStoreUrl, storeBadges } from "./mobileApps.ts";

const PLAY = "https://play.google.com/store/apps/details?id=com.tratra";
const APPLE = "https://apps.apple.com/ci/app/tratra/id6450000000";

test("aucun lien, lien vide ou API indisponible : aucun badge (ni titre, ni espace réservé)", () => {
  assert.deepEqual(storeBadges(null), []);
  assert.deepEqual(storeBadges(undefined), []);
  assert.deepEqual(storeBadges({ android_url: null, ios_url: null }), []);
  assert.deepEqual(storeBadges({ android_url: "", ios_url: "   " }), []);
});

test("chaque badge est masqué indépendamment ; ordre Google Play puis App Store", () => {
  assert.deepEqual(storeBadges({ android_url: PLAY, ios_url: null }).map((b) => b.kind), ["android"]);
  assert.deepEqual(storeBadges({ android_url: null, ios_url: APPLE }).map((b) => b.kind), ["ios"]);
  assert.deepEqual(storeBadges({ android_url: PLAY, ios_url: APPLE }).map((b) => b.kind), ["android", "ios"]);
});

test("ouverture dans un nouvel onglet, sans accès à la page d'origine ni référent ; libellés officiels", () => {
  const [android, ios] = storeBadges({ android_url: PLAY, ios_url: APPLE });
  for (const b of [android, ios]) {
    assert.equal(b.target, "_blank");
    assert.equal(b.rel, "noopener noreferrer");
    assert.match(b.label, /nouvel onglet/);
    assert.ok(b.src.startsWith("/images/stores/"), "visuel servi par le site (aucun appel à Google/Apple chez le visiteur)");
  }
  assert.equal(android.href, PLAY);
  assert.match(android.label, /^Disponible sur Google Play/);
  assert.equal(ios.href, APPLE);
  assert.match(ios.label, /^Télécharger dans l’App Store/);
});

test("liens piégés jamais rendus cliquables", () => {
  for (const raw of [
    "http://play.google.com/store/apps/details?id=com.tratra",
    "javascript:alert(1)",
    "https://play.google.com.evil.example/store/apps/details?id=com.tratra",
    "https://evil.example/store/apps/details?id=com.tratra&x=play.google.com",
    "https://play.google.com@evil.example/store/apps/details?id=com.tratra",
    "https://user:pw@play.google.com/store/apps/details?id=com.tratra",
    "https://play.google.com:8443/store/apps/details?id=com.tratra",
    "https://play.google.com\\@evil.example/store/apps/details?id=com.tratra",
    "https://www.google.com/url?q=https://play.google.com/store/apps/details?id=com.tratra",
    "https://play.google.com/store/apps/details",
    "https://play.google.com/store/apps/details?id=com.tratra&id=com.autre",
    "https://play.google.com/store/apps/details?id=com.tra\ntra",   // le navigateur retirerait le saut de ligne
    "//play.google.com/store/apps/details?id=com.tratra",
    APPLE,
  ]) {
    assert.equal(officialStoreUrl("android", raw), null, raw);
  }
  for (const raw of [
    "http://apps.apple.com/ci/app/tratra/id6450000000",
    "https://apps.apple.com.evil.example/ci/app/tratra/id6450000000",
    "https://itunes.apple.com/ci/app/tratra/id6450000000",
    "https://apps.apple.com/ci/developer/tratra/id6450000000",
    "https://apps.apple.com/ci/app/../../redirect/id6450000000",
    PLAY,
  ]) {
    assert.equal(officialStoreUrl("ios", raw), null, raw);
  }
  assert.deepEqual(storeBadges({ android_url: "https://evil.example/app", ios_url: "javascript:alert(1)" }), []);
});

test("fiches officielles acceptées (langue, pays, nom de l'application)", () => {
  assert.equal(officialStoreUrl("android", `${PLAY}&hl=fr&gl=CI`), `${PLAY}&hl=fr&gl=CI`);
  assert.equal(officialStoreUrl("ios", "https://apps.apple.com/app/id6450000000"), "https://apps.apple.com/app/id6450000000");
  assert.equal(officialStoreUrl("ios", APPLE), APPLE);
});
