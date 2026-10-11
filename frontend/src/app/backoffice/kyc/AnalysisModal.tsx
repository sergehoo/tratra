"use client";
import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Modal, type BadgeTone } from "@/components/ds";
import { bo, boError } from "@/lib/bo";
import { dt } from "../_components/ui";

interface Check { code: string; status: "ok" | "warn" | "fail" | "unknown"; label: string; detail: string }
interface Analysis { id: number; created_at: string; risk_level: string; risk_label: string; summary: string; checks: Check[]; fields: Record<string, string>; ocr_engine: string; external_used: boolean; disclaimer: string }
interface Last { analysis: Analysis | null; ai: { kyc_external_allowed: boolean }; local_ocr: boolean }

const TONE: Record<string, BadgeTone> = { ok: "success", warn: "warning", fail: "danger", unknown: "gray" };
const LABEL: Record<string, string> = { ok: "Conforme", warn: "À vérifier", fail: "Anomalie", unknown: "Indéterminé" };
const RISK_TONE: Record<string, BadgeTone> = { low: "success", medium: "warning", high: "danger", unknown: "gray" };

/** Analyse assistée d'une pièce : contrôles explicables. Indicatif uniquement — la décision reste celle de l'équipe KYC. */
export function AnalysisModal({ docId, title, onClose }: { docId: number | null; title: string; onClose: () => void }) {
  const [last, setLast] = useState<Last | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (id: number) => {
    setError(""); setLast(null);
    try { setLast(await bo.get<Last>(`/kyc/documents/${id}/analysis/`)); } catch (e) { setError(boError(e, "L’analyse n’a pas pu être chargée.")); }
  }, []);
  useEffect(() => { if (docId) void load(docId); }, [docId, load]);

  async function run() {
    if (!docId) return;
    setBusy(true); setError("");
    try { const a = await bo.post<Analysis>(`/kyc/documents/${docId}/analyze/`); setLast((l) => ({ analysis: a, ai: l?.ai ?? { kyc_external_allowed: false }, local_ocr: l?.local_ocr ?? false })); }
    catch (e) { setError(boError(e, "L’analyse a échoué.")); } finally { setBusy(false); }
  }
  const a = last?.analysis;

  return (
    <Modal open={docId !== null} onClose={() => !busy && onClose()} title={`Analyse assistée — ${title}`} size="lg"
      description="Indicatif : l’IA et les règles proposent, l’équipe KYC décide. Aucune approbation, aucun refus ni aucun badge n’est déclenché par cette analyse."
      footer={<><Button variant="outline" onClick={onClose} disabled={busy}>Fermer</Button><Button onClick={() => void run()} loading={busy}>{a ? "Relancer l’analyse" : "Lancer l’analyse"}</Button></>}>
      <div className="space-y-4">
        {error ? <Alert tone="danger">{error}</Alert> : null}
        {last && !a ? <Alert tone="info">Aucune analyse pour cette pièce. {last.local_ocr ? "La lecture automatique locale est disponible." : "Aucun OCR local n’est installé : le contrôle restera en partie manuel."} {last.ai.kyc_external_allowed ? "L’envoi à un fournisseur externe est autorisé par la configuration." : "Aucun document n’est envoyé à un fournisseur externe."}</Alert> : null}
        {a ? (
          <>
            <div className="flex flex-wrap items-center gap-2"><Badge tone={RISK_TONE[a.risk_level] ?? "gray"}>Risque {a.risk_label.toLowerCase()}</Badge><span className="text-xs text-ash">{dt(a.created_at)} · lecture : {a.ocr_engine === "none" ? "aucune" : a.ocr_engine}{a.external_used ? " · fournisseur externe utilisé" : " · traitement local"}</span></div>
            <p className="text-sm text-inkSoft">{a.summary}</p>
            <ul className="divide-y divide-lineSoft rounded-panel border border-lineSoft">
              {a.checks.map((c) => (
                <li key={c.code} className="flex flex-wrap items-start justify-between gap-2 p-3 text-sm"><div className="min-w-0"><p className="font-semibold text-ink">{c.label}</p>{c.detail ? <p className="text-xs text-inkSoft">{c.detail}</p> : null}</div><Badge tone={TONE[c.status]}>{LABEL[c.status]}</Badge></li>
              ))}
            </ul>
            {Object.keys(a.fields).length ? (
              <details className="rounded-panel bg-canvas p-3 text-sm"><summary className="cursor-pointer font-semibold text-ink">Champs lus automatiquement (numéro masqué)</summary>
                <dl className="mt-2 grid gap-1 sm:grid-cols-2">{Object.entries(a.fields).map(([k, v]) => <div key={k}><dt className="text-xs text-ash">{k.replace(/_/g, " ")}</dt><dd className="font-semibold text-ink">{v}</dd></div>)}</dl>
              </details>
            ) : null}
            <p className="text-xs text-ash">{a.disclaimer}</p>
          </>
        ) : null}
      </div>
    </Modal>
  );
}
