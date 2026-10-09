"use client";
import { useCallback, useEffect, useState } from "react";
import { Check, Eye, FileSearch, RefreshCw, X } from "lucide-react";
import { get, post, privateFileUrl } from "@/lib/api";
import {
  Alert,
  Avatar,
  Button,
  ButtonLink,
  ConfirmDialog,
  EmptyState,
  PageHeader,
  SkeletonList,
  Tabs,
  TextareaField,
  type TabItem,
} from "@/components/ds";
import { KycDocumentCard } from "@/components/kyc/KycDocumentCard";
import { documentTypeLabel, kycErrorMessage, riseDelay } from "@/components/kyc/documents";
import type { HandymanDocument, Paginated } from "@/lib/types";

type Filter = "all" | "pending" | "approved" | "rejected";
type BusyAction = "view" | "approve" | "reject";

/** Libellés des filtres (les statuts eux-mêmes viennent de l'API : pending / approved / rejected). */
const FILTER_LABEL: Record<Exclude<Filter, "all">, string> = {
  pending: "En vérification",
  approved: "Validés",
  rejected: "Refusés",
};

/** Titre de l'état vide quand un filtre ne retient aucun document. */
const FILTER_EMPTY: Record<Exclude<Filter, "all">, string> = {
  pending: "Aucun document en vérification",
  approved: "Aucun document validé",
  rejected: "Aucun document refusé",
};

/** Prénom + nom, à défaut l'identifiant ; « Artisan » si l'API n'en fournit aucun. */
function artisanName(d: HandymanDocument): string {
  const user = d.handyman_detail?.user_detail;
  const full = [user?.first_name, user?.last_name].filter(Boolean).join(" ").trim();
  return full || user?.username || "Artisan";
}

