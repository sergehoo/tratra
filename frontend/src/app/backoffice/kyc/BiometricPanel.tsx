"use client";
import { useCallback, useEffect, useState } from "react";
import { ScanFace } from "lucide-react";
import { Alert, Badge, Button, Modal, type BadgeTone } from "@/components/ds";
import { apiFetch } from "@/lib/api";
import { bo, boError } from "@/lib/bo";
import { KV, ReasonModal, Section, dt } from "../_components/ui";

interface Capture { id: number; index: number; kind: string; deleted: boolean; quality: { brightness?: number; sharpness?: number } }
interface Session {
  id: number; attempt: number; status: string; outcome: string; outcome_label: string; anomalies: string[]; provider: string; created_at: string; completed_at: string | null;
  challenges: string[]; liveness_passed?: boolean | null; liveness_score?: number | null; match_score?: number | null; thresholds?: { liveness: number; match: number }; captures?: Capture[];
}
interface Report {
  status: string; status_label: string; satisfied: boolean; can_view_captures: boolean; can_decide_biometric: boolean; enabled: boolean;
  document: { document_status: string | null; analysis: { risk_label: string; summary: string; ai_report: string; checks: { code: string; status: string; label: string; detail: string }[]; disclaimer: string } | null };
  sessions: Session[]; decisions: { decision: string; decision_label: string; reason: string; at: string; by: string | null }[]; missing_checks: string[];
  human_review_requested_at?: string | null; human_review_reason?: string; decision_reason?: string; decided_at?: string | null; decided_by?: string | null;
  consent: { version: string; granted_at: string; withdrawn_at: string | null } | null;
}

const TONE: Record<string, BadgeTone> = { passed: "success", manual_approved: "success", alternative_approved: "success", pending_review: "warning", in_progress: "info", inconclusive: "warning", failed: "danger", rejected: "danger", recapture_requested: "warning", documents_requested: "warning", not_started: "gray" };
const ANOMALY_FR: Record<string, string> = { too_fast: "enchaînement trop rapide", identical_frames: "images identiques", capture_reused_elsewhere: "image déjà vue dans un autre compte", document_not_comparable: "pièce non comparable (PDF)" };
const KIND_FR: Record<string, string> = { front: "face", left: "gauche", right: "droite", up: "haut", down: "bas", smile: "sourire" };
const HELP_REASON: Record<string, string> = { no_provider: "aucun fournisseur de vérification configuré", provider_unavailable: "fournisseur indisponible", camera_refused: "caméra refusée", accessibility: "alternative accessible demandée", other: "demande de l’utilisateur" };
const DECISIONS: Record<string, { label: string; tone: "primary" | "danger"; help: string; bio: boolean }> = {
  request_recapture: { label: "Demander une nouvelle capture", tone: "primary", help: "L’utilisateur est invité à refaire la vérification faciale.", bio: false },
  request_documents: { label: "Demander des pièces complémentaires", tone: "primary", help: "Précisez les pièces attendues dans le motif ; l’utilisateur est notifié.", bio: false },
  open_review: { label: "Ouvrir une revue manuelle", tone: "primary", help: "Le dossier passe en attente de revue humaine.", bio: false },
  approve_manual: { label: "Approuver après revue", tone: "primary", help: "Réservé aux contrôles requis : pièce d’identité approuvée et aucune alerte biométrique active. Décision humaine, journalisée.", bio: true },
  approve_alternative: { label: "Approuver la procédure alternative", tone: "primary", help: "Identité vérifiée par un moyen alternatif (agence, appel…). Décrivez la procédure dans le motif.", bio: true },
  reject: { label: "Refuser", tone: "danger", help: "L’utilisateur est informé et peut former un recours auprès du support.", bio: true },
};

