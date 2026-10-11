"use client";
import { useEffect, useRef, useState } from "react";
import { Alert, Modal } from "@/components/ds";
import { apiFetch } from "@/lib/api";

export interface Doc {
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
/** Pièce d'identité : lue par un endpoint protégé (jeton, no-store), jamais par une URL de stockage ; chaque ouverture est journalisée. */
export function DocumentViewer({ doc, onClose }: { doc: Doc | null; onClose: () => void }) {
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

