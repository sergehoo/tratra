"use client";
import { useCallback, useEffect, useState } from "react";
import { FileCheck2, KeyRound, RotateCcw, ScrollText, ShieldOff } from "lucide-react";
import { Alert, Badge, Button, Card, Modal, TextField, TextareaField } from "@/components/ds";
import { bo, boError } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { ReasonModal, Tag, dt } from "../_components/ui";

/* Modèles juridiques et scellement des contrats. Un modèle n'est utilisable qu'après une revue juridique HUMAINE (droit dédié) ; aucun
   écran ne le présente comme « conforme ». Les clés privées ne quittent jamais le serveur. */

interface Article { number: number; key: string; title: string; body: string; categories?: string[] }
interface LegalRef { label: string; citation: string; status: string }
interface Template {
  id: number; code: string; version: number; title: string; relationship: "employment" | "independent"; status: string; status_label: string;
  categories: { id: number; name: string }[]; reviewed_at: string | null; reviewed_by: { name: string } | null; contracts: number;
  articles?: Article[]; legal_references?: LegalRef[]; review_note?: string;
}
interface DocRow { id: number; reference: string; kind: string; stage: string; version: number; sha256: string; issued_at: string; revoked_at: string | null; revoked_reason: string; public: string; signatures: { role: string; signed_at: string }[] }
interface Key { kid: string; algorithm: string; public_key: string; status: string; created_at: string; retired_at: string | null; revoked_at: string | null }

const TPL_TONE: Record<string, "gray" | "warning" | "success" | "info"> = { draft: "gray", to_review: "warning", validated: "success", retired: "gray" };
const REL_FR = { employment: "Contrat de travail (salarié)", independent: "Prestation indépendante" };
const PUBLIC_FR: Record<string, string> = { authentic: "authentique", superseded: "remplacé", revoked: "révoqué", altered: "altéré", invalid_signature: "scellement invalide", key_revoked: "clé révoquée" };