function CaptureViewer({ capture, onClose }: { capture: Capture | null; onClose: () => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false, made: string | null = null;
    setUrl(null); setError("");
    if (!capture) return;
    (async () => {
      try {
        const res = await apiFetch(`/backoffice/kyc/biometric/captures/${capture.id}/`);
        if (!res.ok) throw new Error(String(res.status));
        made = URL.createObjectURL(await res.blob());
        if (!cancelled) setUrl(made);
      } catch { if (!cancelled) setError("La capture n’a pas pu être ouverte (supprimée ou droits insuffisants)."); }
    })();
    return () => { cancelled = true; if (made) URL.revokeObjectURL(made); };
  }, [capture]);
  return (
    <Modal open={Boolean(capture)} onClose={onClose} size="lg" title={capture ? `Capture ${KIND_FR[capture.kind] ?? capture.kind}` : ""} description="Donnée biométrique confidentielle : ne la copiez pas et ne la transmettez pas. Chaque ouverture est journalisée à votre nom.">
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      {url ? <img src={url} alt="Capture du visage" className="mx-auto max-h-[70vh] rounded-panel border border-lineSoft object-contain" /> : !error ? <p className="text-sm text-inkSoft" role="status">Ouverture sécurisée…</p> : null}
    </Modal>
  );
}

