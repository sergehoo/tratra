"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Alert, Badge, Button, PageHeader, SkeletonList, TextareaField } from "@/components/ds";
import { bo, boError, fieldErrors } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useBoList, useDebounced } from "@/lib/useBoList";
import { KV, SearchBox, Section, STATUS_FR, Tag, dt, useNotice } from "../_components/ui";

interface QueueItem { kind: "dispute" | "report"; id: number; title: string; excerpt: string; status: string; who: string; created_at: string; age_hours: number; overdue: boolean; href: string }
interface Queue { count: number; overdue: number; results: QueueItem[]; sla_hours: { dispute: number; report: number } }
interface Overview {
  user: { id: number; name: string; phone: string | null; city: string | null; is_active: boolean; is_verified: boolean; date_joined: string; last_login: string | null };
  bookings: { id: number; status: string; role: string; service: string | null; booking_date: string }[];
  disputes: { id: number; booking_id: number; status: string; created_at: string }[];
  reports_filed: number;
  notifications: { title: string; category: string; at: string; push_status: string | null }[];
  notes: { id: number; body: string; author: string; created_at: string }[];
}
interface UserRow { id: number; name: string; phone: string | null; email: string | null; city: string | null }

function Lookup({ onPick, allowSearch }: { onPick: (id: number) => void; allowSearch: boolean }) {
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const list = useBoList<UserRow>("/users/", { q: allowSearch ? dq : "" }, 8);
  const numeric = /^\d+$/.test(q.trim());
  return (
    <div>
      <SearchBox value={q} onChange={setQ} label="Retrouver un compte" placeholder={allowSearch ? "Nom, téléphone, e-mail ou n° de compte…" : "N° de compte"} />
      {numeric ? <Button className="mt-3" size="sm" variant="outline" onClick={() => onPick(Number(q.trim()))}>Ouvrir le compte n°{q.trim()}</Button> : null}
      {allowSearch && dq.trim().length >= 2 ? (
        <ul className="mt-3 divide-y divide-lineSoft rounded-panel border border-lineSoft bg-white">
          {list.loading && list.rows.length === 0 ? <li className="px-3 py-2 text-sm text-ash">Recherche…</li> : null}
          {list.rows.map((u) => (
            <li key={u.id}><button type="button" onClick={() => onPick(u.id)} className="flex w-full min-h-[44px] items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
              <span className="font-semibold text-ink">{u.name} <span className="font-normal text-ash">#{u.id}</span></span><span className="text-ash">{[u.phone, u.city].filter(Boolean).join(" · ")}</span></button></li>
          ))}
          {!list.loading && list.rows.length === 0 && !list.error ? <li className="px-3 py-2 text-sm text-ash">Aucun compte trouvé.</li> : null}
          {list.error ? <li className="px-3 py-2 text-sm text-dangerInk">{list.error}</li> : null}
        </ul>
      ) : null}
    </div>
  );
}

