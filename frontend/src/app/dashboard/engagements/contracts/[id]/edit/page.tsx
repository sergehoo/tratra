"use client";
import { useParams } from "next/navigation";
import { Alert, PageHeader } from "@/components/ds";
import { eng, type ContractDetail } from "@/lib/engagements";
import { ContractForm } from "../../../_components/ContractForm";
import { LoadState, useLoad } from "../../../_components/common";
import { termsFromContract } from "../../../_components/TermsFields";

export default function EditContractPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, loading, reload } = useLoad(() => eng.get<ContractDetail>(`/contracts/${id}/`), [id]);
  return (
    <>
      <PageHeader back={{ href: `/dashboard/engagements/contracts/${id}`, label: "Retour au contrat" }} title="Modifier le brouillon" />
      <LoadState loading={loading} error={error} hasData={Boolean(data)} reload={() => void reload()}>
        {data && data.status !== "draft" ? <Alert tone="warning">Seul un brouillon se modifie. Après la proposition, passez par un avenant.</Alert> : null}
        {data && data.status === "draft" ? <ContractForm key={data.version} initial={termsFromContract(data)} existing={data} /> : null}
      </LoadState>
    </>
  );
}
