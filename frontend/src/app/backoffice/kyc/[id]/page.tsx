"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { CircleCheck, Circle } from "lucide-react";
import { Alert, Badge, Button, ConfirmDialog, Modal, PageHeader, SkeletonPage, type BadgeTone } from "@/components/ds";
import { apiFetch } from "@/lib/api";
import { bo, boError, errorCode } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { KV, ReasonModal, Section, dt, postTo } from "../../_components/ui";

interface Doc {
  id: number;
  type: string;
  type_label: string;
  status: "pending" | "approved" | "rejected";
  uploaded_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
  rejection_reason: string;
  title: string;
  issuer: string;
  expires_on: string | null;
  file_path: string | null;
}
interface Detail {
  profile_id: number;
  user_id: number;
  name: string;
  commune: string | null;
  state: string;
  state_label: string;
  is_approved: boolean;
  publishable: boolean;
  account_active: boolean;
  documents: Doc[];
  documents_summary: { pending: number; approved: number; rejected: number };
  checklist: { key: string; label: string; hint: string; done: boolean }[];
  history: { action: string; at: string; by: string; reason: string }[];
}

const TONE: Record<string, BadgeTone> = { pending: "warning", approved: "success", rejected: "danger" };
const DOC_FR = { pending: "À examiner", approved: "Approuvée", rejected: "Refusée" } as const;

/** Pièce d'identité : lue par un endpoint protégé (jeton, no-store), jamais par une URL de stockage ; chaque ouverture est journalisée. */
function DocumentViewer({ doc, onClose }: { doc: Doc | null; onClose: () => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [type, setType] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const created = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setUrl(null);
    setError("");
    if (!doc?.file_path) return;
    setLoading(true);
    (async () => {
      try {
        const res = await apiFetch(doc.file_path!.replace(/^\/handy/, ""));
        if (!res.ok) throw new Error(String(res.status));
        const blob = await res.blob();
        if (cancelled) return;
        const objectUrl = URL.createObjectURL(blob);
        created.current = objectUrl;
        setType(blob.type);
        setUrl(objectUrl);
      } catch {
        if (!cancelled) setError("Le document n’a pas pu être ouvert (introuvable ou droits insuffisants).");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      if (created.current) URL.revokeObjectURL(created.current);
      created.current = null;
    };
  }, [doc]);

  return (
    <Modal open={Boolean(doc)} onClose={onClose} size="lg" title={doc ? `${doc.type_label}` : ""} description="Pièce confidentielle : ne la copiez ni ne la partagez. Cette consultation est journalisée.">
      {loading ? <p className="text-sm text-inkSoft" role="status">Ouverture sécurisée…</p> : null}
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {url && type.startsWith("image/") ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url} alt={`Pièce : ${doc?.type_label ?? ""}`} className="max-h-[70vh] w-full rounded-panel border border-lineSoft object-contain" />
      ) : null}
      {url && !type.startsWith("image/") ? (
        <Alert tone="info" action={<a href={url} download="document" className="text-sm font-semibold underline">Télécharger</a>}>
          Ce format ne s’affiche pas dans la page : téléchargez-le pour le consulter.
        </Alert>
      ) : null}
    </Modal>
  );
}

