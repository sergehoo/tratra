"use client";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Eye, FileText, Film, Inbox, Paperclip, Search, Send, Users, X } from "lucide-react";
import { Alert, Badge, Button, Card, EmptyState, PageHeader, Select, SkeletonList, Tabs, TextareaField, cx } from "@/components/ds";
import { upload } from "@/lib/api";
import { newId } from "@/lib/assistant";
import { bo, boError, type Page } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { dt } from "../_components/ui";
import { AiDraftBar } from "./AiDraftBar";

interface Attachment { url: string | null; kind: "image" | "video" | "file"; mime: string; size: number; name: string; width?: number; height?: number; duration?: number }
interface Thread { id: number; member: { id: number; name: string; phone: string | null } | null; last_message: string; last_at: string; unread: number; awaiting_reply: boolean }
interface ThreadMsg { id: number; from_member: boolean; staff: string | null; content: string; created_at: string; state: string; kind: string; attachment: Attachment | null }
interface ThreadPage { results: ThreadMsg[]; has_more: boolean; next_before: number | null }
interface Results { pending: number; sent: number; skipped_consent: number; skipped_unreachable: number; failed: number }
interface Batch { id: number; created_at: string; status: string; purpose: string; sender: string | null; body: string; recipient_count: number; selection: string; results: Results }
interface Delivery { user: number; name: string; phone: string | null; status: string; error: string; state: string | null }
interface UserRow { id: number; name: string; phone: string | null; city: string | null }
interface Preview { recipient_count: number; skipped: { no_consent: number; inactive: number }; sample: string[]; bulk: boolean; note: string; body: string }

const TABS = [{ id: "inbox", label: "Boîte de réception" }, { id: "compose", label: "Nouveau message" }, { id: "batches", label: "Envois" }] as const;
type TabId = (typeof TABS)[number]["id"];
const DELIVERY_FR: Record<string, string> = { pending: "En attente", sent: "Envoyé", skipped_consent: "Ignoré : pas de consentement marketing", skipped_unreachable: "Ignoré : compte inactif", failed: "Échec" };
const STATE_FR: Record<string, string> = { sent: "Envoyé", delivered: "Distribué", read: "Lu" };
const POLL_MS = 10_000;
const ACCEPT = "image/jpeg,image/png,image/webp,video/mp4,video/quicktime,application/pdf";
const MAX_BYTES = { image: 10 * 1024 * 1024, video: 25 * 1024 * 1024, file: 10 * 1024 * 1024 };

