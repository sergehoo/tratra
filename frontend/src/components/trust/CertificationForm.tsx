"use client";
import { useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { FileBadge } from "lucide-react";
import { Alert, Button, Card, CardHeader, Field, SelectField, TextField } from "@/components/ds";
import { FileDropzone } from "@/components/kyc/FileDropzone";
import { KYC_ACCEPT, KYC_MAX_MB, kycErrorMessage } from "@/components/kyc/documents";
import { upload } from "@/lib/api";
import { useData } from "@/lib/useData";
import type { Category, Paginated } from "@/lib/types";

/** Dépôt d'un justificatif professionnel (diplôme, attestation…). Il reste « en attente » jusqu'à la validation de l'équipe Tratra. */
export function CertificationForm({ onSent }: { onSent: () => void }) {
  const cats = useData<Paginated<Category>>("/categories/?page_size=100&ordering=name");
  const fileRef = useRef<HTMLInputElement>(null);
  const [picked, setPicked] = useState<{ name: string; size: number } | null>(null);
  const [f, setF] = useState({ title: "", category: "", issuer: "", issued_on: "", expires_on: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const set = (k: keyof typeof f) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((s) => ({ ...s, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return setError("Choisissez le fichier du justificatif.");
    if (!f.title.trim()) return setError("Indiquez l’intitulé du justificatif.");
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const form = new FormData();
      form.append("document_type", "certification");
      form.append("file", file);
      form.append("title", f.title.trim());
      if (f.category) form.append("category", f.category);
      if (f.issuer.trim()) form.append("issuer", f.issuer.trim());
      if (f.issued_on) form.append("issued_on", f.issued_on);
      if (f.expires_on) form.append("expires_on", f.expires_on);
      await upload("/handyman-docs/", form);
      setF({ title: "", category: "", issuer: "", issued_on: "", expires_on: "" });
      if (fileRef.current) fileRef.current.value = "";
      setPicked(null);
      setNotice("Justificatif envoyé. Il sera affiché comme compétence certifiée après validation par l’équipe Tratra.");
      onSent();
    } catch (err) {
      setError(kycErrorMessage(err, "L’envoi du justificatif a échoué. Réessayez dans un instant."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card as="section" aria-label="Ajouter un justificatif professionnel">
      <CardHeader
        icon={<FileBadge className="h-5 w-5" />}
        title="Ajouter un justificatif"
        description="Diplôme, attestation, habilitation… Il compte pour le badge Expert uniquement une fois approuvé par l’équipe Tratra."
      />
      <form onSubmit={submit} className="space-y-4" noValidate>
        <TextField label="Intitulé" required value={f.title} onChange={set("title")} maxLength={120} placeholder="Ex. CAP Installateur sanitaire" />
        <SelectField label="Métier concerné" optional value={f.category} onChange={set("category")}>
          <option value="">Non précisé</option>
          {(cats.data?.results ?? []).map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </SelectField>
        <TextField label="Organisme émetteur" optional value={f.issuer} onChange={set("issuer")} maxLength={120} />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <TextField label="Date d’obtention" optional type="date" value={f.issued_on} onChange={set("issued_on")} />
          <TextField label="Valable jusqu’au" optional type="date" value={f.expires_on} onChange={set("expires_on")} />
        </div>
        <Field label="Fichier" hint={`PDF, JPG ou PNG — ${KYC_MAX_MB} Mo maximum.`} required>
          {(c) => (
            <FileDropzone
              {...c}
              ref={fileRef}
              accept={KYC_ACCEPT}
              selected={picked}
              onChange={(e) => {
                const file = e.target.files?.[0];
                setPicked(file ? { name: file.name, size: file.size } : null);
                setError("");
              }}
            />
          )}
        </Field>
        {error ? <Alert tone="danger">{error}</Alert> : null}
        {notice ? <Alert tone="success">{notice}</Alert> : null}
        <Button type="submit" loading={busy} block size="lg">
          Envoyer le justificatif
        </Button>
      </form>
    </Card>
  );
}
