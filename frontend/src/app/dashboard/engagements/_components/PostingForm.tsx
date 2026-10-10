"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import Link from "next/link";
import { Alert, Button, Card } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api";
import { eng, errFields, isConflictVersion, type Posting } from "@/lib/engagements";
import { useIntent } from "./common";
import { TermsFields, postingBody, type TermsValue } from "./TermsFields";
import { useTermsContext } from "./useTermsContext";

/** Création ou modification d'un besoin. Publier = enregistrer puis rendre visible : la publication est revalidée par le serveur. */
export function PostingForm({ initial, existing }: { initial: TermsValue; existing?: Posting }) {
  const router = useRouter();
  const ctx = useTermsContext();
  const intent = useIntent("posting");
  const [value, setValue] = useState<TermsValue>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<number | null>(null);
  const [busy, setBusy] = useState<"save" | "publish" | null>(null);
  const editing = Boolean(existing);

  async function submit(publish: boolean) {
    setBusy(publish ? "publish" : "save");
    setError("");
    setErrors({});
    const body = postingBody(value);
    let id = existing?.id ?? saved;
    try {
      if (existing) {
        await eng.patch<Posting>(`/postings/${existing.id}/`, { ...body, expected_version: existing.version });
      } else if (id === null) {
        const created = await eng.post<Posting>("/postings/", body, intent.key(body));
        id = created.id;
        setSaved(id);
        intent.reset();
      }
      if (publish && id !== null && (!existing || existing.status === "draft")) {
        try {
          await eng.post<Posting>(`/postings/${id}/publish/`);
        } catch (e) {
          setErrors(errFields(e));
          setError(`Le besoin est enregistré en brouillon mais n’a pas pu être publié : ${apiErrorMessage(e, "vérifiez les champs.")}`);
          setBusy(null);
          return;
        }
      }
      router.push(`/dashboard/engagements/postings/${id}`);
    } catch (e) {
      setErrors(errFields(e));
      setError(isConflictVersion(e) ? "Ce besoin a été modifié ailleurs. Rechargez la page pour repartir de la dernière version." : apiErrorMessage(e, "Enregistrement impossible. Rien n’a été publié."));
      setBusy(null);
    }
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); void submit(!editing || existing?.status === "draft"); }} noValidate>
      {ctx.error ? <Alert tone="warning" className="mb-4" action={<Button size="sm" variant="outline" onClick={ctx.reload}>Réessayer</Button>}>{ctx.error}</Alert> : null}
      <Card padding="md">
        <TermsFields mode="posting" value={value} onChange={setValue} errors={errors} categories={ctx.categories} rules={ctx.rules} organizations={ctx.organizations} disabled={busy !== null} />
      </Card>
      {error ? (
        <Alert tone="danger" className="mt-4">
          {error}
          {saved !== null ? <> <Link href={`/dashboard/engagements/postings/${saved}`}>Ouvrir le brouillon</Link>.</> : null}
        </Alert>
      ) : null}
      <div className="mt-5 flex flex-wrap items-center justify-end gap-3">
        <Link href={existing ? `/dashboard/engagements/postings/${existing.id}` : "/dashboard/engagements"} className="text-sm font-semibold text-inkSoft underline underline-offset-2">Annuler</Link>
        {editing && existing?.status !== "draft" ? (
          <Button type="submit" loading={busy === "save"}>Enregistrer les modifications</Button>
        ) : (
          <>
            <Button type="button" variant="outline" loading={busy === "save"} disabled={busy === "publish"} onClick={() => void submit(false)}>Enregistrer le brouillon</Button>
            <Button type="submit" loading={busy === "publish"} disabled={busy === "save"}>Publier le besoin</Button>
          </>
        )}
      </div>
    </form>
  );
}
