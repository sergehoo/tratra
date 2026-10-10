"use client";
import Link from "next/link";
import { useState } from "react";
import { Repeat } from "lucide-react";
import { Badge, Button, Card, EmptyState, PageHeader } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api";
import { ATTENDANCE_FR, EVENT_STATUS_FR, dateShortFr, eng, timeFr, type Page, type ReplacementRow } from "@/lib/engagements";
import { LoadState, useIntent, useLoad } from "../_components/common";

function Row({ e, onDone }: { e: ReplacementRow; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const intent = useIntent("attend");
  async function go(path: string, body: unknown, key?: string) {
    setBusy(true);
    setError("");
    try {
      await eng.post(path, body, key);
      onDone();
    } catch (err) {
      setError(apiErrorMessage(err, "Action impossible."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <li>
      <Card padding="none" className="p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 className="font-display text-base font-bold text-ink">{e.contract_title}</h2>
            <p className="mt-1 text-sm text-ash">{e.category} · {e.city} · {e.principal.name}</p>
            <p className="mt-1 text-sm font-semibold text-inkSoft">{dateShortFr(e.date)} · {timeFr(e.start_time)} – {timeFr(e.end_time)}</p>
          </div>
          <span className="flex gap-1.5">
            <Badge tone={e.replacement_status === "accepted" ? "success" : e.replacement_status === "proposed" ? "accent" : "gray"}>{e.replacement_status === "accepted" ? "Accepté" : e.replacement_status === "proposed" ? "Proposé" : "Refusé"}</Badge>
            <Badge tone="gray">{EVENT_STATUS_FR[e.status] ?? e.status}</Badge>
            {e.attendance_status !== "none" ? <Badge tone="info">{ATTENDANCE_FR[e.attendance_status]}</Badge> : null}
          </span>
        </div>
        {error ? <p role="alert" className="mt-2 text-xs font-medium text-dangerInk">{error}</p> : null}
        <div className="mt-3 flex flex-wrap gap-2">
          {e.can_answer_replacement ? (
            <>
              <Button size="sm" loading={busy} onClick={() => void go(`/events/${e.id}/replacement/respond/`, { accept: true })}>Accepter ce remplacement</Button>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => void go(`/events/${e.id}/replacement/respond/`, { accept: false })}>Refuser</Button>
            </>
          ) : null}
          {e.can_declare_attendance ? <Button size="sm" variant="soft" loading={busy} onClick={() => void go(`/events/${e.id}/attendance/`, {}, intent.key({ e: e.id }))}>Déclarer ma présence</Button> : null}
        </div>
        {e.can_answer_replacement ? <p className="mt-2 text-xs text-ash">Après votre acceptation, le donneur d’ordre doit encore valider le remplacement. Votre présence sera déclarée par vous, sans position GPS.</p> : null}
      </Card>
    </li>
  );
}

/** Espace du remplaçant : voit ses propres remplacements uniquement — jamais le contrat ni la rémunération. */
export default function ReplacementsPage() {
  const { data, error, loading, reload } = useLoad(() => eng.get<Page<ReplacementRow>>("/me/replacements/?limit=50"), []);
  return (
    <>
      <PageHeader back={{ href: "/dashboard/engagements", label: "Engagements" }} title="Mes remplacements" description="Interventions pour lesquelles on vous a proposé de remplacer le prestataire d’un contrat." />
      <LoadState loading={loading} error={error} hasData={Boolean(data)} reload={() => void reload()}>
        {data && data.results.length === 0 ? (
          <EmptyState icon={<Repeat aria-hidden />} title="Aucun remplacement" description="Quand un prestataire vous propose de le remplacer, la demande apparaît ici et vous êtes notifié(e)." />
        ) : (
          <ul className="grid gap-3">{data?.results.map((e) => <Row key={e.id} e={e} onDone={() => void reload()} />)}</ul>
        )}
      </LoadState>
      <p className="mt-6 text-xs text-ash"><Link href="/dashboard/engagements" className="underline">Retour aux engagements</Link></p>
    </>
  );
}
