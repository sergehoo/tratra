// Annonces (Back-Office) : destinations filtrées selon les destinataires, paramètre, aperçu de la notification. `npm run test:bo`.
import assert from "node:assert/strict";
import { test } from "node:test";
import { allowedFor, groupedDestinations, joinValue, previewNotes, pushText, rolesOf, splitValue, type AppDestination } from "./announcementPreview.ts";

const D = (key: string, group: string, roles: AppDestination["roles"], param: AppDestination["param"] = null): AppDestination =>
  ({ key, label: key, group, roles, param, param_required: Boolean(param) });
const ALL: AppDestination["roles"] = ["artisans", "clients", "companies"];
const REGISTRY = [D("home", "Découvrir", ALL), D("service", "Découvrir", ALL, "service"), D("reputation", "Espace professionnel", ["artisans"]),
  D("business", "Entreprises", ["companies"])];

test("seuls les écrans ouverts à TOUS les destinataires cochés sont proposés", () => {
  const clientsAndPros = groupedDestinations(REGISTRY, ["clients", "artisans"]);
  assert.deepEqual(clientsAndPros.map(([g, items]) => [g, items.map((d) => d.key)]), [["Découvrir", ["home", "service"]]]);
  const pros = groupedDestinations(REGISTRY, ["artisans"]).flatMap(([, items]) => items.map((d) => d.key));
  assert.deepEqual(pros, ["home", "service", "reputation"]);
  assert.equal(allowedFor(REGISTRY[2], ["clients"]), false);
  assert.equal(allowedFor(REGISTRY[3], ["companies"]), true);
});

test("destinataires lus dans le formulaire", () => {
  assert.deepEqual(rolesOf({ to_clients: true, to_artisans: false, to_companies: true }), ["clients", "companies"]);
  assert.deepEqual(rolesOf({ to_clients: false, to_artisans: false, to_companies: false }), []);
});

test("valeur « clé/identifiant » : identifiant numérique seulement", () => {
  assert.deepEqual(splitValue("service/42"), { key: "service", id: "42" });
  assert.deepEqual(splitValue("service/abc"), { key: "service", id: "" });
  assert.deepEqual(splitValue("home"), { key: "home", id: "" });
  assert.equal(joinValue("service", "42"), "service/42");
  assert.equal(joinValue("service", ""), "service");
  assert.equal(joinValue("service", "4a"), "service");
});

test("aperçu : texte de la notification limité à 200 caractères, comme l'envoi réel", () => {
  const long = "x".repeat(260);
  const p = pushText("  Titre  ", long);
  assert.equal(p.title, "Titre");
  assert.equal(p.body.length, 200);
  assert.equal(p.truncated, true);
  assert.equal(pushText("T", "court").truncated, false);
});

test("points d'attention : sans image, sans push, promotion, destination refusée, lien web", () => {
  const base = { title: "Une réparation ?", body: "Publiez votre besoin.", kind: "service", send_push: true, hasImage: false, action_kind: "deeplink",
    action_label: "Publier", roles: ["clients"] as AppDestination["roles"] };
  const texts = (o: Partial<typeof base> & { destinationError?: string }) => previewNotes({ ...base, ...o }).map((n) => n.text);
  assert.ok(texts({}).some((t) => t.startsWith("Sans image")));
  assert.ok(texts({ hasImage: true }).some((t) => t.includes("2:1")));
  assert.ok(texts({ send_push: false }).some((t) => t.startsWith("Sans notification push")));
  assert.ok(texts({ kind: "promotion" }).some((t) => t.includes("consentement marketing")));
  assert.ok(texts({ action_kind: "link" }).some((t) => t.startsWith("Lien web")));
  const refused = previewNotes({ ...base, destinationError: "« Ma réputation » n'est accessible qu'aux artisans." });
  assert.equal(refused.find((n) => n.tone === "danger")?.text, "« Ma réputation » n'est accessible qu'aux artisans.");
  assert.ok(previewNotes({ ...base, roles: [] }).some((n) => n.tone === "danger"));
  assert.ok(texts({ title: "T".repeat(60) }).some((t) => t.startsWith("Titre long")));
});
