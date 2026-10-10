"use client";
import { useState } from "react";
import { History as HistoryIcon, Scale } from "lucide-react";
import { Badge, Button, Card, CardHeader, EmptyState } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api";
import { CONTRACT_EVENT_FR, DISPUTE_KIND_FR, dateTimeFr, eng, type ContractDetail, type Dispute, type HistoryEvent, type Page } from "@/lib/engagements";
import { LoadState, useLoad } from "../../../_components/common";

const DISPUTE_STATUS: Record<string, { label: string; tone: "danger" | "warning" | "success" | "gray" }> = {
  open: { label: "Ouvert", tone: "danger" }, under_review: { label: "En cours d’examen", tone: "warning" }, resolved: { label: "Résolu", tone: "success" }, rejected: { label: "Rejeté", tone: "gray" },
};

export function History({ c }: { c: ContractDetail }) {
  const [extra, setExtra] = useState<HistoryEvent[]>([]);
  const [more, setMore] = useState<number | null>(null);
  const [moreError, setMoreError] = useState("");
  const first = useLoad(async () => {
    const page = await eng.get<Page<HistoryEvent>>(`/contracts/${c.id}/history/?limit=50`);
    setExtra([]);
    setMore(page.next_offset);
    return page;
  }, [c.id, c.version]);
  const disputes = useLoad(() => eng.get<{ results: Dispute[] }>(`/contracts/${c.id}/disputes/`), [c.id, c.version]);
  const events = [...(first.data?.results ?? []), ...extra];
  async function loadMore() {
    if (more === null) return;
    setMoreError("");
    try {
      const page = await eng.get<Page<HistoryEvent>>(`/contracts/${c.id}/history/?limit=50&offset=${more}`);
      setExtra((e) => [...e, ...page.results]);
      setMore(page.next_offset);
    } catch (e) {
      setMoreError(apiErrorMessage(e, "Chargement impossible."));
    }
  }
  return (
    <div className="space-y-6">
      {disputes.data && disputes.data.results.length > 0 ? (
        <Card padding="md">
          <CardHeader title="Litiges" icon={<Scale className="h-5 w-5" />} />
          <ul className="space-y-3">
            {disputes.data.results.map((d) => (
              <li key={d.id} className="rounded-panel border border-lineSoft p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold text-ink">{DISPUTE_KIND_FR[d.kind] ?? d.kind}{d.mine ? " · ouvert par vous" : ""}</span>
                  <Badge tone={DISPUTE_STATUS[d.status]?.tone ?? "gray"}>{DISPUTE_STATUS[d.status]?.label ?? d.status}</Badge>
                </div>
                <p className="mt-1 text-inkSoft">{d.reason}</p>
                {d.resolution ? <p className="mt-2 rounded-panel bg-primarySoft/60 p-2 text-xs text-inkSoft"><strong>Décision de Tratra :</strong> {d.resolution}</p> : null}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      <Card padding="md">
        <CardHeader title="Historique" description="Chaque étape du contrat, en ajout seulement : rien n’est jamais effacé." icon={<HistoryIcon className="h-5 w-5" />} />
        <LoadState loading={first.loading} error={first.error} hasData={Boolean(first.data)} reload={() => void first.reload()}>
          {events.length === 0 ? <EmptyState compact title="Aucun événement" /> : (
            <ol className="space-y-3">
              {events.map((e) => (
                <li key={e.id} className="flex gap-3 text-sm">
                  <span aria-hidden className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary" />
                  <div className="min-w-0">
                    <p className="font-semibold text-ink">{CONTRACT_EVENT_FR[e.type] ?? e.type.replace(/_/g, " ")}</p>
                    <p className="text-xs text-ash">{e.actor ? e.actor.name : "Tratra (automatique)"} · {dateTimeFr(e.at)}</p>
                  </div>
                </li>
              ))}
            </ol>
          )}
          {more !== null ? <Button className="mt-4" size="sm" variant="outline" onClick={() => void loadMore()}>Voir les événements plus anciens</Button> : null}
          {moreError ? <p role="alert" className="mt-2 text-xs text-dangerInk">{moreError}</p> : null}
        </LoadState>
      </Card>
    </div>
  );
}