export default function KycDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useBo();
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [failure, setFailure] = useState("");
  const [view, setView] = useState<Doc | null>(null);
  const [reject, setReject] = useState<Doc | null>(null);
  const [approveDoc, setApproveDoc] = useState<Doc | null>(null);
  const [busy, setBusy] = useState(false);
  const [suspend, setSuspend] = useState(false);
  const [approveProfile, setApproveProfile] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      setD(await bo.get<Detail>(`/kyc/${id}/`));
    } catch (e) {
      setError(boError(e, "Ce dossier n’a pas pu être chargé."));
    }
  }, [id]);
  useEffect(() => void load(), [load]);

  async function run(fn: () => Promise<unknown>, done: string) {
    setBusy(true);
    setFailure("");
    try {
      await fn();
      setNotice(done);
      setApproveDoc(null);
      setApproveProfile(false);
      await load();
    } catch (e) {
      setFailure(errorCode(e) === "kyc_incomplete" ? "La pièce d’identité doit d’abord être approuvée : le dossier ne peut pas être approuvé sans elle." : boError(e, "L’opération a échoué. Rien n’a été modifié."));
      setApproveDoc(null);
      setApproveProfile(false);
    } finally {
      setBusy(false);
    }
  }

  if (error && !d) {
    return (
      <>
        <PageHeader title="Dossier KYC" back={{ href: "/backoffice/kyc", label: "Vérification KYC" }} />
        <Alert tone="danger" title="Dossier indisponible" action={<Button size="sm" variant="outline" onClick={() => void load()}>Réessayer</Button>}>{error}</Alert>
      </>
    );
  }
  if (!d) return <SkeletonPage />;
  const manage = can("kyc.review");
  return (
    <>
      <PageHeader
        title={d.name}
        eyebrow={`Dossier #${d.profile_id}`}
        back={{ href: "/backoffice/kyc", label: "Vérification KYC" }}
        description={`${d.state_label}${d.commune ? ` · ${d.commune}` : ""}`}
        actions={manage ? (
          d.is_approved ? <Button variant="danger" size="sm" onClick={() => setSuspend(true)}>Suspendre le dossier</Button>
            : <Button size="sm" disabled={d.documents_summary.approved === 0} onClick={() => setApproveProfile(true)}>Approuver le dossier</Button>
        ) : null}
      />
      {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}
      {failure ? <Alert tone="danger" className="mb-4">{failure}</Alert> : null}
      {!d.account_active ? <Alert tone="warning" className="mb-4">Le compte de cet artisan est suspendu : il n’est ni publié ni éligible aux missions.</Alert> : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <Section title="Pièces du dossier" className="lg:col-span-2">
          {d.documents.length === 0 ? <p className="text-sm text-inkSoft">Aucune pièce déposée.</p> : (
            <ul className="divide-y divide-lineSoft">
              {d.documents.map((doc) => (
                <li key={doc.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <p className="font-semibold text-ink">{doc.type_label}{doc.title ? ` — ${doc.title}` : ""}</p>
                    <p className="text-xs text-ash">Déposée le {dt(doc.uploaded_at)}{doc.issuer ? ` · ${doc.issuer}` : ""}{doc.expires_on ? ` · expire le ${doc.expires_on}` : ""}</p>
                    {doc.status !== "pending" ? <p className="mt-0.5 text-xs text-inkSoft">Décision de {doc.reviewed_by ?? "—"} le {dt(doc.reviewed_at)}{doc.rejection_reason ? ` — motif : ${doc.rejection_reason}` : ""}</p> : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={TONE[doc.status]}>{DOC_FR[doc.status]}</Badge>
                    {doc.file_path && manage ? <Button size="sm" variant="outline" onClick={() => setView(doc)}>Voir la pièce</Button> : null}
                    {manage && doc.status === "pending" ? (
                      <>
                        <Button size="sm" onClick={() => setApproveDoc(doc)}>Approuver</Button>
                        <Button size="sm" variant="danger" onClick={() => setReject(doc)}>Refuser</Button>
                      </>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Éligibilité aux missions">
          <p className="mb-3 text-xs text-ash">Même règle que la publication : tout doit être validé pour que l’artisan reçoive des missions.</p>
          <ul className="space-y-2.5">
            {d.checklist.map((c) => (
              <li key={c.key} className="flex items-start gap-2.5 text-sm">
                {c.done ? <CircleCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-success" /> : <Circle aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-fog" />}
                <span><span className={c.done ? "text-ink" : "font-semibold text-ink"}>{c.label}</span>{!c.done ? <span className="block text-xs text-ash">{c.hint}</span> : null}</span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-sm font-semibold">{d.publishable ? <span className="text-successInk">Publiable et éligible aux missions</span> : <span className="text-warningInk">Non publiable pour le moment</span>}</p>
        </Section>

        <Section title="Historique" className="lg:col-span-3">
          {d.history.length ? (
            <ul className="divide-y divide-lineSoft text-sm">
              {d.history.map((h, i) => <li key={i} className="py-2"><strong>{h.action.replace("backoffice.", "")}</strong> — {h.by} · {dt(h.at)}{h.reason ? <span className="block text-inkSoft">Motif : {h.reason}</span> : null}</li>)}
            </ul>
          ) : <KV items={[["Décisions", "Aucune décision enregistrée sur ce dossier."]]} />}
        </Section>
      </div>

      <DocumentViewer doc={view} onClose={() => setView(null)} />
      <ConfirmDialog
        open={Boolean(approveDoc)}
        onClose={() => setApproveDoc(null)}
        title="Approuver cette pièce ?"
        description={`${approveDoc?.type_label ?? ""} — l’artisan en sera informé. Cette décision ne se modifie pas en silence.`}
        confirmLabel="Approuver"
        loading={busy}
        onConfirm={() => approveDoc && void run(() => bo.post(`/kyc/documents/${approveDoc.id}/review/`, { action: "approve" }), "Pièce approuvée.")}
      />
      <ReasonModal
        open={Boolean(reject)}
        title="Refuser cette pièce ?"
        description="L’artisan reçoit ce motif et pourra déposer une nouvelle pièce."
        confirmLabel="Refuser la pièce"
        tone="danger"
        onClose={() => setReject(null)}
        request={(b) => bo.post(`/kyc/documents/${reject?.id}/review/`, { action: "reject", reason: b.reason })}
        onDone={() => { setReject(null); setNotice("Pièce refusée."); void load(); }}
      />
      <ConfirmDialog
        open={approveProfile}
        onClose={() => setApproveProfile(false)}
        title="Approuver ce dossier ?"
        description="L’artisan devient publiable et éligible aux missions s’il remplit les autres conditions. L’approbation est une décision humaine, journalisée."
        confirmLabel="Approuver le dossier"
        loading={busy}
        onConfirm={() => void run(() => bo.post(`/kyc/${d.profile_id}/approve/`, {}), "Dossier approuvé.")}
      />
      <ReasonModal
        open={suspend}
        title="Suspendre ce dossier ?"
        description="Retrait immédiat de la publication, des missions et du Tratra ID de cet artisan. Ses réservations en cours ne sont pas annulées."
        confirmLabel="Suspendre"
        tone="danger"
        onClose={() => setSuspend(false)}
        request={postTo(`/kyc/${d.profile_id}/suspend/`)}
        onDone={() => { setSuspend(false); setNotice("Dossier suspendu."); void load(); }}
      />
    </>
  );
}
