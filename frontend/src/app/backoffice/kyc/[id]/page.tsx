"use client";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { CircleCheck, Circle } from "lucide-react";
import { Alert, Badge, Button, ConfirmDialog, PageHeader, SkeletonPage, type BadgeTone } from "@/components/ds";
import { bo, boError, errorCode } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import Link from "next/link";
import { DocumentViewer, type Doc } from "../../_components/DocumentViewer";
import { useCrumb } from "../../_components/crumbs";
import { Fiche, Pane, Restricted } from "../../_components/fiche";
import { KV, ReasonModal, Section, dt, postTo } from "../../_components/ui";

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
  useCrumb(d?.name);

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
  const documents = (
    <Section title="Pièces du dossier">
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
                {doc.file_path && manage ? <Button size="sm" variant="outline" onClick={() => setView(doc)}>Voir l’original</Button> : null}
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
      <p className="mt-3 text-xs text-ash">Les originaux sont lus par un accès protégé (jamais par une adresse publique) ; chaque ouverture est journalisée avec votre nom.</p>
    </Section>
  );
  const eligibility = (
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
  );
  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      {failure ? <Alert tone="danger" className="mb-4">{failure}</Alert> : null}
      <Fiche
        name={d.name}
        eyebrow={`Dossier #${d.profile_id}`}
        subtitle={`${d.state_label}${d.commune ? ` · ${d.commune}` : ""}`}
        badges={<><Badge tone={d.is_approved ? "success" : "warning"}>{d.is_approved ? "Dossier approuvé" : "Dossier non approuvé"}</Badge><Badge tone={d.publishable ? "success" : "gray"}>{d.publishable ? "Publiable" : "Non publiable"}</Badge>{!d.account_active ? <Badge tone="danger">Compte suspendu</Badge> : null}</>}
        facts={[["Pièces à examiner", d.documents_summary.pending], ["Approuvées", d.documents_summary.approved], ["Refusées", d.documents_summary.rejected], ["Commune", d.commune]]}
        actions={manage ? (
          d.is_approved ? <Button variant="danger" size="sm" onClick={() => setSuspend(true)}>Suspendre le dossier</Button>
            : <Button size="sm" disabled={d.documents_summary.approved === 0} onClick={() => setApproveProfile(true)}>Approuver le dossier</Button>
        ) : null}
        alert={!d.account_active ? <Alert tone="warning" className="mb-4">Le compte de cet artisan est suspendu : il n’est ni publié ni éligible aux missions.</Alert> : undefined}
        tabs={[
          { id: "general", label: "Informations générales", content: <Pane>{eligibility}<Section title="Compte de l’artisan"><KV items={[["Commune", d.commune], ["Dossier", d.state_label], ["Compte", d.account_active ? "Actif" : "Suspendu"]]} /><p className="mt-3 text-sm font-semibold text-primaryDark">{can("users.view") ? <Link className="underline underline-offset-2" href={`/backoffice/users/${d.user_id}`}>Ouvrir la fiche complète du compte</Link> : null}</p></Section></Pane> },
          { id: "documents", label: "Documents et justificatifs", count: d.documents.length || undefined, content: documents },
          { id: "activity", label: "Activités et historique", content: <Section title="Activité de l’artisan"><p className="text-sm text-inkSoft">Missions, litiges, paiements et engagements de ce compte sont regroupés sur sa fiche.</p>{can("users.view") ? <p className="mt-3"><Link className="text-sm font-semibold text-primaryDark underline underline-offset-2" href={`/backoffice/users/${d.user_id}?tab=activity`}>Voir ses activités</Link></p> : <Restricted right="users.view" />}</Section> },
          { id: "notes", label: "Notes internes et audit", content: (
            <Section title="Historique des décisions">
              {d.history.length ? (
                <ul className="divide-y divide-lineSoft text-sm">
                  {d.history.map((h, i) => <li key={i} className="py-2"><strong>{h.action.replace("backoffice.", "")}</strong> — {h.by} · {dt(h.at)}{h.reason ? <span className="block text-inkSoft">Motif : {h.reason}</span> : null}</li>)}
                </ul>
              ) : <KV items={[["Décisions", "Aucune décision enregistrée sur ce dossier."]]} />}
            </Section>
          ) },
          { id: "actions", label: "Actions administratives", content: (
            <Pane>
              <Section title="Décision sur le dossier">
                {manage ? (
                  <div className="space-y-3">
                    {d.is_approved
                      ? <><Button variant="danger" onClick={() => setSuspend(true)}>Suspendre le dossier</Button><p className="text-xs text-ash">Retrait immédiat de la publication, des missions et du Tratra ID. Les réservations en cours ne sont pas annulées.</p></>
                      : <><Button disabled={d.documents_summary.approved === 0} onClick={() => setApproveProfile(true)}>Approuver le dossier</Button><p className="text-xs text-ash">{d.documents_summary.approved === 0 ? "Une pièce d’identité approuvée est requise avant toute approbation du dossier." : "L’approbation est une décision humaine, journalisée."}</p></>}
                  </div>
                ) : <Restricted right="kyc.review">Approuver ou suspendre un dossier.</Restricted>}
              </Section>
              <Section title="Liens utiles">
                <ul className="space-y-2 text-sm font-semibold text-primaryDark">
                  {can("users.view") ? <li><Link className="underline underline-offset-2" href={`/backoffice/users/${d.user_id}`}>Fiche du compte</Link></li> : null}
                  {can("trust.manage") ? <li><Link className="underline underline-offset-2" href={`/backoffice/trust/${d.profile_id}`}>Confiance (Tratra Trust)</Link></li> : null}
                  {can("tratra_id.manage") ? <li><Link className="underline underline-offset-2" href="/backoffice/tratra-id">Tratra ID</Link></li> : null}
                </ul>
              </Section>
            </Pane>
          ) },
        ]}
      />

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