function TemplateModal({ id, onClose, onChanged }: { id: number | null; onClose: () => void; onChanged: () => void }) {
  const { can } = useBo();
  const [t, setT] = useState<Template | null>(null);
  const [draft, setDraft] = useState<Article[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [review, setReview] = useState({ reviewed_by_name: "", note: "" });
  const load = useCallback(async () => {
    if (id === null) return;
    setError("");
    try {
      const data = await bo.get<Template>(`/engagements/templates/${id}/`);
      setT(data);
      setDraft(data.articles ?? []);
    } catch (e) {
      setError(boError(e, "Modèle indisponible."));
    }
  }, [id]);
  useEffect(() => { setT(null); void load(); }, [load]);

  async function act(path: string, body?: unknown) {
    setBusy(true);
    setError("");
    try {
      const next = await bo.post<Template>(path, body);
      onChanged();
      if (next.id !== id) onClose(); else { setT(next); setDraft(next.articles ?? []); }
    } catch (e) {
      setError(boError(e, "Action impossible. Rien n’a été modifié."));
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    if (!t) return;
    setBusy(true);
    setError("");
    try {
      const next = await bo.patch<Template>(`/engagements/templates/${t.id}/`, { articles: draft });
      setT(next);
      onChanged();
    } catch (e) {
      setError(boError(e, "Enregistrement impossible."));
    } finally {
      setBusy(false);
    }
  }
  const editable = t && (t.status === "draft" || t.status === "to_review") && can("contracts.templates");
  return (
    <Modal open={id !== null} onClose={onClose} size="lg" title={t ? `${t.title} — v${t.version}` : "Modèle de contrat"}>
      {error ? <Alert tone="danger" className="mb-3">{error}</Alert> : null}
      {t ? (
        <div className="space-y-5 text-sm">
          <p className="flex flex-wrap items-center gap-2">
            <Tag value={t.status} label={t.status_label} tone={TPL_TONE[t.status]} /> <span>{REL_FR[t.relationship]}</span>
            <span className="text-ash">· {t.categories.length ? t.categories.map((c) => c.name).join(", ") : "tous les métiers"}</span>
          </p>
          <Alert tone="warning" title="Aucune présomption de conformité">
            Tratra ne qualifie pas la conformité juridique d’un modèle. « Validé par revue juridique » signifie seulement qu’une personne habilitée a
            enregistré la revue d’un juriste sur ce texte exact. Les emplacements « [À compléter par la revue juridique] » doivent être complétés
            avant toute validation.
          </Alert>
          {t.review_note ? <p className="rounded-panel bg-canvas p-3 text-xs text-inkSoft">{t.review_note}</p> : null}
          <div>
            <h3 className="mb-2 font-bold text-ink">Références juridiques proposées</h3>
            <ul className="space-y-1 text-xs text-inkSoft">{(t.legal_references ?? []).map((r, i) => <li key={i}><strong>{r.label}</strong> : {r.citation} — <em>{r.status}</em></li>)}</ul>
          </div>
          <div className="space-y-4">
            <h3 className="font-bold text-ink">Articles</h3>
            {draft.map((a, i) => (
              <div key={`${a.key}-${i}`} className="space-y-2 rounded-panel border border-lineSoft p-3">
                {editable ? (
                  <>
                    <TextField label={`Article ${a.number} — titre`} value={a.title} onChange={(e) => setDraft(draft.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))} />
                    <TextareaField label="Texte" rows={6} value={a.body} onChange={(e) => setDraft(draft.map((x, j) => (j === i ? { ...x, body: e.target.value } : x)))} />
                  </>
                ) : (
                  <>
                    <p className="font-semibold text-ink">Article {a.number} — {a.title}{a.categories?.length ? <Badge tone="gray" className="ml-2">{a.categories.join(", ")}</Badge> : null}</p>
                    <p className="whitespace-pre-line text-inkSoft">{a.body}</p>
                  </>
                )}
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2 border-t border-lineSoft pt-4">
            {editable ? <Button variant="outline" loading={busy} onClick={() => void save()}>Enregistrer le texte (repasse en brouillon)</Button> : null}
            {t.status === "draft" && can("contracts.templates") ? <Button loading={busy} onClick={() => void act(`/engagements/templates/${t.id}/submit/`)}>Soumettre à la revue juridique</Button> : null}
            {t.status === "validated" && can("contracts.templates") ? (
              <>
                <Button variant="outline" loading={busy} onClick={() => void act(`/engagements/templates/${t.id}/new_version/`)}>Créer une nouvelle version</Button>
                <Button variant="ghost" loading={busy} onClick={() => void act(`/engagements/templates/${t.id}/retire/`)}>Retirer</Button>
              </>
            ) : null}
          </div>
          {t.status === "to_review" && can("contracts.legal_review") ? (
            <Card padding="md" className="space-y-3">
              <p className="font-bold text-ink">Enregistrer la revue juridique</p>
              <TextField label="Juriste ou organisme ayant revu le texte" required value={review.reviewed_by_name} onChange={(e) => setReview({ ...review, reviewed_by_name: e.target.value })} />
              <TextareaField label="Note de revue" required rows={3} value={review.note} onChange={(e) => setReview({ ...review, note: e.target.value })} hint="Portée de la revue, réserves, date du texte revu." />
              <Button loading={busy} disabled={review.reviewed_by_name.trim().length < 3 || review.note.trim().length < 10}
                onClick={() => void act(`/engagements/templates/${t.id}/validate/`, review)}>Valider après revue juridique</Button>
            </Card>
          ) : null}
        </div>
      ) : !error ? <p role="status" className="text-sm text-inkSoft">Chargement…</p> : null}
    </Modal>
  );
}

export function TemplatesTab() {
  const [rows, setRows] = useState<Template[] | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const load = useCallback(async () => {
    try {
      const data = await bo.get<{ results: Template[]; notice: string }>("/engagements/templates/");
      setRows(data.results);
      setNotice(data.notice);
    } catch (e) {
      setError(boError(e, "Modèles indisponibles."));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  return (
    <div className="space-y-4">
      {notice ? <Alert tone="info" icon={<ScrollText />}>{notice}</Alert> : null}
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <Card padding="none">
        <ul className="divide-y divide-lineSoft">
          {(rows ?? []).map((t) => (
            <li key={t.id}>
              <button type="button" onClick={() => setOpen(t.id)} className="flex w-full flex-wrap items-center justify-between gap-2 px-4 py-3 text-left hover:bg-canvas">
                <span>
                  <span className="font-semibold text-ink">{t.title}</span> <span className="text-xs text-ash">({t.code} · v{t.version})</span>
                  <span className="block text-xs text-ash">{REL_FR[t.relationship]} · {t.contracts} contrat(s){t.reviewed_at ? ` · revu le ${dt(t.reviewed_at)}${t.reviewed_by ? ` par ${t.reviewed_by.name}` : ""}` : ""}</span>
                </span>
                <Tag value={t.status} label={t.status_label} tone={TPL_TONE[t.status]} />
              </button>
            </li>
          ))}
          {rows && !rows.length ? <li className="px-4 py-6 text-sm text-ash">Aucun modèle.</li> : null}
        </ul>
      </Card>
      <TemplateModal id={open} onClose={() => setOpen(null)} onChanged={() => void load()} />
    </div>
  );
}

export function KeysTab() {
  const [keys, setKeys] = useState<Key[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revoke, setRevoke] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { setKeys((await bo.get<{ results: Key[] }>("/engagements/signing-keys/")).results); } catch (e) { setError(boError(e, "Clés indisponibles.")); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  async function rotate() {
    setBusy(true);
    setError("");
    try { await bo.post("/engagements/signing-keys/", { action: "rotate" }); await load(); } catch (e) { setError(boError(e, "Rotation impossible.")); } finally { setBusy(false); }
  }
  return (
    <div className="space-y-4">
      <Alert tone="info" icon={<KeyRound />}>
        Les documents de contrat sont scellés (Ed25519) par la clé active. Une rotation crée une nouvelle clé ; l’ancienne continue de vérifier ses
        documents. Une révocation (compromission) signale tous les documents scellés par cette clé. Les clés privées sont chiffrées côté serveur et ne
        sont jamais affichées ; les clés publiques sont publiées pour une vérification indépendante.
      </Alert>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <Button leftIcon={<RotateCcw aria-hidden className="h-4 w-4" />} loading={busy} onClick={() => void rotate()}>Nouvelle clé (rotation)</Button>
      <Card padding="none">
        <ul className="divide-y divide-lineSoft">
          {(keys ?? []).map((k) => (
            <li key={k.kid} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <span className="min-w-0">
                <span className="font-mono text-sm font-semibold text-ink">{k.kid}</span> <Tag value={k.status} label={{ active: "Active", retired: "Retirée", revoked: "Révoquée" }[k.status] ?? k.status} tone={k.status === "active" ? "success" : k.status === "revoked" ? "danger" : "gray"} />
                <span className="block break-all font-mono text-[11px] text-ash">{k.algorithm} · {k.public_key}</span>
                <span className="block text-xs text-ash">Créée le {dt(k.created_at)}{k.revoked_at ? ` · révoquée le ${dt(k.revoked_at)}` : ""}</span>
              </span>
              {k.status !== "revoked" ? <Button size="sm" variant="ghost" leftIcon={<ShieldOff aria-hidden className="h-4 w-4" />} onClick={() => setRevoke(k.kid)}>Révoquer</Button> : null}
            </li>
          ))}
        </ul>
      </Card>
      <ReasonModal open={revoke !== null} tone="danger" title="Révoquer cette clé ?" confirmLabel="Révoquer" minReason={10}
        description="Tous les documents qu’elle a scellés seront signalés « clé révoquée » à la vérification. Si c’est la clé active, une nouvelle clé la remplace."
        request={(body) => bo.post("/engagements/signing-keys/", { ...body, action: "revoke", kid: revoke })} onClose={() => setRevoke(null)} onDone={() => { setRevoke(null); void load(); }} />
    </div>
  );
}

/** Documents scellés d'un contrat (fiche Back-Office) : état public et révocation (droit dédié, motif obligatoire, définitive). */
export function DocumentsBlock({ contractId }: { contractId: number }) {
  const { can } = useBo();
  const [rows, setRows] = useState<DocRow[] | null>(null);
  const [revoke, setRevoke] = useState<number | null>(null);
  const load = useCallback(async () => {
    try { setRows((await bo.get<{ results: DocRow[] }>(`/engagements/contracts/${contractId}/documents/`)).results); } catch { setRows([]); }
  }, [contractId]);
  useEffect(() => { void load(); }, [load]);
  if (!rows?.length) return null;
  return (
    <div>
      <h3 className="mb-1 flex items-center gap-1 text-sm font-bold text-ink"><FileCheck2 aria-hidden className="h-4 w-4" />Documents scellés</h3>
      <ul className="space-y-1 text-xs text-inkSoft">
        {rows.map((d) => (
          <li key={d.id} className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-ink">{d.reference}</span> · {d.kind === "amendment" ? "avenant" : d.stage === "final" ? "signé" : "à signer"} · v{d.version} · {dt(d.issued_at)} ·
            <Badge tone={d.public === "authentic" ? "success" : d.public === "superseded" ? "gray" : "danger"}>{PUBLIC_FR[d.public] ?? d.public}</Badge>
            {d.signatures.length ? <span>{d.signatures.length} signature(s)</span> : null}
            {!d.revoked_at && can("contracts.revoke") ? <Button size="sm" variant="ghost" onClick={() => setRevoke(d.id)}>Révoquer</Button> : null}
          </li>
        ))}
      </ul>
      <ReasonModal open={revoke !== null} tone="danger" title="Révoquer ce document ?" confirmLabel="Révoquer définitivement" minReason={10}
        description="La vérification publique affichera « révoqué ». Le fichier et son empreinte restent conservés ; la révocation ne peut pas être annulée."
        request={(body) => bo.post(`/engagements/documents/${revoke}/revoke/`, body)} onClose={() => setRevoke(null)} onDone={() => { setRevoke(null); void load(); }} />
    </div>
  );
}
