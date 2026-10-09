"use client";
import { useCallback, useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { FileText, Lock, RefreshCw, Upload, UploadCloud } from "lucide-react";
import { get, upload } from "@/lib/api";
import {
  Alert,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Field,
  PageHeader,
  SelectField,
  SkeletonList,
} from "@/components/ds";
import { FileDropzone } from "@/components/kyc/FileDropzone";
import { KycDocumentCard } from "@/components/kyc/KycDocumentCard";
import {
  DOC_TYPES,
  KYC_ACCEPT,
  KYC_MAX_MB,
  documentTypeLabel,
  kycErrorMessage,
  riseDelay,
} from "@/components/kyc/documents";
import type { HandymanDocument, Paginated } from "@/lib/types";

const UPLOAD_FALLBACK = "Échec du téléversement (profil artisan requis).";

/** Phrase d'état par statut — uniquement ce que le statut reçu de l'API permet d'affirmer. */
const STATUS_NOTE: Record<string, string> = {
  pending: "Notre équipe examine cette pièce. Son statut s’affichera ici dès la fin de l’examen.",
  approved: "Cette pièce a été validée par notre équipe.",
};

export default function KycPage() {
  const [docs, setDocs] = useState<HandymanDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [type, setType] = useState("id_card");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [picked, setPicked] = useState<{ name: string; size: number } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback((skeleton = true) => {
    if (skeleton) setLoading(true);
    setLoadError("");
    get<Paginated<HandymanDocument>>("/handyman-docs/")
      .then((d) => {
        setDocs(d.results ?? []);
        setTotal(d.count ?? d.results?.length ?? 0);
        setHasMore(Boolean(d.next));
      })
      .catch((requestError) => setLoadError(kycErrorMessage(requestError, "Vos documents ne peuvent pas être chargés.")))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  function onPick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    setPicked(file ? { name: file.name, size: file.size } : null);
    setError("");
    setNotice("");
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const form = new FormData();
      form.append("document_type", type);
      form.append("file", file);
      await upload("/handyman-docs/", form);
      if (fileRef.current) fileRef.current.value = "";
      setPicked(null);
      setNotice(`Document « ${documentTypeLabel(type)} » envoyé. Il est en cours de vérification.`);
      load(false);
    } catch (requestError) {
      setError(kycErrorMessage(requestError, UPLOAD_FALLBACK));
    } finally {
      setBusy(false);
    }
  }

  /** Ouvre le sélecteur de fichier (même champ que le formulaire de dépôt). */
  function openPicker(preferredType?: string) {
    if (preferredType && DOC_TYPES.some((t) => t.value === preferredType)) setType(preferredType);
    fileRef.current?.click();
  }

  return (
    <>
      <PageHeader
        eyebrow="Espace artisan"
        title="Vérification (KYC)"
        description="Envoyez vos pièces justificatives : notre équipe les examine, et chaque document affiche son statut réel. Un document n’est « Validé » qu’après cet examen."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5 lg:items-start">
        <Card as="section" aria-label="Déposer un document" className="animate-rise lg:col-span-2">
          <CardHeader
            icon={<UploadCloud className="h-5 w-5" />}
            title="Déposer une pièce"
            description="Un document à la fois. Il apparaît ensuite dans « Mes documents »."
          />
          <form onSubmit={submit} className="space-y-5">
            <SelectField label="Type de document" value={type} onChange={(e) => setType(e.target.value)} disabled={busy}>
              {DOC_TYPES.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </SelectField>

            <Field label="Fichier" required hint={`PDF, JPEG ou PNG · ${KYC_MAX_MB} Mo maximum`}>
              {(c) => (
                <FileDropzone
                  ref={fileRef}
                  id={c.id}
                  aria-describedby={c["aria-describedby"]}
                  aria-required={c["aria-required"]}
                  invalid={Boolean(error)}
                  required
                  accept={KYC_ACCEPT}
                  onChange={onPick}
                  selected={picked}
                  disabled={busy}
                />
              )}
            </Field>

            {error ? (
              <Alert tone="danger" title="Envoi impossible">
                {error}
              </Alert>
            ) : null}
            {notice ? (
              <Alert tone="success" onDismiss={() => setNotice("")}>
                {notice}
              </Alert>
            ) : null}

            <Button type="submit" block loading={busy} leftIcon={<Upload aria-hidden className="h-4 w-4" />}>
              {busy ? "Envoi…" : "Téléverser"}
            </Button>
            {busy ? (
              <p role="status" className="text-center text-xs text-ash">
                Envoi{picked ? ` de « ${picked.name} »` : ""} en cours. Gardez cette page ouverte.
              </p>
            ) : null}

            <p className="flex items-start gap-2 text-xs leading-relaxed text-ash">
              <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              Vos pièces sont stockées en privé : seuls vous et l’équipe Tratra pouvez les consulter.
            </p>
          </form>
        </Card>

        <section aria-labelledby="kyc-docs-title" className="lg:col-span-3">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-x-4 gap-y-1">
            <h2 id="kyc-docs-title" className="font-display text-lg font-bold text-ink">
              Mes documents
            </h2>
            {!loading && docs.length > 0 ? (
              <p className="text-sm text-ash">
                {docs.length} document{docs.length > 1 ? "s" : ""}
              </p>
            ) : null}
          </div>

          <div className="space-y-4">
            {loadError ? (
              <Alert
                tone="danger"
                title="Chargement impossible"
                action={
                  <Button size="sm" variant="outline" leftIcon={<RefreshCw aria-hidden className="h-4 w-4" />} onClick={() => load()}>
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
              <SkeletonList count={2} />
            ) : docs.length > 0 ? (
              <ul className="grid grid-cols-1 gap-3">
                {docs.map((d, index) => (
                  <li key={d.id} className="animate-rise" style={riseDelay(index)}>
                    <KycDocumentCard
                      audience="worker"
                      title={documentTypeLabel(d.document_type)}
                      status={d.status}
                      uploadedAt={d.uploaded_at}
                      note={STATUS_NOTE[d.status]}
                      rejectionReason={d.rejection_reason}
                      actions={
                        d.status === "rejected" ? (
                          <Button
                            size="md"
                            variant="soft"
                            leftIcon={<Upload aria-hidden className="h-4 w-4" />}
                            disabled={busy}
                            onClick={() => openPicker(d.document_type)}
                          >
                            Déposer une nouvelle pièce
                          </Button>
                        ) : undefined
                      }
                    />
                  </li>
                ))}
              </ul>
            ) : !loadError ? (
              <EmptyState
                icon={<FileText aria-hidden />}
                title="Aucun document déposé"
                description="Vous n’avez encore envoyé aucune pièce. Téléversez au moins une pièce d’identité : notre équipe pourra alors commencer la vérification."
                actions={
                  <Button leftIcon={<Upload aria-hidden className="h-4 w-4" />} onClick={() => openPicker()}>
                    Choisir un fichier
                  </Button>
                }
              />
            ) : null}
          </div>
        </section>
      </div>
    </>
  );
}
