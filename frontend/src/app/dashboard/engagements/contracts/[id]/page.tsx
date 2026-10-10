"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Alert, Button, ButtonLink, PageHeader, StatusBadge, Tabs } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api";
import { PERIOD_FR, eng, fcfa, type ContractDetail } from "@/lib/engagements";
import { LoadState, useLoad, useNotice, useTabParam } from "../../_components/common";
import { Amendments } from "./_parts/Amendments";
import { Evaluations } from "./_parts/Evaluations";
import { History } from "./_parts/History";
import { Pay } from "./_parts/Pay";
import { Planning } from "./_parts/Planning";
import { Summary } from "./_parts/Summary";

type Tab = "summary" | "pay" | "planning" | "amendments" | "evaluations" | "history";
const ALL: readonly Tab[] = ["summary", "pay", "planning", "amendments", "evaluations", "history"];

export default function ContractPage() {
  const { id } = useParams<{ id: string }>();
  const { data: c, error, loading, reload } = useLoad(() => eng.get<ContractDetail>(`/contracts/${id}/`), [id]);
  const [tab, setTab] = useTabParam(ALL, "summary");
  const [amend, setAmend] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useNotice();

  async function propose() {
    if (!c) return;
    setBusy(true);
    setActionError("");
    try {
      await eng.post(`/contracts/${c.id}/propose/`, { expected_version: c.version });
      setNotice(`Contrat proposé à ${c.worker.name}. Vous serez prévenu(e) de sa réponse.`);
      await reload();
    } catch (e) {
      setActionError(apiErrorMessage(e, "Proposition impossible."));
    } finally {
      setBusy(false);
    }
  }

  const started = c ? ["active", "suspended", "notice", "terminated", "completed", "accepted"].includes(c.status) : false;
  const tabs = [{ id: "summary" as Tab, label: "Résumé" }, ...(started ? [{ id: "pay" as Tab, label: "Rémunération" }, { id: "planning" as Tab, label: "Planning" }, { id: "amendments" as Tab, label: "Avenants" }, { id: "evaluations" as Tab, label: "Évaluations" }] : []), { id: "history" as Tab, label: "Historique" }];
  const current: Tab = tabs.some((t) => t.id === tab) ? tab : "summary";

  return (
    <LoadState loading={loading} error={error} hasData={Boolean(c)} reload={() => void reload()}>
      {c ? (
        <>
          <PageHeader back={{ href: "/dashboard/engagements", label: "Engagements" }} title={c.title} eyebrow={<StatusBadge kind="contract" status={c.status} />}
            description={`${c.my_role === "worker" ? "Pour" : "Avec"} ${c.counterpart.name} · ${fcfa(c.amount, c.currency)} ${PERIOD_FR[c.period]}`}
            actions={
              c.status === "draft" ? (
                <>
                  <ButtonLink href={`/dashboard/engagements/contracts/${c.id}/edit`} variant="outline">Modifier</ButtonLink>
                  <Button loading={busy} onClick={() => void propose()}>Proposer à {c.worker.name}</Button>
                </>
              ) : undefined
            } />
          {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}
          {actionError ? <Alert tone="danger" className="mb-4">{actionError}</Alert> : null}
          <Tabs ariaLabel="Sections du contrat" value={current} onChange={setTab} className="mb-5" items={tabs} />
          {current === "summary" ? <Summary c={c} reload={() => void reload()} goTab={setTab} openAmend={() => { setTab("amendments"); setAmend(true); }} /> : null}
          {current === "pay" ? <Pay c={c} onChanged={() => void reload()} initialOpen={null} /> : null}
          {current === "planning" ? <Planning c={c} onChanged={() => void reload()} /> : null}
          {current === "amendments" ? <Amendments c={c} onChanged={() => void reload()} openNew={amend} setOpenNew={setAmend} /> : null}
          {current === "evaluations" ? <Evaluations c={c} /> : null}
          {current === "history" ? <History c={c} /> : null}
          <p className="mt-8 text-xs text-ash">Un désaccord ? Ouvrez un litige depuis l’onglet Résumé : l’équipe Tratra peut médier, suspendre ou résilier le contrat. <Link href="/dashboard/engagements" className="underline">Retour aux engagements</Link></p>
        </>
      ) : null}
    </LoadState>
  );
}
