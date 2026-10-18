"use client";
import { useEffect, useId, useState } from "react";
import { Info, Sparkles } from "lucide-react";
import { Alert, Button, Select } from "@/components/ds";
import { assistantApi, draftApi, type DraftMode, type DraftResult } from "@/lib/assistant";
import { boError } from "@/lib/bo";

const MODES: { id: DraftMode; label: string; needsText: boolean }[] = [
  { id: "compose", label: "Rédiger à partir d’une consigne", needsText: false },
  { id: "rewrite", label: "Reformuler mon texte", needsText: true },
  { id: "correct", label: "Corriger l’orthographe et la grammaire", needsText: true },
  { id: "professional", label: "Prendre un ton professionnel", needsText: true },
  { id: "shorten", label: "Raccourcir", needsText: true },
];

let statusMemo: Promise<boolean | null> | null = null;
/** « IA configurée ? » — une seule requête par chargement de page ; `null` = inconnu (le serveur tranchera à la demande). */
function aiConfigured(): Promise<boolean | null> {
  statusMemo ??= assistantApi.status().then((s) => s.configured).catch(() => null);
  return statusMemo;
}

/**
 * « Rédiger avec l'IA » : propose, reformule, corrige ou adapte le ton d'un message. C'est une PROPOSITION affichée à part : elle ne remplace
 * le texte qu'après « Utiliser cette proposition », et rien n'est jamais envoyé d'ici (l'envoi reste une action humaine, après relecture).
 */
export function AiDraftBar({ text, purpose = "service", thread, onUse }: { text: string; purpose?: string; thread?: number; onUse: (draft: string) => void }) {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<DraftMode>("compose");
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<DraftResult | null>(null);
  const panel = useId();
  useEffect(() => { void aiConfigured().then(setConfigured); }, []);

  const current = MODES.find((m) => m.id === mode)!;
  const missing = current.needsText ? !text.trim() : !instruction.trim() && !text.trim();

  async function generate() {
    setBusy(true);
    setError("");
    try {
      setResult(await draftApi.create({ mode, text: text.trim() || undefined, instruction: instruction.trim() || undefined, purpose, thread }));
    } catch (e) {
      setResult(null);
      setError(boError(e, "La proposition n’a pas pu être générée."));
    } finally {
      setBusy(false);
    }
  }

  const off = configured === false;
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="soft" size="sm" leftIcon={<Sparkles aria-hidden className="h-4 w-4" />} aria-expanded={open} aria-controls={panel} disabled={off} title={off ? "IA non configurée" : undefined} onClick={() => setOpen((v) => !v)}>Rédiger avec l’IA</Button>
        {off ? <span className="text-xs font-semibold text-ash">IA non configurée</span> : null}
      </div>
      {open && !off ? (
        <div id={panel} className="mt-2 space-y-3 rounded-2xl border border-primary/30 bg-primarySoft/30 p-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-xs font-semibold text-ink">Action
              <Select value={mode} onChange={(e) => { setMode(e.target.value as DraftMode); setResult(null); }}>{MODES.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}</Select>
            </label>
            <label className="text-xs font-semibold text-ink">{mode === "compose" ? "Consigne" : "Précision (facultatif)"}
              <input value={instruction} maxLength={500} onChange={(e) => setInstruction(e.target.value)} placeholder={mode === "compose" ? "Ex. : prévenir que le dossier est complet" : "Ex. : plus chaleureux"} className="mt-1 min-h-11 w-full rounded-xl border border-line bg-white px-3 text-sm font-normal focus:border-primary focus:outline-none" />
            </label>
          </div>
          {current.needsText && !text.trim() ? <p className="text-xs text-warningInk">Écrivez d’abord le texte à retravailler dans le champ du message.</p> : null}
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" loading={busy} disabled={missing} onClick={() => void generate()}>{result ? "Régénérer" : "Générer une proposition"}</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => { setOpen(false); setResult(null); setError(""); }}>Fermer</Button>
          </div>
          <p className="flex items-start gap-1.5 text-[11px] leading-snug text-ash"><Info aria-hidden className="mt-0.5 h-3 w-3 shrink-0" />Le texte, la consigne et, pour une réponse, les derniers messages du fil (coordonnées masquées) sont transmis au fournisseur d’IA. Rien n’est envoyé au membre.</p>
          {error ? <Alert tone={error.includes("non configurée") ? "warning" : "danger"}>{error}</Alert> : null}
          {result ? (
            <div className="space-y-2 rounded-xl border border-line bg-white p-3" aria-live="polite">
              <p className="text-xs font-bold uppercase tracking-wide text-ash">Proposition de l’IA</p>
              <blockquote className="whitespace-pre-wrap rounded-lg bg-surface p-3 text-sm text-ink">{result.draft}</blockquote>
              {result.notes ? <p className="text-xs text-inkSoft"><span className="font-semibold">À vérifier : </span>{result.notes}</p> : null}
              <p className="text-xs text-ash">{result.note}</p>
              <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" onClick={() => { onUse(result.draft); setResult(null); setOpen(false); }}>Utiliser cette proposition</Button>
                <Button type="button" size="sm" variant="outline" onClick={() => setResult(null)}>Ignorer</Button>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
