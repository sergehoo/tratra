// Tests du modèle de navigation du Back-Office : `npm run test:bo` (node --test, sans dépendance).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { GROUPS, activeModule, activeSub, breadcrumb, buildNav, normalize, searchEntries, searchLocal, type ModuleLike } from "./boNavModel.ts";

/** Registre serveur réel : `backoffice/modules.py` (source de vérité des modules et de leurs chemins). */
function serverModules(): ModuleLike[] {
  const src = readFileSync(new URL("../../../backoffice/modules.py", import.meta.url), "utf8");
  const rows = [...src.matchAll(/\("([a-z_]+)", "([^"]+)", "[a-z_.]+", "[a-z0-9-]+", "(\/backoffice[^"]*)"\)/g)];
  return rows.map(([, id, label, path]) => ({ id, label, path }));
}

test("le registre serveur est lu en entier (22 modules, dont Tratra Flash et l’engagement automatisé)", () => {
  assert.equal(serverModules().length, 22);
});

test("7 rubriques, dans l'ordre demandé", () => {
  assert.deepEqual(
    buildNav(serverModules()).map((g) => g.label),
    ["Vue d’ensemble", "Utilisateurs & Identités", "Prestations & Missions", "Tratra Business", "Finances", "Communication", "Administration"],
  );
});

test("chaque module serveur apparaît EXACTEMENT une fois (aucun doublon, aucun oubli)", () => {
  const ids = buildNav(serverModules()).flatMap((g) => g.items.map((i) => i.id));
  assert.equal(ids.length, new Set(ids).size, "doublon de navigation");
  assert.deepEqual([...ids].sort(), serverModules().map((m) => m.id).sort());
});

test("la table des rubriques couvre tous les modules du serveur (sinon ils tomberaient dans Administration)", () => {
  const covered = new Set(GROUPS.flatMap((g) => g.modules));
  assert.deepEqual(serverModules().filter((m) => !covered.has(m.id)).map((m) => m.id), []);
});

test("un rôle restreint ne voit que ses rubriques (jamais de rubrique vide)", () => {
  const finance = serverModules().filter((m) => ["dashboard", "bookings", "finance", "analytics", "business", "engagements"].includes(m.id));
  const nav = buildNav(finance);
  assert.deepEqual(nav.map((g) => g.id), ["overview", "missions", "business", "finance"]);
  assert.ok(nav.every((g) => g.items.length > 0));
  assert.ok(!nav.some((g) => g.id === "administration"), "pas d'Administration sans module d'administration");
});

test("un module inconnu reste visible (Administration)", () => {
  const nav = buildNav([{ id: "nouveau", label: "Nouveau module", path: "/backoffice/nouveau" }]);
  assert.equal(nav[0].id, "administration");
  assert.equal(nav[0].items[0].href, "/backoffice/nouveau");
});

test("les sous-menus pointent vers les onglets réels, sans toucher aux routes", () => {
  const nav = buildNav(serverModules());
  const finance = nav.find((g) => g.id === "finance")!.items[0];
  assert.deepEqual(finance.subs.map((s) => s.href), ["/backoffice/finance?tab=payments", "/backoffice/finance?tab=payouts", "/backoffice/finance?tab=invoices"]);
  assert.equal(finance.href, "/backoffice/finance");
});

test("module et sous-menu actifs", () => {
  const nav = buildNav(serverModules());
  assert.equal(activeModule(nav, "/backoffice")?.item.id, "dashboard");
  assert.equal(activeModule(nav, "/backoffice/users/12")?.item.id, "users");
  assert.equal(activeModule(nav, "/backoffice/tratra-id")?.item.id, "tratra_id");
  assert.equal(activeModule(nav, "/ailleurs"), null);
  const bookings = activeModule(nav, "/backoffice/bookings")!.item;
  assert.equal(activeSub(bookings, null)?.tab, "bookings"); // onglet par défaut
  assert.equal(activeSub(bookings, "disputes")?.tab, "disputes");
  assert.equal(activeSub(bookings, "inconnu")?.tab, "bookings");
  assert.equal(activeSub(activeModule(nav, "/backoffice/users")!.item, null), null);
});

test("recherche : sans accents, tous les mots, libellé en tête", () => {
  const entries = searchEntries(buildNav(serverModules()));
  assert.equal(searchLocal(entries, "verification kyc")[0].href, "/backoffice/kyc");
  assert.equal(searchLocal(entries, "Vérification")[0].label, "Vérification KYC");
  assert.ok(searchLocal(entries, "paiem").some((e) => e.href === "/backoffice/finance?tab=payments"));
  assert.ok(searchLocal(entries, "resiliation").some((e) => e.href === "/backoffice/engagements?tab=contracts"));
  assert.ok(searchLocal(entries, "journal audit").some((e) => e.href === "/backoffice/security?tab=audit"));
  assert.deepEqual(searchLocal(entries, "zzzzzz"), []);
  assert.deepEqual(searchLocal(entries, "   "), []);
  assert.equal(normalize("  Réservations   d’Été "), "reservations d ete");
});

test("la recherche ne propose que les pages autorisées", () => {
  const nav = buildNav(serverModules().filter((m) => ["dashboard", "analytics"].includes(m.id)));
  assert.deepEqual(searchLocal(searchEntries(nav), "finance"), []);
});

test("fil d'Ariane", () => {
  const nav = buildNav(serverModules());
  assert.deepEqual(breadcrumb(nav, "/backoffice", null).map((c) => c.label), ["Back-Office", "Tableau de bord"]);
  assert.deepEqual(breadcrumb(nav, "/backoffice/users", null).map((c) => c.label), ["Back-Office", "Utilisateurs & Identités", "Utilisateurs"]);
  assert.deepEqual(breadcrumb(nav, "/backoffice/finance", "payouts").map((c) => c.label), ["Back-Office", "Finances", "Retraits"]); // pas de « Finances › Finances »
  assert.deepEqual(breadcrumb(nav, "/backoffice/bookings", "disputes").map((c) => c.label), ["Back-Office", "Prestations & Missions", "Réservations et litiges", "Litiges"]);
  assert.deepEqual(breadcrumb(nav, "/backoffice/users/12", null).map((c) => c.label), ["Back-Office", "Utilisateurs & Identités", "Utilisateurs", "Fiche #12"]);
  assert.equal(breadcrumb(nav, "/backoffice/users/12", null, "Awa K.").at(-1)?.label, "Awa K.");
  assert.equal(breadcrumb(nav, "/backoffice/users/12", null)[2].href, "/backoffice/users");
});

test("l'engagement automatisé est rangé dans Communication, après les annonces, et trouvable par « relance »", () => {
  const nav = buildNav(serverModules());
  const ids = nav.find((g) => g.id === "communication")!.items.map((i) => i.id);
  assert.equal(ids.indexOf("campaigns"), ids.indexOf("announcements") + 1);
  assert.ok(searchLocal(searchEntries(nav), "relance").some((e) => e.href === "/backoffice/campaigns"));
});
