"use client";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Eye, Inbox, Search, Send, Users } from "lucide-react";
import { Alert, Badge, Button, Card, EmptyState, PageHeader, Select, SkeletonList, Tabs, TextareaField, cx } from "@/components/ds";
import { bo, boError, type Page } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { dt } from "../_components/ui";

interface Thread { id: number; member: { id: number; name: string; phone: string | null } | null; last_message: string; last_at: string; unread: number }
interface ThreadMsg { id: number; from_member: boolean; staff: string | null; content: string; created_at: string; state: string }
interface Results { pending: number; sent: number; skipped_consent: number; skipped_unreachable: number; failed: number }
interface Batch { id: number; created_at: string; status: string; purpose: string; sender: string | null; body: string; recipient_count: number; selection: string; results: Results }
interface Delivery { user: number; name: string; phone: string | null; status: string; error: string; state: string | null }
interface UserRow { id: number; name: string; phone: string | null; city: string | null }
interface Preview { recipient_count: number; skipped: { no_consent: number; inactive: number }; sample: string[]; bulk: boolean; note: string; body: string }

const TABS = [{ id: "inbox", label: "Boîte de réception" }, { id: "compose", label: "Nouveau message" }, { id: "batches", label: "Envois" }] as const;
type TabId = (typeof TABS)[number]["id"];
const DELIVERY_FR: Record<string, string> = { pending: "En attente", sent: "Envoyé", skipped_consent: "Ignoré : pas de consentement marketing", skipped_unreachable: "Ignoré : compte inactif", failed: "Échec" };
const STATE_FR: Record<string, string> = { sent: "Envoyé", delivered: "Distribué", read: "Lu" };

