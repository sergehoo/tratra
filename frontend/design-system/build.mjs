#!/usr/bin/env node
/**
 * Générateur de tokens du Design System Tratra.
 *
 * Source unique : design-system/tokens.json
 * Sorties :
 *   - frontend/src/styles/tokens.css            (variables CSS --tt-*)
 *   - <app Flutter>/lib/design/tokens.dart      (TtColors, TtRadius, TtShadows…)
 *
 * Usage :
 *   node design-system/build.mjs            écrit les fichiers
 *   node design-system/build.mjs --check    échoue si un fichier généré est périmé
 *
 * Le dossier Flutter se règle avec TRATRA_FLUTTER_DIR ; par défaut le dépôt
 * compagnon voisin ../handy_tratra/flutter_tratra. S'il est absent (CI web),
 * seule la sortie CSS est produite/vérifiée.
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontendDir = resolve(here, "..");
const repoRoot = resolve(frontendDir, "..");
const tokens = JSON.parse(readFileSync(resolve(here, "tokens.json"), "utf8"));
const check = process.argv.includes("--check");

const flutterDir = process.env.TRATRA_FLUTTER_DIR
  ? resolve(process.env.TRATRA_FLUTTER_DIR)
  : resolve(repoRoot, "../handy_tratra/flutter_tratra");

// ---------- utilitaires ----------
const kebab = (s) => s.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();
const flatColors = Object.assign({}, ...Object.values(tokens.color));

function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
}
function dartColor(hex, alpha = 1) {
  const a = Math.round(alpha * 255).toString(16).padStart(2, "0");
  return `Color(0x${a}${hex.replace("#", "").toUpperCase()})`;
}
function cssShadow(s) {
  const [r, g, b] = hexToRgb(s.color);
  const alpha = String(s.alpha).replace(/^0\./, ".");
  return `${s.x}px ${s.y}px ${s.blur}px ${s.spread}px rgba(${r},${g},${b},${alpha})`;
}

// ---------- CSS ----------
function buildCss() {
  const lines = [
    "/* GÉNÉRÉ par design-system/build.mjs depuis tokens.json — ne pas éditer à la main. */",
    ":root {",
  ];
  for (const [name, hex] of Object.entries(flatColors)) lines.push(`  --tt-${kebab(name)}: ${hex};`);
  for (const [name, [a, b]] of Object.entries(tokens.gradient)) {
    lines.push(`  --tt-gradient-${kebab(name)}: linear-gradient(135deg, ${a}, ${b});`);
  }
  for (const [name, px] of Object.entries(tokens.radius)) lines.push(`  --tt-radius-${kebab(name)}: ${px}px;`);
  for (const [name, s] of Object.entries(tokens.shadow)) lines.push(`  --tt-shadow-${kebab(name)}: ${cssShadow(s)};`);
  for (const [name, ms] of Object.entries(tokens.motion.duration)) lines.push(`  --tt-duration-${kebab(name)}: ${ms}ms;`);
  for (const [name, c] of Object.entries(tokens.motion.easing)) lines.push(`  --tt-ease-${kebab(name)}: cubic-bezier(${c.join(",")});`);
  lines.push(`  --tt-sidebar-width: ${tokens.layout.sidebarWidth}px;`);
  lines.push(`  --tt-topbar-height: ${tokens.layout.topbarHeight}px;`);
  lines.push(`  --tt-bottom-nav-height: ${tokens.layout.bottomNavHeight}px;`);
  lines.push("}", "");
  return lines.join("\n");
}