/** Vérification faciale : statut, tentatives, anomalies, rapport, décisions. Scores et captures réservés au droit « données biométriques ». */
export function BiometricPanel({ profileId, canReview, onChanged }: { profileId: number; canReview: boolean; onChanged: () => void }) {
  const [r, setR] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [act, setAct] = useState<string | null>(null);
  const [view, setView] = useState<Capture | null>(null);
  const load = useCallback(async () => {
    setError("");
    try { setR(await bo.get<Report>(`/kyc/${profileId}/biometric/`)); } catch (e) { setError(boError(e, "La vérification faciale n’a pas pu être chargée.")); }
  }, [profileId]);
  useEffect(() => void load(), [load]);

  if (error && !r) return <Alert tone="danger" action={<Button size="sm" variant="outline" onClick={() => void load()}>Réessayer</Button>}>{error}</Alert>;
  if (!r) return <p className="text-sm text-inkSoft" role="status">Chargement…</p>;
  const decisions = Object.entries(DECISIONS).filter(([, d]) => canReview && (!d.bio || r.can_decide_biometric));
  const doc = r.document;

  return (
    <div className="space-y-6">
      <Section title="Vérification faciale" actions={<Badge tone={TONE[r.status] ?? "gray"} icon={<ScanFace />}>{r.status_label}</Badge>}>
        <KV items={[["Fonction", r.enabled ? "Activée" : "Désactivée sur ce serveur"], ["Pièce d’identité", doc.document_status ?? "aucune"], ["Consentement", r.consent ? `${r.consent.version} · ${dt(r.consent.granted_at)}${r.consent.withdrawn_at ? ` · retiré le ${dt(r.consent.withdrawn_at)}` : ""}` : "aucun"],
          ["Revue humaine demandée", r.human_review_requested_at ? `${dt(r.human_review_requested_at)} (${HELP_REASON[r.human_review_reason ?? ""] ?? r.human_review_reason})` : "non"],
          ["Dernière décision", r.decided_at ? `${dt(r.decided_at)}${r.decided_by ? ` · ${r.decided_by}` : ""} — ${r.decision_reason}` : "aucune"]]} />
        <p className="mt-3 text-xs text-ash">Le badge « Vérifié » exige un KYC approuvé et, si la politique est activée, une vérification faciale satisfaisante ou une procédure alternative approuvée. Aucune validation automatique : sans fournisseur, le dossier reste en attente de revue humaine.</p>
        {r.missing_checks.length ? <Alert tone="warning" className="mt-3" title="Contrôles requis avant approbation">{r.missing_checks.join(" · ")}</Alert> : <Alert tone="success" className="mt-3">Contrôles requis réunis : l’approbation est possible.</Alert>}
        {decisions.length ? <div className="mt-4 flex flex-wrap gap-2">{decisions.map(([id, d]) => <Button key={id} size="sm" variant={d.tone === "danger" ? "danger" : id.startsWith("approve") ? "primary" : "outline"} onClick={() => setAct(id)}>{d.label}</Button>)}</div> : null}
        {!r.can_decide_biometric ? <p className="mt-3 text-xs text-ash">Approuver, refuser et consulter les captures du visage sont réservés aux administrateurs autorisés (droit « données biométriques »).</p> : null}
      </Section>

      <Section title="Rapport documentaire (aide à la décision)">
        {doc.analysis ? (
          <>
            <p className="text-sm text-inkSoft">Risque : <strong>{doc.analysis.risk_label}</strong>. {doc.analysis.summary}</p>
            {doc.analysis.ai_report ? <p className="mt-2 rounded-panel bg-canvas p-3 text-sm text-inkSoft"><strong>Rapport IA :</strong> {doc.analysis.ai_report}</p> : null}
            <ul className="mt-2 grid gap-1 text-xs text-inkSoft sm:grid-cols-2">{doc.analysis.checks.map((c) => <li key={c.code}><Badge tone={c.status === "ok" ? "success" : c.status === "fail" ? "danger" : c.status === "warn" ? "warning" : "gray"}>{c.status}</Badge> {c.label}{c.detail ? ` — ${c.detail}` : ""}</li>)}</ul>
            <p className="mt-2 text-xs text-ash">{doc.analysis.disclaimer}</p>
          </>
        ) : <p className="text-sm text-inkSoft">Aucune analyse : lancez « Analyse assistée » depuis l’onglet Documents.</p>}
      </Section>

      <Section title="Historique des tentatives">
        {r.sessions.length === 0 ? <p className="text-sm text-inkSoft">Aucune tentative.</p> : (
          <ul className="space-y-3">
            {r.sessions.map((s) => (
              <li key={s.id} className="rounded-panel border border-lineSoft p-3 text-sm">
                <p className="flex flex-wrap items-center gap-2 font-semibold text-ink">Tentative {s.attempt} <Badge tone={TONE[s.outcome] ?? "gray"}>{s.outcome_label}</Badge><span className="font-normal text-ash">{dt(s.created_at)} · fournisseur : {s.provider}</span></p>
                {s.anomalies.length ? <p className="mt-1 text-xs text-warningInk">Anomalies : {s.anomalies.map((a) => ANOMALY_FR[a] ?? a.replace("provider:", "fournisseur : ")).join(", ")}</p> : null}
                {s.liveness_score !== undefined ? <p className="mt-1 text-xs text-inkSoft">Liveness : {s.liveness_passed === null ? "—" : s.liveness_passed ? "réussi" : "échoué"}{s.liveness_score != null ? ` (${s.liveness_score})` : ""} · Correspondance visage/pièce : {s.match_score ?? "—"} · Seuils : {s.thresholds?.liveness} / {s.thresholds?.match}</p> : null}
                {s.captures?.length ? <p className="mt-2 flex flex-wrap gap-1.5">{s.captures.map((c) => <Button key={c.id} size="sm" variant="outline" disabled={c.deleted} onClick={() => setView(c)}>{KIND_FR[c.kind] ?? c.kind}{c.deleted ? " (supprimée)" : ""}</Button>)}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Décisions">
        {r.decisions.length === 0 ? <p className="text-sm text-inkSoft">Aucune décision.</p> : <ol className="space-y-2">{r.decisions.map((d, i) => <li key={i} className="rounded-panel border border-lineSoft p-3 text-sm"><p className="font-semibold text-ink">{d.decision_label} <span className="font-normal text-ash">· {dt(d.at)}{d.by ? ` · ${d.by}` : ""}</span></p><p className="mt-0.5 text-inkSoft">{d.reason}</p></li>)}</ol>}
      </Section>

      <ReasonModal open={Boolean(act)} title={act ? DECISIONS[act].label : ""} description={act ? DECISIONS[act].help : undefined} confirmLabel={act ? DECISIONS[act].label : "Confirmer"} tone={act ? DECISIONS[act].tone : "primary"}
        reasonLabel="Motif (10 caractères minimum, conservé dans l’historique)" onClose={() => setAct(null)} request={act ? (b) => bo.post(`/kyc/${profileId}/biometric/decision/`, { decision: act, reason: b.reason }) : async () => undefined}
        onDone={() => { setAct(null); void load(); onChanged(); }} />
      <CaptureViewer capture={view} onClose={() => setView(null)} />
    </div>
  );
}