function Inbox_() {
  const [threads, setThreads] = useState<Thread[] | null>(null);
  const [error, setError] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Thread | null>(null);
  const [msgs, setMsgs] = useState<ThreadMsg[]>([]);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await bo.get<Page<Thread>>(`/messages/threads/?${unreadOnly ? "unread=true&" : ""}${q ? `q=${encodeURIComponent(q)}` : ""}`);
      setThreads(r.results);
      setError("");
    } catch (e) { setError(boError(e, "La boîte de réception n’a pas pu être chargée.")); }
  }, [unreadOnly, q]);
  useEffect(() => { const t = setTimeout(() => void load(), q ? 250 : 0); return () => clearTimeout(t); }, [load, q]);

  async function openThread(t: Thread) {
    setOpen(t);
    try {
      const r = await bo.get<{ results: ThreadMsg[] }>(`/messages/threads/${t.id}/`);
      setMsgs(r.results);
      if (t.unread) { await bo.post(`/messages/threads/${t.id}/read/`); void load(); }
    } catch (e) { setError(boError(e, "La conversation n’a pas pu être chargée.")); }
  }
  async function sendReply() {
    if (!open || !reply.trim()) return;
    setBusy(true);
    try {
      await bo.post(`/messages/threads/${open.id}/reply/`, { content: reply });
      setReply("");
      await openThread({ ...open, unread: 0 });
      void load();
    } catch (e) { setError(boError(e, "La réponse n’a pas pu être envoyée.")); } finally { setBusy(false); }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
      <div className="space-y-3">
        <div className="flex gap-2">
          <div className="relative flex-1"><Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ash" /><label htmlFor="bo-thread-q" className="sr-only">Rechercher un membre</label><input id="bo-thread-q" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher un membre…" className="min-h-11 w-full rounded-xl border border-line bg-white pl-9 pr-3 text-sm focus:border-primary focus:outline-none" /></div>
          <Button variant={unreadOnly ? "primary" : "outline"} onClick={() => setUnreadOnly((v) => !v)} aria-pressed={unreadOnly}>Non lus</Button>
        </div>
        {error ? <Alert tone="danger">{error}</Alert> : null}
        {threads === null ? <SkeletonList count={4} /> : threads.length === 0 ? <EmptyState icon={<Inbox />} title="Aucune conversation" description="Les conversations « Équipe Tratra » apparaissent après un premier envoi à un membre." /> : (
          <ul className="space-y-2">
            {threads.map((t) => (
              <li key={t.id}>
                <button type="button" onClick={() => void openThread(t)} aria-current={open?.id === t.id ? "true" : undefined} className={cx("w-full rounded-2xl border p-3 text-left", open?.id === t.id ? "border-primary/40 bg-primarySoft/50" : "border-line bg-white hover:border-primary/30")}>
                  <span className="flex items-center justify-between gap-2"><span className="truncate text-sm font-bold text-ink">{t.member?.name ?? "Membre"}</span><span className="shrink-0 text-[11px] text-ash">{dt(t.last_at)}</span></span>
                  <span className="flex items-center justify-between gap-2"><span className="truncate text-xs text-ash">{t.last_message}</span>{t.unread ? <span className="grid h-5 min-w-5 place-items-center rounded-full bg-primary px-1 text-[11px] font-bold text-white">{t.unread}</span> : null}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <Card padding="none" className="flex min-h-[24rem] flex-col overflow-hidden">
        {!open ? <div className="grid flex-1 place-items-center p-8 text-sm text-ash">Sélectionnez une conversation.</div> : (
          <>
            <div className="border-b border-line px-4 py-3"><p className="font-display font-bold text-ink">{open.member?.name}</p><p className="text-xs text-ash">{open.member?.phone ?? ""}</p></div>
            <div className="flex-1 space-y-2 overflow-y-auto bg-surface p-4">
              {msgs.map((m) => (
                <div key={m.id} className={cx("flex", m.from_member ? "justify-start" : "justify-end")}>
                  <div className={cx("max-w-[80%] rounded-2xl px-3.5 py-2 text-sm", m.from_member ? "border border-line bg-white text-ink" : "bg-primary text-white")}>
                    {m.staff ? <p className="mb-0.5 text-[10px] font-bold opacity-80">{m.staff}</p> : null}
                    <p className="whitespace-pre-wrap break-words">{m.content}</p>
                    <p className="mt-1 text-[10px] opacity-70">{dt(m.created_at)}{!m.from_member ? ` · ${STATE_FR[m.state] ?? m.state}` : ""}</p>
                  </div>
                </div>
              ))}
            </div>
            <form className="flex items-end gap-2 border-t border-line p-3" onSubmit={(e) => { e.preventDefault(); void sendReply(); }}>
              <label htmlFor="bo-reply" className="sr-only">Votre réponse</label>
              <textarea id="bo-reply" rows={2} value={reply} maxLength={2000} onChange={(e) => setReply(e.target.value)} placeholder="Répondre au nom de l’équipe Tratra…" className="min-h-11 flex-1 resize-none rounded-xl border border-line px-3 py-2 text-sm focus:border-primary focus:outline-none" />
              <Button type="submit" loading={busy} disabled={!reply.trim()} leftIcon={<Send aria-hidden className="h-4 w-4" />}>Répondre</Button>
            </form>
          </>
        )}
      </Card>
    </div>
  );
}

function Compose({ onSent }: { onSent: () => void }) {
  const { can } = useBo();
  const params = useSearchParams();
  const bulk = can("messages.bulk");
  const [mode, setMode] = useState<"pick" | "filters">("pick");
  const [q, setQ] = useState("");
  const [found, setFound] = useState<UserRow[]>([]);
  const [picked, setPicked] = useState<UserRow[]>([]);
  const [filters, setFilters] = useState({ type: "", city: "", kyc: "", active_days: "" });
  const [body, setBody] = useState("");
  const [purpose, setPurpose] = useState("service");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Batch | null>(null);

  // Destinataire proposé depuis la fiche d'un compte : /backoffice/messages?tab=compose&user=<id>
  useEffect(() => {
    const id = Number(params.get("user"));
    if (!id) return;
    bo.get<Page<UserRow>>(`/users/?q=${id}`).catch(() => undefined);
    bo.get<{ id: number; name: string; phone: string | null; city: string | null }>(`/users/${id}/`).then((u) => setPicked([{ id: u.id, name: u.name, phone: u.phone, city: u.city }])).catch(() => undefined);
  }, [params]);
  useEffect(() => {
    if (q.trim().length < 2) { setFound([]); return; }
    const t = setTimeout(() => { bo.get<Page<UserRow>>(`/users/?q=${encodeURIComponent(q.trim())}&active=true`).then((r) => setFound(r.results.slice(0, 8))).catch(() => setFound([])); }, 250);
    return () => clearTimeout(t);
  }, [q]);

  const selection = () => mode === "pick" ? { user_ids: picked.map((p) => p.id) } : { filters: Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) };
  const ready = body.trim().length > 0 && (mode === "pick" ? picked.length > 0 : Object.values(filters).some(Boolean));

  async function doPreview() {
    setBusy(true); setError(""); setPreview(null);
    try { setPreview(await bo.post<Preview>("/messages/preview/", { ...selection(), body, purpose })); } catch (e) { setError(boError(e, "L’aperçu n’a pas pu être calculé.")); } finally { setBusy(false); }
  }
  async function doSend() {
    setBusy(true); setError("");
    try { setDone(await bo.post<Batch>("/messages/send/", { ...selection(), body, purpose })); setPreview(null); setBody(""); setPicked([]); onSent(); } catch (e) { setError(boError(e, "L’envoi n’a pas pu être effectué.")); } finally { setBusy(false); }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      {done ? <Alert tone="success" title="Envoi effectué">{done.results.sent} message{done.results.sent > 1 ? "s" : ""} envoyé{done.results.sent > 1 ? "s" : ""}{done.results.skipped_consent + done.results.skipped_unreachable ? `, ${done.results.skipped_consent + done.results.skipped_unreachable} ignoré(s)` : ""}{done.results.failed ? `, ${done.results.failed} en échec (réessayé automatiquement)` : ""}. Le détail est dans l’onglet « Envois ».</Alert> : null}
      <Card padding="md" className="space-y-4">
        <div role="tablist" aria-label="Choix des destinataires" className="grid grid-cols-2 gap-1 rounded-2xl bg-lineSoft p-1">
          <button type="button" role="tab" aria-selected={mode === "pick"} onClick={() => { setMode("pick"); setPreview(null); }} className={cx("min-h-11 rounded-xl text-sm font-semibold", mode === "pick" ? "bg-white text-primaryDark shadow-hair" : "text-ash")}>Choisir des membres</button>
          <button type="button" role="tab" aria-selected={mode === "filters"} disabled={!bulk} title={bulk ? undefined : "Droit « envoi en masse » requis"} onClick={() => { setMode("filters"); setPreview(null); }} className={cx("min-h-11 rounded-xl text-sm font-semibold disabled:opacity-40", mode === "filters" ? "bg-white text-primaryDark shadow-hair" : "text-ash")}>Par critères</button>
        </div>
        {mode === "pick" ? (
          <div className="space-y-3">
            <div className="relative"><Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ash" /><label htmlFor="bo-user-q" className="sr-only">Rechercher un membre</label><input id="bo-user-q" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nom, téléphone ou e-mail…" className="min-h-11 w-full rounded-xl border border-line pl-9 pr-3 text-sm focus:border-primary focus:outline-none" /></div>
            {found.length ? <ul className="divide-y divide-lineSoft rounded-xl border border-line">{found.filter((u) => !picked.some((p) => p.id === u.id)).map((u) => <li key={u.id}><button type="button" onClick={() => { setPicked([...picked, u]); setQ(""); setFound([]); setPreview(null); }} className="flex min-h-11 w-full items-center justify-between px-3 text-left text-sm hover:bg-canvas"><span className="font-semibold text-ink">{u.name}</span><span className="text-xs text-ash">{u.phone ?? ""}</span></button></li>)}</ul> : null}
            <ul className="flex flex-wrap gap-2" aria-label="Destinataires choisis">{picked.map((p) => <li key={p.id}><button type="button" onClick={() => { setPicked(picked.filter((x) => x.id !== p.id)); setPreview(null); }} aria-label={`Retirer ${p.name}`} className="inline-flex min-h-9 items-center gap-2 rounded-full bg-primarySoft px-3 text-sm font-semibold text-primaryDark">{p.name}<span aria-hidden>×</span></button></li>)}</ul>
            <p className="text-xs text-ash">{bulk ? "Jusqu’à 20 membres ici ; au-delà, utilisez « Par critères »." : "Jusqu’à 20 membres."}</p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm font-semibold text-ink">Type de membre<Select value={filters.type} onChange={(e) => { setFilters({ ...filters, type: e.target.value }); setPreview(null); }}><option value="">Tous</option><option value="client">Clients</option><option value="artisan">Artisans</option><option value="company">Entreprises</option></Select></label>
            <label className="text-sm font-semibold text-ink">État KYC<Select value={filters.kyc} onChange={(e) => { setFilters({ ...filters, kyc: e.target.value }); setPreview(null); }}><option value="">Tous</option><option value="pending">Pièces à examiner</option><option value="approved">Approuvé</option><option value="rejected">Refusé</option><option value="incomplete">Dossier incomplet</option></Select></label>
            <label className="text-sm font-semibold text-ink">Ville déclarée<input value={filters.city} onChange={(e) => { setFilters({ ...filters, city: e.target.value }); setPreview(null); }} className="mt-1 min-h-11 w-full rounded-xl border border-line px-3 text-sm font-normal focus:border-primary focus:outline-none" placeholder="Abidjan" /></label>
            <label className="text-sm font-semibold text-ink">Actifs depuis (jours)<input type="number" min={1} max={365} value={filters.active_days} onChange={(e) => { setFilters({ ...filters, active_days: e.target.value }); setPreview(null); }} className="mt-1 min-h-11 w-full rounded-xl border border-line px-3 text-sm font-normal focus:border-primary focus:outline-none" /></label>
          </div>
        )}
        <TextareaField label="Message" value={body} maxLength={2000} rows={5} onChange={(e) => { setBody(e.target.value); setPreview(null); }} hint="Chaque destinataire reçoit ce message dans sa propre conversation « Équipe Tratra »." />
        <label className="block text-sm font-semibold text-ink">Nature du message
          <Select value={purpose} onChange={(e) => { setPurpose(e.target.value); setPreview(null); }}><option value="service">Information de service</option><option value="promotion">Promotionnelle (consentement marketing requis)</option></Select>
        </label>
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <Button variant="outline" leftIcon={<Eye aria-hidden className="h-4 w-4" />} loading={busy && !preview} disabled={!ready} onClick={() => void doPreview()}>Prévisualiser</Button>
      </Card>
      {preview ? (
        <Card padding="md" className="space-y-3 border-primary/40">
          <h2 className="flex items-center gap-2 font-display text-base font-bold text-ink"><Users aria-hidden className="h-4 w-4 text-primary" />Aperçu avant envoi</h2>
          <p className="text-sm text-ink"><strong>{preview.recipient_count}</strong> destinataire{preview.recipient_count > 1 ? "s" : ""}{preview.sample.length ? ` — par exemple : ${preview.sample.join(", ")}` : ""}.</p>
          {preview.skipped.no_consent || preview.skipped.inactive ? <Alert tone="warning">{preview.skipped.no_consent ? `${preview.skipped.no_consent} membre(s) sans consentement marketing seront ignorés. ` : ""}{preview.skipped.inactive ? `${preview.skipped.inactive} compte(s) inactif(s) seront ignorés.` : ""}</Alert> : null}
          <blockquote className="whitespace-pre-wrap rounded-xl bg-surface p-3 text-sm text-ink">{preview.body}</blockquote>
          <p className="text-xs text-ash">{preview.note}</p>
          <Button leftIcon={<Send aria-hidden className="h-4 w-4" />} loading={busy} disabled={preview.recipient_count === 0} onClick={() => void doSend()}>Envoyer à {preview.recipient_count} membre{preview.recipient_count > 1 ? "s" : ""}</Button>
        </Card>
      ) : null}
    </div>
  );
}

function Batches({ refreshKey }: { refreshKey: number }) {
  const [batches, setBatches] = useState<Batch[] | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<Batch | null>(null);
  const [rows, setRows] = useState<Delivery[]>([]);
  useEffect(() => { bo.get<Page<Batch>>("/messages/batches/").then((r) => setBatches(r.results)).catch((e) => setError(boError(e, "L’historique n’a pas pu être chargé."))); }, [refreshKey]);
  async function show(b: Batch) {
    setOpen(b);
    try { setRows((await bo.get<{ deliveries: { results: Delivery[] } }>(`/messages/batches/${b.id}/`)).deliveries.results); } catch (e) { setError(boError(e, "Le détail n’a pas pu être chargé.")); }
  }
  if (error && !batches) return <Alert tone="danger">{error}</Alert>;
  if (!batches) return <SkeletonList count={3} />;
  if (!batches.length) return <EmptyState icon={<Send />} title="Aucun envoi" description="Les messages envoyés par l’équipe apparaissent ici avec leur résultat par destinataire." />;
  return (
    <div className="grid gap-4 lg:grid-cols-[24rem_1fr]">
      <ul className="space-y-2">
        {batches.map((b) => (
          <li key={b.id}><button type="button" onClick={() => void show(b)} className={cx("w-full rounded-2xl border p-3 text-left", open?.id === b.id ? "border-primary/40 bg-primarySoft/50" : "border-line bg-white hover:border-primary/30")}>
            <span className="flex items-center justify-between gap-2"><span className="text-sm font-bold text-ink">{b.recipient_count} destinataire{b.recipient_count > 1 ? "s" : ""}</span><Badge tone={b.status === "done" ? "success" : "info"}>{b.status === "done" ? "Terminé" : "En cours"}</Badge></span>
            <span className="block truncate text-xs text-ash">{b.body}</span>
            <span className="block text-[11px] text-ash">{dt(b.created_at)} · {b.sender ?? "—"} · {b.purpose === "promotion" ? "Promotionnel" : "Service"}</span>
          </button></li>
        ))}
      </ul>
      <Card padding="md">
        {!open ? <p className="py-10 text-center text-sm text-ash">Sélectionnez un envoi pour voir le résultat par destinataire.</p> : (
          <div className="space-y-3">
            <blockquote className="whitespace-pre-wrap rounded-xl bg-surface p-3 text-sm text-ink">{open.body}</blockquote>
            <ul className="flex flex-wrap gap-2 text-xs">{Object.entries(open.results).filter(([, n]) => n).map(([k, n]) => <li key={k}><Badge tone={k === "sent" ? "success" : k === "failed" ? "danger" : "warning"}>{DELIVERY_FR[k]} : {n}</Badge></li>)}</ul>
            <table className="w-full text-left text-sm"><thead className="text-xs text-ash"><tr><th className="py-1">Membre</th><th>Résultat</th><th>État</th></tr></thead><tbody>
              {rows.map((r) => <tr key={r.user} className="border-t border-lineSoft"><td className="py-2 font-semibold text-ink">{r.name}<span className="block text-xs font-normal text-ash">{r.phone}</span></td><td>{DELIVERY_FR[r.status] ?? r.status}</td><td>{r.state ? STATE_FR[r.state] ?? r.state : "—"}</td></tr>)}
            </tbody></table>
          </div>
        )}
      </Card>
    </div>
  );
}

function MessagesContent() {
  const params = useSearchParams();
  const [tab, setTab] = useState<TabId>((TABS.find((t) => t.id === params.get("tab"))?.id) ?? "inbox");
  const [bump, setBump] = useState(0);
  return (
    <>
      <PageHeader title="Messagerie" description="Écrivez à un membre ou à plusieurs : chacun reçoit son message dans sa propre conversation « Équipe Tratra »." />
      <Tabs ariaLabel="Messagerie" value={tab} onChange={setTab} items={TABS.map((t) => ({ id: t.id, label: t.label }))} />
      <div className="mt-5">
        {tab === "inbox" ? <Inbox_ /> : tab === "compose" ? <Compose onSent={() => setBump((b) => b + 1)} /> : <Batches refreshKey={bump} />}
      </div>
    </>
  );
}

export default function BoMessagesPage() {
  return <Suspense fallback={<SkeletonList count={3} />}><MessagesContent /></Suspense>;
}
