/**
 * Lecture du flux SSE de Tratra AI (`POST /backoffice/assistant/chat/`). Fonctions pures, testées par `npm run test:bo`.
 * Un bloc SSE = lignes « event: nom » et « data: {json} », séparé du suivant par une ligne vide ; les lignes « : ping » sont ignorées.
 */
export type StreamEvent =
  | { type: "meta"; conversation: number; message: number }
  | { type: "status"; tool: string; label: string }
  | { type: "delta"; text: string }
  | { type: "done"; message: number; content: string; sources: { tool: string; label: string; ok: boolean }[]; provider: string; usage: { tokens_in: number; tokens_out: number } }
  | { type: "error"; code: string; detail: string; message?: number };

/** Découpe un tampon en événements complets ; renvoie aussi le reste (bloc incomplet) à compléter au prochain morceau reçu. */
export function parseSse(buffer: string): { events: StreamEvent[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: StreamEvent[] = [];
  for (const block of blocks) {
    const data = block
      .split("\n")
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).trimStart())
      .join("\n");
    if (!data) continue;
    try {
      const parsed = JSON.parse(data) as StreamEvent;
      if (parsed && typeof parsed === "object" && typeof parsed.type === "string") events.push(parsed);
    } catch {
      /* bloc illisible : ignoré, jamais une erreur affichée à l'utilisateur */
    }
  }
  return { events, rest };
}
