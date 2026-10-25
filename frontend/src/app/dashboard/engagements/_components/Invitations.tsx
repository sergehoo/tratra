"use client";
import Link from "next/link";
import { useState } from "react";
import { MailPlus, Send } from "lucide-react";
import { Alert, Badge, Button, Card, CardHeader, TextareaField } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api";
import { PERIOD_FR, eng, fcfa } from "@/lib/engagements";
import { LoadState, useLoad } from "./common";
import { WorkerPicker, type PickedWorker } from "./WorkerPicker";

export interface Invitation {
  id: number; status: "sent" | "accepted" | "declined" | "cancelled"; message: string; created_at: string; responded_at: string | null;
  posting: { id: number; title: string; category: string; city: string; amount: string | null; period: string; work_relationship: string };
  invitee: { name: string } | null; invited_by: { name: string } | null; application_id: number | null; can_respond: boolean;
}
const STATUS_FR = { sent: "Envoyée", accepted: "Candidature reçue", declined: "Déclinée", cancelled: "Retirée" } as const;

/** Auteur d'un besoin publié : inviter un professionnel VÉRIFIÉ à candidater (il reste libre d'accepter ou non). */
export function InvitePanel({ postingId }: { postingId: number }) {
  const { data, error, loading, reload } = useLoad(() => eng.get<{ results: Invitation[] }>(`/postings/${postingId}/invitations/`), [postingId]);
  const [worker, setWorker] = useState<PickedWorker | null>(null);
  const [pickerKey, setPickerKey] = useState(0); // nouvelle recherche vierge après chaque invitation envoyée
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function invite() {
    if (!worker) return;
    setBusy(true);
    setErr("");
    try {
      await eng.post(`/postings/${postingId}/invitations/`, { invitee: worker.id, message: message.trim() });
      setWorker(null);
      setPickerKey((k) => k + 1);
      setMessage("");
      await reload();
    } catch (e) {
      setErr(apiErrorMessage(e, "Invitation impossible."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card padding="md" className="mt-6">
      <CardHeader title="Inviter un professionnel" icon={<MailPlus className="h-5 w-5" />}
        description="Seuls les professionnels vérifiés peuvent être invités. L’invitation leur propose de candidater ; vous choisissez ensuite parmi les candidatures." />
      <div className="space-y-3">
        <WorkerPicker key={pickerKey} label="Professionnel vérifié" picked={worker} onPick={setWorker} />
        <TextareaField label="Message" optional rows={2} maxLength={500} value={message} onChange={(e) => setMessage(e.target.value)} />
        {err ? <Alert tone="danger">{err}</Alert> : null}
        <Button leftIcon={<Send aria-hidden className="h-4 w-4" />} disabled={!worker} loading={busy} onClick={() => void invite()}>Envoyer l’invitation</Button>
      </div>
      <LoadState loading={loading} error={error} hasData={Boolean(data)} reload={() => void reload()}>
        {data?.results.length ? (
          <ul className="mt-5 space-y-2 text-sm">
            {data.results.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 rounded-panel bg-canvas px-3 py-2">
                <span>{i.invitee?.name ?? "—"} <Badge tone={i.status === "accepted" ? "success" : i.status === "sent" ? "info" : "gray"}>{STATUS_FR[i.status]}</Badge></span>
                {i.status === "sent" ? (
                  <Button size="sm" variant="ghost" onClick={async () => { try { await eng.post(`/invitations/${i.id}/cancel/`); await reload(); } catch (e) { setErr(apiErrorMessage(e, "Retrait impossible.")); } }}>Retirer</Button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
      </LoadState>
    </Card>
  );
}

/** Professionnel : invitations reçues (candidater ou décliner). Rien n'est affiché sans invitation réelle. */
export function ReceivedInvitations({ onResponded }: { onResponded?: () => void }) {
  const { data, reload } = useLoad(() => eng.get<{ results: Invitation[] }>("/invitations/mine/"), []);
  const [err, setErr] = useState("");
  const open = (data?.results ?? []).filter((i) => i.can_respond);
  if (!open.length) return null;
  async function respond(i: Invitation, accept: boolean) {
    setErr("");
    try {
      await eng.post(`/invitations/${i.id}/respond/`, { accept });
      await reload();
      onResponded?.(); // « Candidature envoyée » sur l'offre concernée
    } catch (e) {
      setErr(apiErrorMessage(e, "Réponse impossible."));
    }
  }
  return (
    <Card variant="accent" padding="md" className="mb-6">
      <CardHeader title="Invitations à candidater" icon={<MailPlus className="h-5 w-5" />} description="Un donneur d’ordre vous propose de candidater. Candidater envoie votre candidature ; décliner le prévient." />
      {err ? <Alert tone="danger" className="mb-3">{err}</Alert> : null}
      <ul className="space-y-3">
        {open.map((i) => (
          <li key={i.id} className="rounded-panel border border-lineSoft p-3">
            <p className="font-semibold text-ink"><Link href={`/dashboard/engagements/postings/${i.posting.id}`} className="hover:underline">{i.posting.title}</Link></p>
            <p className="text-xs text-ash">{i.posting.category} · {i.posting.city} · {fcfa(i.posting.amount)} {PERIOD_FR[i.posting.period as keyof typeof PERIOD_FR] ?? ""}</p>
            {i.message ? <p className="mt-1 text-sm text-inkSoft">« {i.message} » — {i.invited_by?.name}</p> : null}
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" onClick={() => void respond(i, true)}>Candidater</Button>
              <Button size="sm" variant="ghost" onClick={() => void respond(i, false)}>Décliner</Button>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
