/**
 * Mise en forme SÛRE des réponses de l'assistant : seuls le gras (**…**), les listes à puces et les liens INTERNES du Back-Office
 * (`[libellé](/backoffice/…)`) sont reconnus. Aucun HTML n'est jamais interprété et aucun lien externe, `javascript:` ou protocole relatif
 * n'est rendu cliquable : un texte inséré par un utilisateur (nom, message, avis) ne peut donc pas injecter de lien ni de balise.
 * Fonctions pures (testées par `npm run test:bo`).
 */
export type Inline = { t: "text"; v: string } | { t: "bold"; v: string } | { t: "link"; v: string; href: string };
export type Block = { t: "p"; inline: Inline[] } | { t: "ul"; items: Inline[][] };

const LINK = /\[([^\]\n]{1,120})\]\((\/backoffice(?:[/?#][A-Za-z0-9_\-./?=&%#]*)?)\)/;
const BOLD = /\*\*([^*\n]{1,200})\*\*/;

/** Lien interne autorisé : chemin absolu sous /backoffice, sans « // », sans « .. », sans protocole. */
export function isInternalBackofficeHref(href: string): boolean {
  return /^\/backoffice(?:[/?#][A-Za-z0-9_\-./?=&%#]*)?$/.test(href) && !href.includes("//") && !href.includes("..");
}

export function parseInline(line: string): Inline[] {
  const out: Inline[] = [];
  let rest = line;
  while (rest) {
    const link = LINK.exec(rest);
    const bold = BOLD.exec(rest);
    const next = [link, bold].filter((m): m is RegExpExecArray => m !== null).sort((a, b) => a.index - b.index)[0];
    if (!next) {
      out.push({ t: "text", v: rest });
      break;
    }
    if (next.index > 0) out.push({ t: "text", v: rest.slice(0, next.index) });
    if (next === link) {
      if (isInternalBackofficeHref(link[2])) out.push({ t: "link", v: link[1], href: link[2] });
      else out.push({ t: "text", v: link[1] });
    } else {
      out.push({ t: "bold", v: next[1] });
    }
    rest = rest.slice(next.index + next[0].length);
  }
  return out;
}

export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let list: Inline[][] | null = null;
  for (const raw of text.replace(/\r/g, "").split("\n")) {
    const line = raw.trimEnd();
    const bullet = /^\s*(?:[-*•])\s+(.*)$/.exec(line);
    if (bullet) {
      if (!list) {
        list = [];
        blocks.push({ t: "ul", items: list });
      }
      list.push(parseInline(bullet[1]));
      continue;
    }
    list = null;
    if (line.trim()) blocks.push({ t: "p", inline: parseInline(line.trim()) });
  }
  return blocks;
}
