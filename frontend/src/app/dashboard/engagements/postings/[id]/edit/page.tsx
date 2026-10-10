"use client";
import { useParams } from "next/navigation";
import { PageHeader } from "@/components/ds";
import { eng, type Posting } from "@/lib/engagements";
import { LoadState, useLoad } from "../../../_components/common";
import { PostingForm } from "../../../_components/PostingForm";
import { termsFromPosting } from "../../../_components/TermsFields";

export default function EditPostingPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, loading, reload } = useLoad(() => eng.get<Posting>(`/postings/${id}/`), [id]);
  return (
    <>
      <PageHeader back={{ href: `/dashboard/engagements/postings/${id}`, label: "Retour au besoin" }} title="Modifier le besoin" />
      <LoadState loading={loading} error={error} hasData={Boolean(data)} reload={() => void reload()}>
        {data ? <PostingForm key={data.version} initial={termsFromPosting(data)} existing={data} /> : null}
      </LoadState>
    </>
  );
}