export default function AdminKyc() {
  const [docs, setDocs] = useState<HandymanDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const [busyAction, setBusyAction] = useState<BusyAction | null>(null);
  const [actionError, setActionError] = useState<{ id: number; title: string; message: string } | null>(null);
  const [notice, setNotice] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  // La cible reste en mémoire à la fermeture pour que le dialogue ne se vide pas pendant son animation de sortie.
  const [target, setTarget] = useState<HandymanDocument | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [reason, setReason] = useState("");

  const load = useCallback((skeleton = true) => {
    if (skeleton) setLoading(true);
    setLoadError("");
    get<Paginated<HandymanDocument>>("/handyman-docs/")
      .then((d) => {
        setDocs(d.results ?? []);
        setTotal(d.count ?? d.results?.length ?? 0);
        setHasMore(Boolean(d.next));
      })
      .catch((requestError) => setLoadError(kycErrorMessage(requestError, "Les documents KYC ne peuvent pas être chargés.")))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  async function review(doc: HandymanDocument, action: "approve" | "reject", rejectionReason = "") {
    setBusy(doc.id);
    setBusyAction(action);
    setActionError(null);
    setNotice("");
    try {
      await post(`/handyman-docs/${doc.id}/review/`, { action, reason: rejectionReason });
      setDialogOpen(false);
      setNotice(
        `Document « ${documentTypeLabel(doc.document_type)} » de ${artisanName(doc)} : ${action === "approve" ? "approuvé" : "rejeté"}.`,
      );
      load(false);
    } catch (requestError) {
      setActionError({
        id: doc.id,
        title: "Revue impossible",
        message: kycErrorMessage(requestError, "La revue du document a échoué."),
      });
    } finally {
      setBusy(null);
      setBusyAction(null);
    }
  }

  function askReject(doc: HandymanDocument) {
    setTarget(doc);
    setReason("");
    setActionError(null);
    setDialogOpen(true);
  }

  async function viewDocument(document: HandymanDocument) {
    if (!document.download_url) return;
    setBusy(document.id);
    setBusyAction("view");
    setActionError(null);
    setNotice("");
    try {
      const objectUrl = await privateFileUrl(document.download_url);
      const link = window.document.createElement("a");
      link.href = objectUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      window.document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    } catch (requestError) {
      setActionError({
        id: document.id,
        title: "Document inaccessible",
        message: kycErrorMessage(requestError, "Le document KYC ne peut pas être ouvert."),
      });
    } finally {
      setBusy(null);
      setBusyAction(null);
    }
  }

  const count = (status: Exclude<Filter, "all">) => docs.filter((d) => d.status === status).length;
  const tabs: TabItem<Filter>[] = [
    { id: "all", label: "Tous", count: docs.length },
    { id: "pending", label: FILTER_LABEL.pending, count: count("pending") },
    { id: "approved", label: FILTER_LABEL.approved, count: count("approved") },
    { id: "rejected", label: FILTER_LABEL.rejected, count: count("rejected") },
  ];
  const visible = filter === "all" ? docs : docs.filter((d) => d.status === filter);
  const dialogError = dialogOpen && target && actionError?.id === target.id ? actionError.message : "";

  return (
    <>
      <PageHeader
        eyebrow="Back-office"
        title="Vérifications KYC"
        description="Examinez les pièces déposées par les artisans : ouvrez le document, puis approuvez-le ou rejetez-le en indiquant un motif."
        actions={
          <Button
            variant="outline"
            loading={loading}
            leftIcon={<RefreshCw aria-hidden className="h-4 w-4" />}
            onClick={() => load()}
          >
            Actualiser
          </Button>
        }
      />

      <div className="space-y-5">
        {notice ? (
          <Alert tone="success" onDismiss={() => setNotice("")}>
            {notice}
          </Alert>
        ) : null}

        {loadError ? (
          <Alert
            tone="danger"
            title="Chargement impossible"
            action={
              <Button size="sm" variant="outline" onClick={() => load()}>
                Réessayer
              </Button>
            }
          >
            {loadError}
          </Alert>
        ) : null}

        {hasMore && !loading ? (
          <Alert tone="info">
            Seuls {docs.length} documents sur {total} sont affichés ici.
          </Alert>
        ) : null}

        {loading ? (
          <SkeletonList count={3} />
        ) : docs.length === 0 ? (
          loadError ? null : (
            <EmptyState
              icon={<FileSearch aria-hidden />}
              title="Aucun document à examiner"
              description="Les pièces déposées par les artisans apparaîtront ici dès qu’ils en enverront."
              actions={
                <ButtonLink href="/admin" variant="outline">
                  Retour à la vue d’ensemble
                </ButtonLink>
              }
            />
          )
        ) : (
          <>
            <Tabs items={tabs} value={filter} onChange={setFilter} ariaLabel="Filtrer les documents par statut" />

            <div role="tabpanel" id={`panel-${filter}`} aria-labelledby={`tab-${filter}`}>
              {visible.length === 0 ? (
                <EmptyState
                  compact
                  icon={<FileSearch aria-hidden />}
                  title={filter === "all" ? "Aucun document" : FILTER_EMPTY[filter]}
                  description="Aucun document ne correspond à ce filtre pour le moment."
                  actions={
                    <Button variant="outline" onClick={() => setFilter("all")}>
                      Voir tous les documents
                    </Button>
                  }
                />
              ) : (
                <ul className="grid items-start gap-4 xl:grid-cols-2">
                  {visible.map((d, index) => {
                    const name = artisanName(d);
                    const working = busy === d.id;
                    const cardError =
                      actionError?.id === d.id && !(dialogOpen && target?.id === d.id) ? actionError : null;
                    return (
                      <li key={d.id} className="animate-rise" style={riseDelay(index)}>
                        <KycDocumentCard
                          audience="admin"
                          title={documentTypeLabel(d.document_type)}
                          status={d.status}
                          uploadedAt={d.uploaded_at}
                          rejectionReason={d.rejection_reason}
                          byline={
                            <span className="inline-flex items-center gap-2">
                              <Avatar name={name} size={24} />
                              <span className="font-semibold text-ink">{name}</span>
                            </span>
                          }
                          actions={
                            <>
                              {d.download_url ? (
                                <Button
                                  variant="outline"
                                  leftIcon={<Eye aria-hidden className="h-4 w-4" />}
                                  loading={working && busyAction === "view"}
                                  disabled={working}
                                  onClick={() => void viewDocument(d)}
                                >
                                  Voir le document
                                </Button>
                              ) : null}
                              {d.status !== "approved" ? (
                                <Button
                                  leftIcon={<Check aria-hidden className="h-4 w-4" />}
                                  loading={working && busyAction === "approve"}
                                  disabled={working}
                                  onClick={() => void review(d, "approve")}
                                >
                                  Approuver
                                </Button>
                              ) : null}
                              {d.status !== "rejected" ? (
                                <Button
                                  variant="outline"
                                  leftIcon={<X aria-hidden className="h-4 w-4 text-danger" />}
                                  disabled={working}
                                  onClick={() => askReject(d)}
                                >
                                  Rejeter
                                </Button>
                              ) : null}
                            </>
                          }
                        >
                          {cardError ? (
                            <Alert tone="danger" title={cardError.title}>
                              {cardError.message}
                            </Alert>
                          ) : null}
                        </KycDocumentCard>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </>
        )}
      </div>

      <ConfirmDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onConfirm={() => target && void review(target, "reject", reason.trim())}
        title="Rejeter ce document ?"
        description={
          target
            ? `« ${documentTypeLabel(target.document_type)} » de ${artisanName(target)} passera au statut « Refusé ».`
            : undefined
        }
        confirmLabel="Rejeter le document"
        tone="danger"
        loading={busyAction === "reject"}
      >
        <div className="space-y-4">
          <TextareaField
            label="Motif du rejet"
            optional
            rows={4}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Ex. document illisible, pièce expirée…"
            hint="Le motif est affiché à l’artisan avec le statut « Refusé » : indiquez ce qu’il doit corriger."
          />
          {dialogError ? <Alert tone="danger">{dialogError}</Alert> : null}
        </div>
      </ConfirmDialog>
    </>
  );
}
