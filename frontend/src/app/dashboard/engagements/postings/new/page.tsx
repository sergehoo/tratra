"use client";
import { PageHeader } from "@/components/ds";
import { PostingForm } from "../../_components/PostingForm";
import { emptyTerms } from "../../_components/TermsFields";

export default function NewPostingPage() {
  return (
    <>
      <PageHeader back={{ href: "/dashboard/engagements", label: "Engagements" }} title="Publier un besoin"
        description="Décrivez la mission, le planning et la rémunération. Seuls des professionnels vérifiés pourront postuler ; vous choisissez qui retenir, puis vous préparez le contrat ensemble." />
      <PostingForm initial={emptyTerms()} />
    </>
  );
}
