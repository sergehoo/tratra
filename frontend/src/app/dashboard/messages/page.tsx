"use client";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Ban, Check, CheckCheck, Clock, File as FileIcon, Flag, MessageSquare, MoreVertical, Paperclip, RotateCw, Search, Send, ShieldCheck, WifiOff, X } from "lucide-react";
import { ApiError, apiErrorMessage, del, get, post, uploadWithProgress } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDashboard } from "@/lib/dashboard";
import { useInbox, useInboxEvents, type ChatMessage, type Conversation } from "@/lib/inbox";
import { newClientId, compressImage } from "@/lib/statuses";
import { Alert, Avatar, Button, Card, EmptyState, Modal, PageHeader, SkeletonList, cx } from "@/components/ds";
import { formatDateTimeShort } from "../_components/dates";

interface Thread { conversation: Conversation; results: ChatMessage[]; has_more: boolean; next_before: number | null }
interface ListPage { results: Conversation[]; has_more: boolean; next_page: number | null; unread_total: number }
/** Message en cours d'envoi ou en échec : conservé localement avec son `client_id` pour un renvoi idempotent. */
type Local = ChatMessage & { local?: "sending" | "failed"; file?: File; progress?: number };

const ACCEPT = "image/jpeg,image/png,image/webp,video/mp4,video/quicktime,application/pdf";

function Ticks({ m }: { m: Local }) {
  if (!m.mine) return null;
  if (m.local === "sending") return <Clock aria-label="Envoi en cours" className="h-3 w-3" />;
  if (m.local === "failed") return <span className="font-bold text-dangerInk">Échec</span>;
  if (m.state === "read") return <CheckCheck aria-label="Lu" className="h-3.5 w-3.5 text-accent" />;
  if (m.state === "delivered") return <CheckCheck aria-label="Distribué" className="h-3.5 w-3.5" />;
  return <Check aria-label="Envoyé" className="h-3.5 w-3.5" />;
}

function Attachment({ m }: { m: Local }) {
  const a = m.attachment;
  if (!a?.url) return m.file ? <p className="mb-1 flex items-center gap-2 text-xs"><FileIcon aria-hidden className="h-4 w-4" />{m.file.name}</p> : null;
  if (m.kind === "image") return (
    <a href={a.url} target="_blank" rel="noopener noreferrer" className="mb-1 block">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={a.url} alt={m.content || "Photo envoyée"} loading="lazy" className="max-h-64 w-full rounded-xl object-cover" />
    </a>
  );
  if (m.kind === "video") return <video src={a.url} controls playsInline preload="metadata" className="mb-1 max-h-64 w-full rounded-xl bg-night" />;
  return <a href={a.url} target="_blank" rel="noopener noreferrer" className="mb-1 flex items-center gap-2 rounded-xl bg-black/10 px-3 py-2 text-sm underline"><FileIcon aria-hidden className="h-4 w-4" />{a.name || "Document PDF"}</a>;
}

