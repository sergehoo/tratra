"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Alert, Button, Card, SelectField } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api";
import { eng, errCode, errFields, isConflictVersion, type ContractDetail } from "@/lib/engagements";
import { useIntent } from "./common";
import { TermsFields, contractBody, type TermsValue } from "./TermsFields";
import { useTermsContext } from "./useTermsContext";
import { WorkerPicker, type PickedWorker } from "./WorkerPicker";

/**
 * Brouillon de contrat. Rien n'engage personne tant que le contrat n'est pas PROPOSÉ puis ACCEPTÉ par les deux parties ;
 * l'adresse n'est visible du prestataire qu'à la proposition. Le serveur revalide toutes les règles (durée, préavis, emploi…).
 */
export function ContractForm({ initial, application, existing, initialWorker }: { initial: TermsValue; application?: number; existing?: ContractDetail; initialWorker?: PickedWorker }) {
  const router = useRouter();
  const ctx = useTermsContext();
  const intent = useIntent("contract");
  const [value, setValue] = useState<TermsValue>(initial);
  const [worker, setWorker] = useState<PickedWorker | null>(initialWorker ?? null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<number | null>(null);
  const [busy, setBusy] = useState<"save" | "propose" | null>(null);
  const direct = !application && !existing;

  async function submit(propose: boolean) {
    if (direct && !worker) {
      setErrors({ worker: "Choisissez le professionnel." });
      return;
    }
    setBusy(propose ? "propose" : "save");
    setError("");
    setErrors({});
    const terms = contractBody(value);
    let id = existing?.id ?? saved;
    try {
      if (existing) {
        await eng.patch<ContractDetail>(`/contracts/${existing.id}/`, { ...terms, expected_version: existing.version });
      } else if (id === null) {
        const body = application ? { ...terms, application } : { ...terms, worker: worker?.id, ...(value.organization ? { organization: Number(value.organization) } : {}) };
        const created = await eng.post<ContractDetail>("/contracts/", body, intent.key(body));
        id = created.id;
        setSaved(id);
        intent.reset();
      }
      if (propose && id !== null) {
        try {
          await eng.post(`/contracts/${id}/propose/`);
        } catch (e) {
          setErrors(errFields(e));
          setError(`Brouillon enregistré, mais la proposition n’a pas pu être envoyée : ${apiErrorMessage(e, "vérifiez les champs.")}`);
          setBusy(null);
          return;
        }
      }
      router.push(`/dashboard/engagements/contracts/${id}`);
    } catch (e) {
      setErrors(errFields(e));
      const existingId = (e as { data?: { contract_id?: number } })?.data?.contract_id;
      setError(
        isConflictVersion(e) ? "Ce brouillon a été modifié ailleurs. Rechargez la page pour repartir de la dernière version."
          : errCode(e) === "contract_exists" && existingId ? `Un contrat existe déjà pour cette candidature (n° ${existingId}).`
          : apiErrorMessage(e, "Enregistrement impossible. Rien n’a été envoyé."),
      );
      setBusy(null);
    }
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); void submit(false); }} noValidate>
      {ctx.error ? <Alert tone="warning" className="mb-4" action={<Button size="sm" variant="outline" onClick={ctx.reload}>Réessayer</Button>}>{ctx.error}</Alert> : null}
      <Card padding="md">
        <div className="space-y-5">
          {direct ? (
            <>
              <WorkerPicker label="Prestataire" picked={worker} onPick={setWorker} />
              {errors.worker ? <p role="alert" className="-mt-3 text-xs font-medium text-dangerInk">{errors.worker}</p> : null}
              {ctx.organizations.length > 0 ? (
                <SelectField label="Engager au nom de" optional value={value.organization} onChange={(e) => setValue({ ...value, organization: e.target.value })}>
                  <option value="">Moi-même</option>
                  {ctx.organizations.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                </SelectField>
              ) : null}
            </>
          ) : null}
          <TermsFields mode="contract" value={value} onChange={setValue} errors={errors} categories={ctx.categories} rules={ctx.rules} disabled={busy !== null} />
        </div>
      </Card>
      {error ? (
        <Alert tone="danger" className="mt-4">
          {error}
          {saved !== null ? <> <Link href={`/dashboard/engagements/contracts/${saved}`}>Ouvrir le brouillon</Link>.</> : null}
        </Alert>
      ) : null}
      <div className="mt-5 flex flex-wrap items-center justify-end gap-3">
        <Link href={existing ? `/dashboard/engagements/contracts/${existing.id}` : "/dashboard/engagements"} className="text-sm font-semibold text-inkSoft underline underline-offset-2">Annuler</Link>
        <Button type="submit" variant="outline" loading={busy === "save"} disabled={busy === "propose"}>{existing ? "Enregistrer" : "Enregistrer le brouillon"}</Button>
        <Button type="button" loading={busy === "propose"} disabled={busy === "save"} onClick={() => void submit(true)}>Enregistrer et proposer</Button>
      </div>
    </form>
  );
}
