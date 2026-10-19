// Tests du catalogue des métiers côté web : `npm run test:bo` (node --test, sans dépendance).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { DEFAULT_ICON, ICON_BY_KEY, featuredTrades, iconForCategory, resolveTrades } from "./trades.ts";

type Item = Parameters<typeof resolveTrades>[0][number];
const item = (id: number, name: string, slug: string, extra: Partial<Item> = {}): Item => ({ id, name, slug, is_active: true, parent: null, position: 100, ...extra });

/** Réponse type de `GET /handy/catalog/` : Jardinage et Cuisine avec prestations, Nounou sans prestation ni offre, un métier masqué. */
const CATALOG: Item[] = [
  item(7, "Jardinage", "jardinage", { icon_key: "tree", position: 10, is_featured: true, offers_total: 2, kind: "trade" }),
  item(71, "Entretien de fleurs", "entretien-de-fleurs", { parent: 7, trade: 7, icon_key: "seedling", offers_total: 1, kind: "service" }),
  item(72, "Élagage léger", "elagage-leger", { parent: 7, trade: 7, offers_total: 1, kind: "service" }),
  item(9, "Cuisine", "cuisine", { icon_key: "utensils", position: 20, is_featured: true, offers_total: 1, description: "Repas à domicile", kind: "trade" }),
  item(91, "Cours de cuisine", "cours-de-cuisine", { parent: 9, trade: 9, offers_total: 0 }),
  item(92, "Chef privé", "chef-prive", { parent: 9, trade: 9, offers_total: 1 }),
  item(12, "Nounou", "nounou", { icon_key: "baby", position: 30, offers_total: 0, kind: "trade" }),
  item(13, "Cachée", "cachee", { is_active: false }),
  item(131, "Invisible", "invisible", { parent: 13, trade: 13 }),
  item(93, "Prestation masquée", "prestation-masquee", { parent: 9, trade: 9, is_active: false }),
];

test("Jardinage, Cuisine et Nounou : mêmes noms, arborescence et offres que le catalogue serveur", () => {
  const trades = resolveTrades(CATALOG);
  assert.deepEqual(trades.map((t) => t.label), ["Jardinage", "Cuisine", "Nounou"]);
  const [jardinage, cuisine, nounou] = trades;
  assert.deepEqual(jardinage.prestations.map((p) => p.name).sort(), ["Entretien de fleurs", "Élagage léger"]);
  assert.deepEqual(cuisine.prestations.map((p) => p.name).sort(), ["Chef privé", "Cours de cuisine"]);
  assert.equal(jardinage.offersTotal, 2);
  assert.equal(cuisine.offersTotal, 1);
  assert.equal(cuisine.blurb, "Repas à domicile");
  assert.equal(jardinage.blurb, "Élagage léger, Entretien de fleurs");
  assert.equal(nounou.prestations.length, 0);
  assert.equal(jardinage.icon, ICON_BY_KEY["tree"]);
  assert.equal(cuisine.icon, ICON_BY_KEY["utensils"]);
  assert.equal(nounou.icon, ICON_BY_KEY["baby"]);
});

test("un métier actif sans offre ni prestation n'est JAMAIS masqué", () => {
  const nounou = resolveTrades(CATALOG).find((t) => t.key === "nounou");
  assert.ok(nounou);
  assert.equal(nounou.offersTotal, 0);
  assert.equal(nounou.href, "/search?metier=nounou");
});

test("un métier masqué disparaît avec ses prestations, une prestation masquée disparaît seule", () => {
  const trades = resolveTrades(CATALOG);
  assert.ok(!trades.some((t) => t.key === "cachee"));
  const all = trades.flatMap((t) => t.categories.map((c) => c.slug));
  assert.ok(!all.includes("invisible") && !all.includes("prestation-masquee"));
});

test("le lien de recherche couvre le métier et toutes ses prestations", () => {
  const cuisine = resolveTrades(CATALOG).find((t) => t.key === "cuisine");
  assert.equal(cuisine?.href, "/search?metier=cuisine,chef-prive,cours-de-cuisine");
  assert.deepEqual(cuisine?.slugs, ["cuisine", "chef-prive", "cours-de-cuisine"]);
});

test("l'ordre suit la position puis le nom, quel que soit l'ordre d'arrivée", () => {
  const shuffled = [...CATALOG].reverse();
  assert.deepEqual(resolveTrades(shuffled).map((t) => t.key), ["jardinage", "cuisine", "nounou"]);
  const bumped = CATALOG.map((c) => (c.slug === "nounou" ? { ...c, position: 1 } : c));
  assert.equal(resolveTrades(bumped)[0].key, "nounou");
});

test("mise en avant : les métiers marqués ; à défaut les premiers du catalogue (jamais une page vide)", () => {
  const trades = resolveTrades(CATALOG);
  assert.deepEqual(featuredTrades(trades).map((t) => t.key), ["jardinage", "cuisine"]);
  const none = resolveTrades(CATALOG.map((c) => ({ ...c, is_featured: false })));
  assert.deepEqual(featuredTrades(none, 2).map((t) => t.key), ["jardinage", "cuisine"]);
  assert.deepEqual(featuredTrades([]), []);
});

test("le rang du serveur (`order`) prime sur le nom quand il est fourni", () => {
  const ranked = [item(1, "A", "a", { order: 2 }), item(2, "B", "b", { order: 0 }), item(3, "C", "c", { order: 1 })];
  assert.deepEqual(resolveTrades(ranked).map((t) => t.key), ["b", "c", "a"]);
});

test("une catégorie dont le parent est absent n'est jamais promue métier", () => {
  const orphan = resolveTrades([item(1, "Orpheline", "orpheline", { parent: 999 })]);
  assert.deepEqual(orphan, []);
});

test("icône : clé normalisée du serveur, sinon icône par défaut — jamais une table par slug", () => {
  assert.equal(iconForCategory({ icon_key: "baby" }), ICON_BY_KEY["baby"]);
  assert.equal(iconForCategory({ icon_key: "inconnue" }), DEFAULT_ICON);
  assert.equal(iconForCategory({ icon_key: null }), DEFAULT_ICON);
  assert.equal(iconForCategory(undefined), DEFAULT_ICON);
});

const server = readFileSync(new URL("../../../handy/catalog.py", import.meta.url), "utf8");
const serverKeys = [...server.slice(server.indexOf("ICON_KEYS = (")).split("DEFAULT_ICON_KEY")[0].matchAll(/"([a-z0-9-]+)"/g)].map((m) => m[1]);

test("contrat avec le serveur : chaque clé d'icône du vocabulaire commun a son pictogramme web, et réciproquement", () => {
  assert.ok(serverKeys.length > 100);
  assert.deepEqual(serverKeys.filter((k) => !(k in ICON_BY_KEY)), []);
  assert.deepEqual(Object.keys(ICON_BY_KEY).filter((k) => !serverKeys.includes(k)), []);
});

test("aucun catalogue de métiers n'est écrit en dur dans le code web", () => {
  for (const file of ["lib/trades.ts", "components/site/SiteFooter.tsx", "components/landing/TradesSection.tsx", "components/landing/UrgencySection.tsx"]) {
    const src = readFileSync(new URL(`../${file}`, import.meta.url), "utf8");
    assert.ok(!/TRADE_FAMILIES|ICON_BY_SLUG|metier=plomberie|metier=electricite/.test(src), file);
  }
});