// ---------- Dart ----------
function buildDart() {
  const L = [];
  L.push(
    "// GÉNÉRÉ par frontend/design-system/build.mjs depuis tokens.json (dépôt tratra).",
    "// Ne pas éditer à la main : modifier tokens.json puis relancer `npm run ds:build`.",
    "// ignore_for_file: constant_identifier_names",
    "import 'package:flutter/material.dart';",
    "",
    "/// Couleurs de marque, neutres et sémantiques (miroir de la landing web).",
    "abstract final class TtColors {",
  );
  for (const [name, hex] of Object.entries(flatColors)) L.push(`  static const Color ${name} = ${dartColor(hex)};`);
  L.push("}", "", "/// Dégradés de marque.", "abstract final class TtGradients {");
  for (const [name, [a, b]] of Object.entries(tokens.gradient)) {
    L.push(
      `  static const LinearGradient ${name} = LinearGradient(`,
      "    begin: Alignment.topLeft,",
      "    end: Alignment.bottomRight,",
      `    colors: [${dartColor(a)}, ${dartColor(b)}],`,
      "  );",
    );
  }
  L.push("}", "", "/// Échelle d'espacement (base 4 dp).", "abstract final class TtSpace {");
  for (const [k, v] of Object.entries(tokens.space)) L.push(`  static const double s${k} = ${v};`);
  L.push("}", "", "/// Rayons : control (champs/boutons carrés), panel, card, sheet, pill.", "abstract final class TtRadius {");
  for (const [k, v] of Object.entries(tokens.radius)) L.push(`  static const double ${k} = ${v};`);
  for (const k of Object.keys(tokens.radius)) {
    L.push(`  static BorderRadius get ${k}All => BorderRadius.circular(${k});`);
  }
  L.push("}", "", "/// Ombres (équivalents des shadow-* Tailwind).", "abstract final class TtShadows {");
  for (const [name, s] of Object.entries(tokens.shadow)) {
    L.push(
      `  static const List<BoxShadow> ${name} = [`,
      `    BoxShadow(color: ${dartColor(s.color, s.alpha)}, offset: Offset(${s.x}, ${s.y}), blurRadius: ${s.blur}, spreadRadius: ${s.spread}),`,
      "  ];",
    );
  }
  L.push("}", "", "/// Durées et courbes d'animation.", "abstract final class TtMotion {");
  for (const [name, ms] of Object.entries(tokens.motion.duration)) L.push(`  static const Duration ${name} = Duration(milliseconds: ${ms});`);
  for (const [name, c] of Object.entries(tokens.motion.easing)) L.push(`  static const Curve ${name} = Cubic(${c.join(", ")});`);
  L.push("}", "", "/// Mesures de mise en page.", "abstract final class TtLayout {");
  const lay = tokens.layout;
  for (const k of ["containerMax", "gutterMobile", "gutterDesktop", "touchTarget", "controlHeight", "sidebarWidth", "topbarHeight", "bottomNavHeight"]) {
    L.push(`  static const double ${k} = ${lay[k]};`);
  }
  L.push(
    `  /// Classes de fenêtre Material 3 : compact < ${lay.windowClass.compact}, medium < ${lay.windowClass.medium}, sinon expanded.`,
    `  static const double compactMax = ${lay.windowClass.compact};`,
    `  static const double mediumMax = ${lay.windowClass.medium};`,
    "}",
    "",
    "/// Familles typographiques de la marque.",
    "abstract final class TtFont {",
    `  static const String display = '${tokens.font.display.family}';`,
    `  static const String body = '${tokens.font.body.family}';`,
    "}",
    "",
    "/// Spécification d'un style de texte (taille desktop/mobile, interligne, graisse, crénage en em).",
    "class TtTextSpec {",
    "  const TtTextSpec({",
    "    required this.display,",
    "    required this.size,",
    "    required this.sizeMobile,",
    "    required this.line,",
    "    required this.weight,",
    "    required this.tracking,",
    "  });",
    "  final bool display;",
    "  final double size;",
    "  final double sizeMobile;",
    "  final double line;",
    "  final FontWeight weight;",
    "  final double tracking;",
    "}",
    "",
    "/// Échelle typographique (même nomenclature que tokens.json).",
    "abstract final class TtType {",
  );
  for (const [name, t] of Object.entries(tokens.type)) {
    L.push(
      `  static const TtTextSpec ${name} = TtTextSpec(display: ${t.font === "display"}, size: ${t.size}, sizeMobile: ${t.sizeMobile}, line: ${t.line}, weight: FontWeight.w${t.weight}, tracking: ${t.tracking});`,
    );
  }
  L.push("}", "");
  return L.join("\n");
}

// ---------- écriture / vérification ----------
const outputs = [{ path: resolve(frontendDir, "src/styles/tokens.css"), content: buildCss() }];
if (existsSync(flutterDir)) {
  outputs.push({ path: resolve(flutterDir, "lib/design/tokens.dart"), content: buildDart() });
} else {
  console.warn(`[ds] Dossier Flutter introuvable (${flutterDir}) — sortie Dart ignorée.`);
}

let stale = false;
for (const { path, content } of outputs) {
  const current = existsSync(path) ? readFileSync(path, "utf8") : null;
  if (check) {
    if (current !== content) {
      stale = true;
      console.error(`[ds] périmé : ${path} — lancez « npm run ds:build ».`);
    }
  } else if (current !== content) {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, content);
    console.log(`[ds] écrit ${path}`);
  } else {
    console.log(`[ds] à jour ${path}`);
  }
}
if (check && stale) process.exit(1);
if (check) console.log("[ds] tokens à jour.");