const size = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1).replace(".", ",")} Mo` : `${Math.max(1, Math.round(n / 1024))} Ko`);
const safeUrl = (u: string | null | undefined) => (u && /^(https?:\/\/|\/)/i.test(u) && !u.startsWith("//") ? u : null);

function fileProblem(f: File): string | null {
  const kind = f.type.startsWith("image/") ? "image" : f.type.startsWith("video/") ? "video" : f.type === "application/pdf" ? "file" : null;
  if (!kind || !ACCEPT.split(",").includes(f.type)) return "Format non accepté : photo JPEG, PNG ou WebP, vidéo MP4 ou MOV, document PDF.";
  return f.size > MAX_BYTES[kind] ? `Fichier trop volumineux : ${size(MAX_BYTES[kind])} au maximum.` : null;
}

/** Actualisation périodique tant que l'onglet est visible (la messagerie reste vivante sans WebSocket côté équipe). */
function usePolling(callback: () => void, ms: number) {
  const saved = useRef(callback);
  useEffect(() => { saved.current = callback; }, [callback]);
  useEffect(() => {
    const t = setInterval(() => { if (document.visibilityState === "visible") saved.current(); }, ms);
    return () => clearInterval(t);
  }, [ms]);
}

function AttachmentView({ a, mine }: { a: Attachment; mine: boolean }) {
  const url = safeUrl(a.url);
  if (!url) return <p className="text-xs opacity-80">Pièce jointe indisponible.</p>;
  if (a.kind === "image") {
    return (
      <a href={url} target="_blank" rel="noopener noreferrer" className="mb-1 block" aria-label="Ouvrir la photo en grand">
        {/* eslint-disable-next-line @next/next/no-img-element -- média de la messagerie servi par l'API, taille déjà bornée côté serveur */}
        <img src={url} alt="Photo jointe au message" loading="lazy" width={a.width} height={a.height} className="max-h-56 w-auto max-w-full rounded-lg object-cover" />
      </a>
    );
  }
  const Icon = a.kind === "video" ? Film : FileText;
  const label = a.kind === "video" ? `Vidéo${a.duration ? ` · ${Math.round(a.duration)} s` : ""}` : "Document PDF";
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className={cx("mb-1 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold underline-offset-2 hover:underline", mine ? "border-white/40" : "border-line")}>
      <Icon aria-hidden className="h-4 w-4 shrink-0" /><span className="min-w-0 truncate">{label}{a.name ? ` — ${a.name}` : ""} ({size(a.size)})</span>
    </a>
  );
}

function Inbox_({ onActivity }: { onActivity: () => void }) {
  const [threads, setThreads] = useState<Thread[] | null>(null);
  const [error, setError] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Thread | null>(null);
  const [msgs, setMsgs] = useState<ThreadMsg[]>([]);
  const [more, setMore] = useState<{ has: boolean; before: number | null }>({ has: false, before: null });
  const [reply, setReply] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [aiAssisted, setAiAssisted] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const list = useRef<HTMLDivElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const picker = useRef<HTMLInputElement>(null);
  const attemptId = useRef(newId());                       // même identifiant tant que l'envoi n'a pas abouti : un rejeu ne crée jamais de doublon
  const openRef = useRef<Thread | null>(null);
  openRef.current = open;
  const msgsRef = useRef<ThreadMsg[]>([]);
  msgsRef.current = msgs;

  const loadThreads = useCallback(async () => {
    try {
      const r = await bo.get<Page<Thread>>(`/messages/threads/?${unreadOnly ? "unread=true&" : ""}${q ? `q=${encodeURIComponent(q)}` : ""}`);
      setThreads(r.results);
      setError("");
    } catch (e) { setError(boError(e, "La boîte de réception n’a pas pu être chargée.")); }
  }, [unreadOnly, q]);
  useEffect(() => { const t = setTimeout(() => void loadThreads(), q ? 250 : 0); return () => clearTimeout(t); }, [loadThreads, q]);

  useEffect(() => { if (stick.current) end.current?.scrollIntoView({ block: "end" }); }, [msgs]);

  async function markRead(id: number) {
    try { await bo.post(`/messages/threads/${id}/read/`); onActivity(); void loadThreads(); } catch { /* le compteur se corrigera à l'actualisation suivante */ }
  }

  async function openThread(t: Thread) {
    setOpen(t); setReply(""); setFile(null); setAiAssisted(false); setConfirming(false); setError("");
    attemptId.current = newId();
    stick.current = true;
    try {
      const r = await bo.get<ThreadPage>(`/messages/threads/${t.id}/`);
      setMsgs(r.results);
      setMore({ has: r.has_more, before: r.next_before });
      if (t.unread) void markRead(t.id);
    } catch (e) { setError(boError(e, "La conversation n’a pas pu être chargée.")); }
  }

  const refreshOpen = useCallback(async () => {
    const t = openRef.current;
    if (!t) return;
    const after = msgsRef.current[msgsRef.current.length - 1]?.id ?? 0;
    try {
      const r = await bo.get<ThreadPage>(`/messages/threads/${t.id}/?after=${after}`);
      if (!r.results.length || openRef.current?.id !== t.id) return;
      const el = list.current;
      stick.current = !el || el.scrollHeight - el.scrollTop - el.clientHeight < 120;
      setMsgs((m) => [...m, ...r.results.filter((n) => !m.some((x) => x.id === n.id))]);
      if (r.results.some((m) => m.from_member)) void markRead(t.id);
    } catch { /* coupure passagère : la prochaine actualisation rattrape */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- markRead ne dépend que de setters stables
  }, []);
  usePolling(() => { void loadThreads(); void refreshOpen(); onActivity(); }, POLL_MS);

  async function loadOlder() {
    if (!open || !more.before) return;
    setLoadingOlder(true);
    const el = list.current;
    const previousHeight = el?.scrollHeight ?? 0;
    try {
      const r = await bo.get<ThreadPage>(`/messages/threads/${open.id}/?before=${more.before}`);
      stick.current = false;
      setMsgs((m) => [...r.results, ...m]);
      setMore({ has: r.has_more, before: r.next_before });
      requestAnimationFrame(() => { if (el) el.scrollTop = el.scrollHeight - previousHeight; });
    } catch (e) { setError(boError(e, "Les messages précédents n’ont pas pu être chargés.")); } finally { setLoadingOlder(false); }
  }

  function pick(f: File | null) {
    if (!f) return;
    const problem = fileProblem(f);
    if (problem) { setError(problem); return; }
    setError("");
    setFile(f);
  }

  async function sendReply() {
    if (!open || (!reply.trim() && !file)) return;
    setBusy(true);
    try {
      if (file) {
        const form = new FormData();
        form.append("content", reply.trim());
        form.append("file", file);
        form.append("client_id", attemptId.current);
        await upload(`/backoffice/messages/threads/${open.id}/reply/`, form);
      } else {
        await bo.post(`/messages/threads/${open.id}/reply/`, { content: reply.trim(), client_id: attemptId.current });
      }
      attemptId.current = newId();
      setReply(""); setFile(null); setAiAssisted(false); setConfirming(false);
      stick.current = true;
      await refreshOpen();
      void loadThreads();
    } catch (e) { setError(boError(e, "La réponse n’a pas pu être envoyée.")); setConfirming(false); } finally { setBusy(false); }
  }
  function submit() {
    if (aiAssisted && !confirming) { setConfirming(true); return; }   // texte rédigé avec l'IA : confirmation humaine explicite avant tout envoi
    void sendReply();
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
      <div className="min-w-0 space-y-3">
        <div className="flex gap-2">
          <div className="relative min-w-0 flex-1"><Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ash" /><label htmlFor="bo-thread-q" className="sr-only">Rechercher un membre ou un mot dans les messages</label><input id="bo-thread-q" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Membre ou mot du message…" className="min-h-11 w-full rounded-xl border border-line bg-white pl-9 pr-3 text-sm focus:border-primary focus:outline-none" /></div>
          <Button variant={unreadOnly ? "primary" : "outline"} onClick={() => setUnreadOnly((v) => !v)} aria-pressed={unreadOnly}>Non lus</Button>
        </div>
        {error && !open ? <Alert tone="danger">{error}</Alert> : null}
        {threads === null ? <SkeletonList count={4} /> : threads.length === 0 ? <EmptyState icon={<Inbox />} title={q || unreadOnly ? "Aucune conversation ne correspond" : "Aucune conversation"} description={q || unreadOnly ? "Modifiez la recherche ou retirez le filtre « Non lus »." : "Les conversations « Équipe Tratra » apparaissent après un premier envoi à un membre."} /> : (
          <ul className="space-y-2">
            {threads.map((t) => (
              <li key={t.id}>
                <button type="button" onClick={() => void openThread(t)} aria-current={open?.id === t.id ? "true" : undefined} className={cx("w-full rounded-2xl border p-3 text-left", open?.id === t.id ? "border-primary/40 bg-primarySoft/50" : "border-line bg-white hover:border-primary/30")}>
                  <span className="flex items-center justify-between gap-2"><span className="truncate text-sm font-bold text-ink">{t.member?.name ?? "Membre"}</span><span className="shrink-0 text-[11px] text-ash">{dt(t.last_at)}</span></span>
                  <span className="flex items-center justify-between gap-2"><span className="truncate text-xs text-ash">{t.last_message}</span>
                    <span className="flex shrink-0 items-center gap-1.5">{t.awaiting_reply && !t.unread ? <Badge tone="warning">À répondre</Badge> : null}{t.unread ? <span aria-label={`${t.unread} non lu${t.unread > 1 ? "s" : ""}`} className="grid h-5 min-w-5 place-items-center rounded-full bg-primary px-1 text-[11px] font-bold text-white">{t.unread}</span> : null}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <Card padding="none" className="flex min-h-[24rem] min-w-0 flex-col overflow-hidden">
        {!open ? <div className="grid flex-1 place-items-center p-8 text-sm text-ash">Sélectionnez une conversation.</div> : (
          <>
            <div className="border-b border-line px-4 py-3"><p className="font-display font-bold text-ink">{open.member?.name}</p><p className="text-xs text-ash">{open.member?.phone ?? ""} · Les messages se mettent à jour automatiquement.</p></div>
            <div ref={list} className="max-h-[32rem] min-h-[16rem] flex-1 space-y-2 overflow-y-auto bg-surface p-4" aria-live="polite" aria-label="Messages de la conversation">
              {more.has ? <div className="text-center"><Button size="sm" variant="outline" loading={loadingOlder} onClick={() => void loadOlder()}>Messages précédents</Button></div> : null}
              {msgs.map((m) => (
                <div key={m.id} className={cx("flex", m.from_member ? "justify-start" : "justify-end")}>
                  <div className={cx("max-w-[80%] rounded-2xl px-3.5 py-2 text-sm", m.from_member ? "border border-line bg-white text-ink" : "bg-primaryDark text-white")}>
                    {m.staff ? <p className="mb-0.5 text-[10px] font-bold opacity-80">{m.staff}</p> : null}
                    {m.attachment ? <AttachmentView a={m.attachment} mine={!m.from_member} /> : null}
                    {m.content ? <p className="whitespace-pre-wrap break-words">{m.content}</p> : null}
                    <p className="mt-1 text-[10px] opacity-70">{dt(m.created_at)}{!m.from_member ? ` · ${STATE_FR[m.state] ?? m.state}` : ""}</p>
                  </div>
                </div>
              ))}
              <div ref={end} />
            </div>
            <form className="space-y-2 border-t border-line p-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
              {error ? <Alert tone="danger" onDismiss={() => setError("")}>{error}</Alert> : null}
              {file ? (
                <p className="flex items-center gap-2 rounded-xl bg-primarySoft px-3 py-2 text-xs font-semibold text-primaryDark"><Paperclip aria-hidden className="h-4 w-4" /><span className="min-w-0 flex-1 truncate">{file.name} ({size(file.size)})</span>
                  <button type="button" aria-label="Retirer la pièce jointe" onClick={() => setFile(null)} className="grid h-7 w-7 place-items-center rounded-full hover:bg-white"><X aria-hidden className="h-4 w-4" /></button></p>
              ) : null}
              <div className="flex items-end gap-2">
                <input ref={picker} type="file" accept={ACCEPT} className="sr-only" tabIndex={-1} aria-hidden onChange={(e) => { pick(e.target.files?.[0] ?? null); e.target.value = ""; }} />
                <button type="button" onClick={() => picker.current?.click()} aria-label="Joindre une photo, une vidéo ou un PDF" title="Photo JPEG/PNG/WebP, vidéo MP4/MOV, PDF" className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-line text-ash hover:border-primary/50 hover:text-primaryDark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"><Paperclip aria-hidden className="h-5 w-5" /></button>
                <label htmlFor="bo-reply" className="sr-only">Votre réponse</label>
                <textarea id="bo-reply" rows={2} value={reply} maxLength={2000} onChange={(e) => { setReply(e.target.value); setConfirming(false); }} placeholder="Répondre au nom de l’équipe Tratra…" className="min-h-11 flex-1 resize-none rounded-xl border border-line px-3 py-2 text-sm focus:border-primary focus:outline-none" />
                <Button type="submit" loading={busy} disabled={!reply.trim() && !file} leftIcon={<Send aria-hidden className="h-4 w-4" />}>Répondre</Button>
              </div>
              <AiDraftBar text={reply} thread={open.id} onUse={(d) => { setReply(d.slice(0, 2000)); setAiAssisted(true); setConfirming(false); }} />
              {confirming ? (
                <div role="alertdialog" aria-label="Confirmer l’envoi" className="space-y-2 rounded-2xl border border-warning/50 bg-warningSoft p-3 text-sm">
                  <p className="font-semibold text-warningInk">Texte rédigé avec l’IA : relisez-le avant l’envoi.</p>
                  <blockquote className="whitespace-pre-wrap rounded-lg bg-white p-3 text-ink">{reply}</blockquote>
                  <p className="text-xs text-inkSoft">Il sera envoyé à {open.member?.name ?? "ce membre"} au nom de l’équipe Tratra{file ? `, avec « ${file.name} »` : ""}.</p>
                  <div className="flex flex-wrap gap-2"><Button type="button" size="sm" loading={busy} onClick={() => void sendReply()}>Confirmer et envoyer</Button><Button type="button" size="sm" variant="outline" onClick={() => setConfirming(false)}>Modifier</Button></div>
                </div>
              ) : null}
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
  const [aiAssisted, setAiAssisted] = useState(false);
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
    try { setDone(await bo.post<Batch>("/messages/send/", { ...selection(), body, purpose })); setPreview(null); setBody(""); setPicked([]); setAiAssisted(false); onSent(); } catch (e) { setError(boError(e, "L’envoi n’a pas pu être effectué.")); } finally { setBusy(false); }
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
            <p className="text-xs text-ash">{bulk ? "Jusqu’à 20 membres ici ; au-delà, utilisez « Par critères »." : "Jusqu’à 20 membres."} Un membre qui a déjà une conversation reçoit le message dans la même conversation.</p>
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
        <AiDraftBar text={body} purpose={purpose} onUse={(d) => { setBody(d.slice(0, 2000)); setAiAssisted(true); setPreview(null); }} />
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
          {aiAssisted ? <p className="rounded-xl bg-primarySoft px-3 py-2 text-xs font-semibold text-primaryDark">Texte rédigé avec l’aide de l’IA : relisez-le ci-dessous. Il ne part qu’après votre clic sur « Envoyer ».</p> : null}
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
    <div className="grid gap-4 lg:grid-cols-[24rem_minmax(0,1fr)]">
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
  const [unread, setUnread] = useState(0);
  const refreshUnread = useCallback(async () => {
    try { setUnread((await bo.get<{ threads: number; messages: number }>("/messages/unread/")).threads); } catch { /* le badge se corrigera à l'actualisation suivante */ }
  }, []);
  useEffect(() => { void refreshUnread(); }, [refreshUnread]);
  return (
    <>
      <PageHeader title="Messagerie" description="Écrivez à un membre ou à plusieurs : chacun reçoit son message dans sa propre conversation « Équipe Tratra »." />
      <Tabs ariaLabel="Messagerie" value={tab} onChange={setTab} items={TABS.map((t) => ({ id: t.id, label: t.label, count: t.id === "inbox" && unread > 0 ? unread : undefined }))} />
      <div className="mt-5">
        {tab === "inbox" ? <Inbox_ onActivity={() => void refreshUnread()} /> : tab === "compose" ? <Compose onSent={() => setBump((b) => b + 1)} /> : <Batches refreshKey={bump} />}
      </div>
    </>
  );
}

export default function BoMessagesPage() {
  return <Suspense fallback={<SkeletonList count={3} />}><MessagesContent /></Suspense>;
}
