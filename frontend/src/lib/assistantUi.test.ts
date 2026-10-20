// Tests de la mise en forme sûre et du lecteur SSE de Tratra AI : `npm run test:bo` (node --test, sans dépendance).
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseSse } from "./assistantStream.ts";
import { isInternalBackofficeHref, parseBlocks, parseInline } from "./safeText.ts";

test("gras, listes et liens internes sont reconnus", () => {
  const blocks = parseBlocks("Voici **2 alertes** :\n- Pièces KYC : [Ouvrir la file](/backoffice/kyc)\n- Autre point\n\nFin.");
  assert.equal(blocks.length, 3);
  assert.deepEqual(blocks[0], { t: "p", inline: [{ t: "text", v: "Voici " }, { t: "bold", v: "2 alertes" }, { t: "text", v: " :" }] });
  assert.equal(blocks[1].t, "ul");
  assert.deepEqual((blocks[1] as { items: unknown[] }).items[0], [{ t: "text", v: "Pièces KYC : " }, { t: "link", v: "Ouvrir la file", href: "/backoffice/kyc" }]);
});

test("aucun lien externe, javascript: ni protocole relatif n'est cliquable", () => {
  for (const evil of ["https://evil.example/x", "javascript:alert(1)", "//evil.example", "/backoffice/../admin", "/backoffice//evil.example", "data:text/html,x"]) {
    const inline = parseInline(`[cliquez ici](${evil})`);
    assert.ok(inline.every((i) => i.t !== "link"), evil);
  }
  assert.equal(isInternalBackofficeHref("/backoffice/users/12"), true);
  assert.equal(isInternalBackofficeHref("/backoffice?tab=risks"), true);
  assert.equal(isInternalBackofficeHref("/dashboard"), false);
});

test("le HTML n'est jamais interprété : il reste du texte", () => {
  const blocks = parseBlocks("<img src=x onerror=alert(1)> et <script>alert(1)</script>");
  assert.deepEqual(blocks, [{ t: "p", inline: [{ t: "text", v: "<img src=x onerror=alert(1)> et <script>alert(1)</script>" }] }]);
});

test("le flux SSE est reconstitué même coupé au milieu d'un bloc", () => {
  const raw = 'event: meta\ndata: {"type":"meta","conversation":1,"message":2}\n\n: ping\n\nevent: delta\ndata: {"type":"delta","text":"Bon"}\n\nevent: del';
  const first = parseSse(raw);
  assert.deepEqual(first.events.map((e) => e.type), ["meta", "delta"]);
  assert.equal(first.rest, "event: del");
  const second = parseSse(first.rest + 'ta\ndata: {"type":"delta","text":"jour"}\n\n');
  assert.deepEqual(second.events, [{ type: "delta", text: "jour" }]);
  assert.equal(second.rest, "");
});

test("un bloc illisible est ignoré sans casser le flux", () => {
  const { events } = parseSse('event: delta\ndata: {pas du json\n\nevent: done\ndata: {"type":"done","message":3,"content":"ok","sources":[],"provider":"deepseek","usage":{"tokens_in":1,"tokens_out":1}}\n\n');
  assert.deepEqual(events.map((e) => e.type), ["done"]);
});

// ---- Connexion bloquée (compte à rebours) ----
import { DEFAULT_SUPPORT_EMAIL, formatCountdown, parseLoginLock, secondsLeft } from "./loginLock.ts";

test("blocage de connexion : le serveur donne le temps restant et le support", () => {
  assert.deepEqual(parseLoginLock({ status: 429, data: { code: "login_locked", retry_after: 3330, support_email: "aide@exemple.ci" } }), { seconds: 3330, supportEmail: "aide@exemple.ci" });
  assert.deepEqual(parseLoginLock({ status: 429, data: { code: "login_locked", retry_after: "120" } }), { seconds: 120, supportEmail: DEFAULT_SUPPORT_EMAIL });
  assert.equal(parseLoginLock({ status: 429, data: { code: "login_locked", retry_after: 10.2 } })?.seconds, 11);
});

test("un refus ordinaire, un 429 de débit ou une réponse sans délai ne sont jamais pris pour un blocage", () => {
  assert.equal(parseLoginLock({ status: 400, data: { non_field_errors: ["x"] } }), null);
  assert.equal(parseLoginLock({ status: 429, data: { detail: "Requête ralentie. Expected available in 60 seconds." } }), null);
  assert.equal(parseLoginLock({ status: 429, data: { code: "login_locked" } }), null);
  assert.equal(parseLoginLock({ status: 429, data: { code: "login_locked", retry_after: 0 } }), null);
  assert.equal(parseLoginLock({ status: 429, data: null }), null);
  assert.equal(parseLoginLock(new TypeError("network")), null);
  assert.equal(parseLoginLock({ status: 429, data: { code: "login_locked", retry_after: 5, support_email: "pas un mail" } })?.supportEmail, DEFAULT_SUPPORT_EMAIL);
});

test("mm:ss et décompte arrondi au-dessus", () => {
  assert.equal(formatCountdown(3330), "55:30");
  assert.equal(formatCountdown(3600), "60:00");
  assert.equal(formatCountdown(7), "00:07");
  assert.equal(formatCountdown(-3), "00:00");
  assert.equal(formatCountdown(Number.NaN), "00:00");
  assert.equal(secondsLeft(10_000, 0), 10);
  assert.equal(secondsLeft(10_000, 9_200), 1);
  assert.equal(secondsLeft(10_000, 10_000), 0);
  assert.equal(secondsLeft(10_000, 12_000), 0);
});