export default function SupportPage() {
  const { can } = useBo();
  const [notice, setNotice] = useNotice();
  const [queue, setQueue] = useState<Queue | null>(null);
  const [queueError, setQueueError] = useState("");
  const [userId, setUserId] = useState<number | null>(null);
  const [ov, setOv] = useState<Overview | null>(null);
  const [ovError, setOvError] = useState("");
  const [note, setNote] = useState("");
  const [noteErrors, setNoteErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const loadQueue = useCallback(async () => {
    setQueueError("");
    try { setQueue(await bo.get<Queue>("/support/queue/")); } catch (e) { setQueueError(boError(e, "La file n’a pas pu être chargée.")); }
  }, []);
  useEffect(() => void loadQueue(), [loadQueue]);

  useEffect(() => {
    const u = new URLSearchParams(window.location.search).get("user");
    if (u && /^\d+$/.test(u)) setUserId(Number(u));
  }, []);

  const loadOverview = useCallback(async () => {
    if (userId === null) return;
    setOvError("");
    try { setOv(await bo.get<Overview>(`/support/users/${userId}/`)); } catch (e) { setOv(null); setOvError(boError(e, "Ce compte n’a pas pu être chargé.")); }
  }, [userId]);
  useEffect(() => { setOv(null); void loadOverview(); }, [loadOverview]);

  async function addNote() {
    setBusy(true);
    setNoteErrors({});
    try {
      await bo.post(`/support/users/${userId}/notes/`, { body: note });
      setNote("");
      setNotice("Note ajoutée.");
      await loadOverview();
    } catch (e) {
      setNoteErrors(fieldErrors(e));
      if (!Object.keys(fieldErrors(e)).length) setNotice(boError(e, "La note n’a pas pu être ajoutée."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Support" description="Ce qui attend une réponse humaine et le dossier d’un compte pour répondre. Les décisions (litiges, avis, suspension) se prennent dans leurs modules, avec leurs propres droits." />
      {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}
      <div className="grid gap-6 lg:grid-cols-5">
        <Section title="À traiter" className="lg:col-span-3" actions={queue ? <span className="text-xs text-ash">{queue.count} en attente · {queue.overdue} hors délai (litiges {queue.sla_hours.dispute} h, signalements {queue.sla_hours.report} h)</span> : undefined}>
          {queueError ? <Alert tone="danger" action={<Button size="sm" variant="outline" onClick={() => void loadQueue()}>Réessayer</Button>}>{queueError}</Alert> : !queue ? <SkeletonList count={3} /> : queue.results.length === 0 ? <p className="text-sm text-inkSoft">Rien n’attend de réponse. 🎉</p> : (
            <ul className="divide-y divide-lineSoft">
              {queue.results.map((i) => (
                <li key={`${i.kind}-${i.id}`}>
                  <Link href={i.href} className="block rounded-panel px-2 py-3 transition hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
                    <span className="flex flex-wrap items-center justify-between gap-2"><strong className="text-sm text-ink">{i.title}</strong>
                      <span className="flex gap-1.5">{i.overdue ? <Badge tone="danger">Hors délai</Badge> : null}<Badge tone="gray">{i.age_hours} h</Badge></span></span>
                    <span className="block text-sm text-inkSoft">{i.excerpt}</span>
                    <span className="block text-xs text-ash">{i.who} · {dt(i.created_at)} · {STATUS_FR[i.status] ?? i.status}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Dossier d’un compte" className="lg:col-span-2">
          <Lookup onPick={setUserId} allowSearch={can("users.view")} />
        </Section>
      </div>

      {userId !== null ? (
        <div className="mt-6">
          {ovError ? <Alert tone="danger">{ovError}</Alert> : !ov ? <SkeletonList count={3} /> : (
            <div className="grid gap-6 lg:grid-cols-2">
              <Section title={`${ov.user.name} · compte #${ov.user.id}`} actions={can("users.view") ? <Link href={`/backoffice/users/${ov.user.id}`} className="text-sm font-semibold text-primaryDark underline underline-offset-2">Fiche complète</Link> : undefined}>
                <KV items={[["Statut", <Badge key="a" tone={ov.user.is_active ? "success" : "danger"}>{ov.user.is_active ? "Actif" : "Suspendu"}</Badge>], ["Téléphone", ov.user.phone ?? "—"], ["Vérifié", ov.user.is_verified ? "Oui" : "Non"], ["Ville", ov.user.city ?? "—"], ["Inscrit le", dt(ov.user.date_joined)], ["Dernière connexion", dt(ov.user.last_login)], ["Signalements émis", ov.reports_filed]]} />
              </Section>
              <Section title="Notes internes">
                <p className="mb-3 text-xs text-ash">Jamais visibles de l’utilisateur. Le journal d’audit garde l’auteur et la date, pas le contenu.</p>
                <TextareaField label="Nouvelle note" value={note} error={noteErrors.body} onChange={(e) => setNote(e.target.value)} rows={3} />
                <Button className="mt-2" size="sm" loading={busy} disabled={note.trim().length < 3} onClick={() => void addNote()}>Ajouter la note</Button>
                {ov.notes.length ? <ul className="mt-4 divide-y divide-lineSoft text-sm">{ov.notes.map((n) => <li key={n.id} className="py-2"><p className="whitespace-pre-line text-ink">{n.body}</p><p className="text-xs text-ash">{n.author} · {dt(n.created_at)}</p></li>)}</ul> : <p className="mt-4 text-sm text-inkSoft">Aucune note.</p>}
              </Section>
              <Section title="Réservations récentes">
                {ov.bookings.length ? <ul className="space-y-1.5 text-sm">{ov.bookings.map((b) => <li key={b.id}>{can("bookings.view") ? <Link className="font-semibold text-primaryDark underline underline-offset-2" href={`/backoffice/bookings/${b.id}`}>#{b.id}</Link> : `#${b.id}`} — {b.service ?? "Intervention"} · {b.role === "client" ? "client" : "artisan"} · <Tag value={b.status} label={STATUS_FR[b.status]} /> · {dt(b.booking_date)}</li>)}</ul> : <p className="text-sm text-inkSoft">Aucune réservation.</p>}
                {ov.disputes.length ? <><h3 className="mb-1 mt-4 text-sm font-bold text-ink">Litiges</h3><ul className="space-y-1 text-sm">{ov.disputes.map((d) => <li key={d.id}><Link className="font-semibold text-primaryDark underline underline-offset-2" href={`/backoffice/bookings?tab=disputes&id=${d.id}`}>Litige #{d.id}</Link> — {STATUS_FR[d.status] ?? d.status} · {dt(d.created_at)}</li>)}</ul></> : null}
              </Section>
              <Section title="Dernières notifications (titres seulement)">
                {ov.notifications.length ? <ul className="space-y-1.5 text-sm">{ov.notifications.map((n, i) => <li key={i}>{n.title} <span className="text-ash">· {n.category} · {dt(n.at)}{n.push_status ? ` · push ${n.push_status}` : ""}</span></li>)}</ul> : <p className="text-sm text-inkSoft">Aucune notification.</p>}
              </Section>
            </div>
          )}
        </div>
      ) : null}
    </>
  );
}
