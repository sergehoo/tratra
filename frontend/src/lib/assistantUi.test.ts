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