function MessagesContent() {
  const router = useRouter();
  const params = useSearchParams();
  const { user } = useAuth();
  const dash = useDashboard();
  const inbox = useInbox();
  const selected = Number(params.get("c")) || null;
  const startWith = Number(params.get("u")) || null;

  const [convs, setConvs] = useState<Conversation[] | null>(null);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [listError, setListError] = useState("");
  const [query, setQuery] = useState("");
  const [thread, setThread] = useState<Thread | null>(null);
  const [messages, setMessages] = useState<Local[]>([]);
  const [threadError, setThreadError] = useState("");
  const [older, setOlder] = useState<{ more: boolean; before: number | null; loading: boolean }>({ more: false, before: null, loading: false });
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sendError, setSendError] = useState("");
  const [menu, setMenu] = useState(false);
  const [dialog, setDialog] = useState<"report" | null>(null);
  const [reason, setReason] = useState("");
  const [alsoBlock, setAlsoBlock] = useState(true);
  const bottom = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const stick = useRef(true);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;

  // ---- liste -----------------------------------------------------------------------------------------------------
  const loadList = useCallback(async (q = query, page = 1) => {
    try {
      const r = await get<ListPage>(`/me/conversations/?page=${page}${q ? `&q=${encodeURIComponent(q)}` : ""}`);
      setConvs((c) => (page === 1 ? r.results : [...(c ?? []), ...r.results]));
      setNextPage(r.next_page);
      setListError("");
    } catch (e) {
      setListError(apiErrorMessage(e, "Vos conversations ne peuvent pas être chargées."));
    }
  }, [query]);

  useEffect(() => {
    const t = setTimeout(() => void loadList(query, 1), query ? 250 : 0);
    return () => clearTimeout(t);
  }, [query, loadList]);

  // ---- fil ---------------------------------------------------------------------------------------------------------
  const markRead = useCallback(async (id: number) => {
    if (document.visibilityState !== "visible") return;
    try {
      await post(`/me/conversations/${id}/read/`);
      setConvs((c) => (c ?? []).map((x) => (x.id === id ? { ...x, unread: 0 } : x)));
      void inbox.refreshUnread();
      void dash.reload();
    } catch { /* sera réessayé au prochain évènement */ }
  }, [inbox, dash]);

  const loadThread = useCallback(async (id: number, keepLocal = true) => {
    try {
      const t = await get<Thread>(`/me/conversations/${id}/messages/?limit=40`);
      setThread(t);
      setOlder({ more: t.has_more, before: t.next_before, loading: false });
      setMessages((prev) => {
        const locals = keepLocal ? prev.filter((m) => m.local && m.conversation === id && !t.results.some((r) => r.client_id && r.client_id === m.client_id)) : [];
        return [...t.results, ...locals];
      });
      setThreadError("");
      if (t.results.some((m) => !m.mine && !m.is_read)) void markRead(id);
    } catch (e) {
      setThreadError(apiErrorMessage(e, "Cette conversation ne peut pas être chargée."));
    }
  }, [markRead]);

  useEffect(() => {
    setThread(null); setMessages([]); setThreadError(""); setSendError(""); setFile(null); setMenu(false);
    stick.current = true;
    if (selected) void loadThread(selected, false);
  }, [selected, loadThread]);

  // Ouverture directe d'un fil avec un membre (ex. depuis un profil) : /dashboard/messages?u=<id>
  useEffect(() => {
    if (!startWith || selected) return;
    post<{ id: number }>("/me/conversations/", { user: startWith })
      .then((r) => router.replace(`/dashboard/messages?c=${r.id}`))
      .catch((e) => setListError(apiErrorMessage(e, "La conversation n’a pas pu être ouverte.")));
  }, [startWith, selected, router]);

  useEffect(() => { if (stick.current) bottom.current?.scrollIntoView({ block: "end" }); }, [messages.length]);

  // ---- temps réel --------------------------------------------------------------------------------------------------
  useInboxEvents((e) => {
    if (e.type === "message") {
      setConvs((c) => {
        const rest = (c ?? []).filter((x) => x.id !== e.conversation.id);
        return [{ ...e.conversation, unread: e.conversation.id === selectedRef.current && !e.message.mine ? 0 : e.conversation.unread }, ...rest];
      });
      if (e.conversation.id === selectedRef.current) {
        setMessages((prev) => (prev.some((m) => m.id === e.message.id) ? prev : [...prev.filter((m) => !(m.local && m.client_id && m.client_id === e.message.client_id)), e.message]));
        if (!e.message.mine) void markRead(e.conversation.id);
      }
    } else if (e.type === "delivered") {
      setMessages((prev) => prev.map((m) => (e.ids.includes(m.id) && m.state === "sent" ? { ...m, state: "delivered" } : m)));
    } else if (e.type === "read" && e.conversation === selectedRef.current) {
      setMessages((prev) => prev.map((m) => (m.mine && m.id <= e.upto ? { ...m, state: "read", is_read: true } : m)));
    } else if (e.type === "resync") {
      void loadList(query, 1);
      if (selectedRef.current) void loadThread(selectedRef.current);   // rattrapage par l'API : rien n'est perdu pendant une coupure
    }
  });

  // ---- envoi -------------------------------------------------------------------------------------------------------
  const sendOne = useCallback(async (local: Local) => {
    setMessages((prev) => prev.map((m) => (m.client_id === local.client_id ? { ...m, local: "sending", progress: 0 } : m)));
    try {
      let saved: { message: ChatMessage };
      if (local.file) {
        const form = new FormData();
        form.set("content", local.content);
        form.set("client_id", local.client_id!);
        form.set("file", local.file);
        saved = await uploadWithProgress(`/me/conversations/${local.conversation}/send/`, form, (p) => setMessages((prev) => prev.map((m) => (m.client_id === local.client_id ? { ...m, progress: p } : m))));
      } else {
        saved = await post(`/me/conversations/${local.conversation}/send/`, { content: local.content, client_id: local.client_id });
      }
      setMessages((prev) => {
        const withoutLocal = prev.filter((m) => m.client_id !== local.client_id || !m.local);
        return withoutLocal.some((m) => m.id === saved.message.id) ? withoutLocal : [...withoutLocal, saved.message];
      });
      void loadList(query, 1);
    } catch (e) {
      const definitive = e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 408 && e.status !== 429;
      setMessages((prev) => prev.map((m) => (m.client_id === local.client_id ? { ...m, local: "failed" } : m)));
      setSendError(definitive ? apiErrorMessage(e, "Le message n’a pas pu être envoyé.") : "Connexion interrompue : le message est conservé, touchez « Renvoyer » (il ne sera envoyé qu’une fois).");
    }
  }, [loadList, query]);

  async function send() {
    const content = text.trim();
    if ((!content && !file) || !selected || !user) return;
    setSendError("");
    let toSend = file;
    if (toSend?.type.startsWith("image/")) toSend = await compressImage(toSend);
    const local: Local = {
      id: -Date.now(), conversation: selected, mine: true, content, kind: toSend ? (toSend.type.startsWith("image/") ? "image" : toSend.type.startsWith("video/") ? "video" : "file") : "text",
      created_at: new Date().toISOString(), is_read: false, state: "sent", client_id: newClientId(), sender: "", via_staff: false, attachment: null, context: null, local: "sending", file: toSend ?? undefined,
    };
    stick.current = true;
    setMessages((prev) => [...prev, local]);
    setText(""); setFile(null);
    void sendOne(local);
  }

  async function loadOlder() {
    if (!selected || !older.before || older.loading) return;
    setOlder((o) => ({ ...o, loading: true }));
    stick.current = false;
    try {
      const t = await get<Thread>(`/me/conversations/${selected}/messages/?limit=40&before=${older.before}`);
      setMessages((prev) => [...t.results, ...prev]);
      setOlder({ more: t.has_more, before: t.next_before, loading: false });
    } catch (e) {
      setSendError(apiErrorMessage(e, "Les messages précédents n’ont pas pu être chargés."));
      setOlder((o) => ({ ...o, loading: false }));
    }
  }

  async function report() {
    if (!selected) return;
    try {
      await post(`/me/conversations/${selected}/report/`, { reason, block: alsoBlock });
      setDialog(null); setReason("");
      void loadThread(selected); void loadList(query, 1);
      setSendError("");
    } catch (e) { setSendError(apiErrorMessage(e, "Le signalement n’a pas pu être envoyé.")); }
  }
  async function toggleBlock() {
    const c = thread?.conversation;
    if (!c?.counterpart_id) return;
    setMenu(false);
    try {
      if (c.blocked) await del(`/me/blocks/${c.counterpart_id}/`); else await post("/me/blocks/", { user: c.counterpart_id });
      void loadThread(c.id); void loadList(query, 1);
    } catch (e) { setSendError(apiErrorMessage(e, "L’opération n’a pas pu être enregistrée.")); }
  }

  const open = (id: number | null) => router.replace(id ? `/dashboard/messages?c=${id}` : "/dashboard/messages");
  const current = thread?.conversation ?? convs?.find((c) => c.id === selected) ?? null;
  const canWrite = !threadError && (current?.can_send ?? true);
  const support = current?.kind === "support";
  const networkNote = useMemo(() => inbox.status === "live" ? null : inbox.status === "connecting" ? "Connexion en cours…" : "Hors connexion : vos messages sont enregistrés et la liste se met à jour dès le retour du réseau.", [inbox.status]);

  const list = (
    <div className={cx("min-w-0 space-y-3", selected && "hidden lg:block")}>
      <div className="relative">
        <label htmlFor="conv-search" className="sr-only">Rechercher une conversation ou un message</label>
        <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ash" />
        <input id="conv-search" type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Rechercher…" className="min-h-11 w-full rounded-2xl border border-line bg-white pl-10 pr-3 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30" />
      </div>
      {convs === null && !listError ? (
        <SkeletonList count={4} />
      ) : listError ? (
        <Alert tone="danger" title="Messagerie indisponible" action={<Button size="sm" variant="outline" onClick={() => void loadList(query, 1)}>Réessayer</Button>}>{listError}</Alert>
      ) : convs && convs.length === 0 ? (
        <EmptyState icon={<MessageSquare />} title={query ? "Aucun résultat" : "Aucune conversation"} description={query ? "Essayez un autre mot." : "Ouvrez une réservation ou répondez à un statut pour écrire à un membre."} />
      ) : (
        <>
          <ul className="grid grid-cols-1 gap-2">
            {convs!.map((c) => (
              <li key={c.id}>
                <button type="button" onClick={() => open(c.id)} aria-current={c.id === selected ? "true" : undefined}
                  className={cx("flex w-full items-center gap-3 rounded-2xl border p-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary", c.id === selected ? "border-primary/40 bg-primarySoft/50" : "border-line bg-white hover:border-primary/30")}>
                  <Avatar name={c.counterpart} size={44} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center justify-between gap-2">
                      <span className={cx("flex min-w-0 items-center gap-1 truncate text-sm", c.unread ? "font-bold text-ink" : "font-semibold text-ink")}>
                        <span className="truncate">{c.counterpart}</span>{c.kind === "support" ? <ShieldCheck aria-label="Équipe Tratra" className="h-3.5 w-3.5 shrink-0 text-primary" /> : null}{c.blocked ? <Ban aria-label="Bloqué" className="h-3.5 w-3.5 shrink-0 text-ash" /> : null}
                      </span>
                      <span className="shrink-0 text-[11px] text-ash">{formatDateTimeShort(c.last_at)}</span>
                    </span>
                    <span className="flex items-center justify-between gap-2">
                      <span className={cx("truncate text-xs", c.unread ? "text-ink" : "text-ash")}>{c.last_message ?? "Aucun message pour le moment"}</span>
                      {c.unread ? <span className="grid h-5 min-w-5 shrink-0 place-items-center rounded-full bg-primary px-1 text-[11px] font-bold text-white">{c.unread > 99 ? "99+" : c.unread}</span> : null}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {nextPage ? <Button variant="outline" size="sm" block onClick={() => void loadList(query, nextPage)}>Voir plus</Button> : null}
        </>
      )}
    </div>
  );

  const pane = selected ? (
    <Card padding="none" radius="panel" className="flex h-[calc(100dvh-19rem)] min-h-[20rem] min-w-0 flex-col overflow-hidden lg:h-[36rem]">
      <div className="relative flex items-center gap-3 border-b border-line px-3 py-3">
        <button type="button" onClick={() => open(null)} aria-label="Retour aux conversations" className="grid h-10 w-10 place-items-center rounded-xl hover:bg-lineSoft lg:hidden"><ArrowLeft aria-hidden className="h-5 w-5" /></button>
        <Avatar name={current?.counterpart ?? ""} size={36} />
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1.5 truncate font-display text-[15px] font-bold text-ink">{current?.counterpart ?? "Conversation"}{support ? <ShieldCheck aria-hidden className="h-4 w-4 text-primary" /> : null}</p>
          {support ? <p className="text-[11px] text-ash">Messages officiels de l’équipe Tratra</p> : null}
        </div>
        {!support && current ? (
          <div className="relative">
            <button type="button" aria-label="Options de la conversation" aria-expanded={menu} onClick={() => setMenu((v) => !v)} className="grid h-10 w-10 place-items-center rounded-xl hover:bg-lineSoft"><MoreVertical aria-hidden className="h-5 w-5" /></button>
            {menu ? (
              <div role="menu" className="absolute right-0 top-full z-overlay mt-1 w-52 rounded-2xl border border-lineSoft bg-white p-1.5 shadow-strong">
                <button role="menuitem" type="button" onClick={() => { setMenu(false); setDialog("report"); }} className="flex min-h-11 w-full items-center gap-2 rounded-xl px-3 text-sm hover:bg-canvas"><Flag aria-hidden className="h-4 w-4" />Signaler</button>
                <button role="menuitem" type="button" onClick={() => void toggleBlock()} className="flex min-h-11 w-full items-center gap-2 rounded-xl px-3 text-sm hover:bg-canvas"><Ban aria-hidden className="h-4 w-4" />{current.blocked ? "Débloquer ce membre" : "Bloquer ce membre"}</button>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
      {networkNote ? <p role="status" className="flex items-center gap-2 bg-warningSoft px-3 py-1.5 text-xs text-warning"><WifiOff aria-hidden className="h-3.5 w-3.5" />{networkNote}</p> : null}
      <div className="flex-1 space-y-2 overflow-y-auto bg-surface px-3 py-4" aria-live="polite" onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }}>
        {older.more ? <div className="text-center"><Button size="sm" variant="ghost" loading={older.loading} onClick={() => void loadOlder()}>Messages précédents</Button></div> : null}
        {threadError ? (
          <Alert tone="danger">{threadError}</Alert>
        ) : !thread ? (
          <SkeletonList count={3} />
        ) : messages.length === 0 ? (
          <p className="py-10 text-center text-sm text-ash">Aucun message. Écrivez le premier.</p>
        ) : (
          messages.map((m) => (
            <div key={m.client_id && m.local ? `l-${m.client_id}` : m.id} className={cx("flex", m.mine ? "justify-end" : "justify-start")}>
              <div className={cx("max-w-[82%] rounded-2xl px-3.5 py-2 text-sm leading-snug", m.mine ? "rounded-br-md bg-primary text-white" : "rounded-bl-md border border-line bg-white text-ink", m.local === "failed" && "opacity-80 ring-2 ring-danger")}>
                {m.context?.status ? <p className={cx("mb-1 rounded-lg border-l-4 px-2 py-1 text-xs", m.mine ? "border-accent bg-white/15" : "border-primary bg-primarySoft/50")}>Réponse à un statut{m.context.text ? ` : « ${m.context.text} »` : ""}</p> : null}
                <Attachment m={m} />
                {m.content ? <p className="whitespace-pre-wrap break-words">{m.content}</p> : null}
                {m.local === "sending" && m.file ? <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round((m.progress ?? 0) * 100)} className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/30"><div className="h-full bg-white transition-[width]" style={{ width: `${Math.round((m.progress ?? 0) * 100)}%` }} /></div> : null}
                <p className={cx("mt-1 flex items-center justify-end gap-1 text-[10px]", m.mine ? "text-white/70" : "text-ash")}>
                  {formatDateTimeShort(m.created_at)}<Ticks m={m} />
                </p>
                {m.local === "failed" ? (
                  <div className="mt-1 flex gap-2">
                    <button type="button" onClick={() => void sendOne(m)} className="flex items-center gap-1 rounded-full bg-white px-2.5 py-1 text-xs font-bold text-primaryDark"><RotateCw aria-hidden className="h-3 w-3" />Renvoyer</button>
                    <button type="button" onClick={() => setMessages((p) => p.filter((x) => x.client_id !== m.client_id))} className="flex items-center gap-1 rounded-full bg-white/20 px-2.5 py-1 text-xs"><X aria-hidden className="h-3 w-3" />Supprimer</button>
                  </div>
                ) : null}
              </div>
            </div>
          ))
        )}
        <div ref={bottom} />
      </div>
      {sendError ? <div className="px-3 pt-2"><Alert tone="danger">{sendError}</Alert></div> : null}
      {current && !current.can_send ? <p className="border-t border-line bg-surface px-4 py-3 text-center text-sm text-ash">Vous ne pouvez plus écrire dans cette conversation.{current.blocked ? " Débloquez ce membre pour reprendre." : ""}</p> : (
        <form className="border-t border-line p-3" onSubmit={(e) => { e.preventDefault(); void send(); }}>
          {file ? <p className="mb-2 flex items-center gap-2 rounded-xl bg-primarySoft/50 px-3 py-1.5 text-xs text-ink"><FileIcon aria-hidden className="h-4 w-4" /><span className="min-w-0 flex-1 truncate">{file.name}</span><button type="button" aria-label="Retirer la pièce jointe" onClick={() => setFile(null)}><X aria-hidden className="h-4 w-4" /></button></p> : null}
          <div className="flex items-end gap-2">
            <input ref={fileInput} type="file" accept={ACCEPT} className="sr-only" tabIndex={-1} aria-label="Joindre une photo, une vidéo ou un PDF" onChange={(e) => { setFile(e.target.files?.[0] ?? null); e.target.value = ""; }} />
            <button type="button" aria-label="Joindre un fichier" disabled={!canWrite} onClick={() => fileInput.current?.click()} className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl border border-line text-ash hover:text-primary disabled:opacity-40"><Paperclip aria-hidden className="h-5 w-5" /></button>
            <label htmlFor="msg-input" className="sr-only">Votre message</label>
            <textarea id="msg-input" rows={1} value={text} maxLength={4000} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} placeholder="Votre message…"
              className="max-h-32 min-h-11 flex-1 resize-none rounded-2xl border border-line bg-white px-4 py-2.5 text-sm text-ink placeholder:text-ash focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30" />
            <Button type="submit" size="md" disabled={(!text.trim() && !file) || !canWrite} aria-label="Envoyer" leftIcon={<Send aria-hidden className="h-4 w-4" />}><span className="hidden sm:inline">Envoyer</span></Button>
          </div>
        </form>
      )}
    </Card>
  ) : (
    <div className="hidden lg:block"><EmptyState icon={<MessageSquare />} title="Sélectionnez une conversation" description="Vos échanges avec les artisans et les clients apparaissent ici." /></div>
  );

  return (
    <>
      <PageHeader title="Messages" description="Échangez avec vos artisans et vos clients ; les messages restent disponibles à chaque connexion." />
      {!selected && networkNote ? <Alert tone="warning" className="mb-4">{networkNote}</Alert> : null}
      <div className="grid gap-4 lg:grid-cols-[20rem_1fr]">
        {list}
        {pane}
      </div>
      <Modal open={dialog === "report"} onClose={() => setDialog(null)} title="Signaler cette conversation" description="L’équipe Tratra examinera le dernier message de ce membre."
        footer={<div className="flex w-full gap-2"><Button variant="ghost" block onClick={() => setDialog(null)}>Annuler</Button><Button block disabled={reason.trim().length < 3} onClick={() => void report()}>Envoyer</Button></div>}>
        <label htmlFor="report-reason" className="mb-1 block text-sm font-semibold text-ink">Motif</label>
        <textarea id="report-reason" rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} className="w-full rounded-xl border border-line px-3 py-2 text-sm focus:border-primary focus:outline-none" />
        <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" checked={alsoBlock} onChange={(e) => setAlsoBlock(e.target.checked)} />Bloquer aussi ce membre</label>
      </Modal>
    </>
  );
}

export default function MessagesPage() {
  return (
    <Suspense fallback={<SkeletonList count={4} />}>
      <MessagesContent />
    </Suspense>
  );
}
