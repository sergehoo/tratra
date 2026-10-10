"use client";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Alert, PageHeader } from "@/components/ds";
import { eng, fcfa, type Application, type Page, type Posting } from "@/lib/engagements";
import { ContractForm } from "../../_components/ContractForm";
import { LoadState, useLoad } from "../../_components/common";
import { emptyTerms, termsFromPosting } from "../../_components/TermsFields";

function Inner() {
  const params = useSearchParams();
  const application = Number(params.get("application")) || undefined;
  const postingId = params.get("posting");
  const workerId = Number(params.get("worker")) || null;
  const workerName = (params.get("name") ?? "").slice(0, 80);
  const posting = useLoad(async () => {
    if (!postingId) return null;
    const p = await eng.get<Posting>(`/postings/${postingId}/`);
    // La candidature retenue (montant proposé, disponibilité) sert de point de départ : le donneur d'ordre ajuste ensuite.
    const apps = application ? (await eng.get<Page<Application>>(`/postings/${postingId}/applications/?limit=50`)).results : [];
    return { posting: p, application: apps.find((a) => a.id === application) ?? null };
  }, [postingId, application]);
  const base = posting.data ? termsFromPosting(posting.data.posting) : emptyTerms();
  const chosen = posting.data?.application ?? null;
  const today = new Date().toISOString().slice(0, 10);
  const prefilled = posting.data
    ? {
        ...base, address: "", city: posting.data.posting.city, notice_period_days: "7", payment_day: "5",
        amount: chosen?.proposed_amount ? String(Number(chosen.proposed_amount)) : base.amount,
        start_date: base.start_date && base.start_date >= today ? base.start_date : chosen?.available_from && chosen.available_from >= today ? chosen.available_from : "",
      }
    : emptyTerms();
  return (
    <>
      <PageHeader back={{ href: postingId ? `/dashboard/engagements/postings/${postingId}` : "/dashboard/engagements", label: "Retour" }} title="Préparer un contrat"
        description={application ? "Les conditions de l’offre sont reprises : ajustez-les avec le candidat retenu avant de les lui proposer." : "Choisissez un professionnel vérifié et définissez vos conditions."} />
      <Alert tone="brand" className="mb-5" title="Un accord clair, accepté par les deux parties">
        Le prestataire relit exactement ces conditions et les accepte (ou demande une modification). Toute évolution ultérieure passe par un avenant accepté par l’autre partie, sans effet rétroactif.
      </Alert>
      {chosen?.proposed_amount ? <Alert tone="info" className="mb-5">{chosen.applicant?.name} propose {fcfa(chosen.proposed_amount)} : ce montant est repris ci-dessous (l’offre indiquait {fcfa(posting.data?.posting.amount)}).</Alert> : null}
      <LoadState loading={posting.loading} error={posting.error} hasData={!posting.loading && !posting.error} reload={() => void posting.reload()}>
        <ContractForm key={posting.data?.posting.id ?? "direct"} initial={prefilled} application={application} initialWorker={workerId && workerName ? { id: workerId, name: workerName, commune: "" } : undefined} />
      </LoadState>
    </>
  );
}

export default function NewContractPage() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  );
}
