"use client";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, MessageSquare, Send } from "lucide-react";
import { apiErrorMessage, get, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDashboard } from "@/lib/dashboard";
import { Alert, Avatar, Button, Card, EmptyState, PageHeader, SkeletonList, cx } from "@/components/ds";
import { formatDateTimeShort } from "../_components/dates";

interface Conversation { id: number; booking_id: number | null; counterpart: string; last_message: string | null; last_at: string; unread: number }
interface Msg { id: number; mine: boolean; content: string; created_at: string; is_read: boolean }
interface Thread { conversation: Conversation; results: Msg[] }

const POLL_MS = 8000;

function MessagesContent() {
  const router = useRouter();
  const params = useSearchParams();
  const { user } = useAuth();
  const dash = useDashboard();
  const selected = Number(params.get("c")) || null;

  const [convs, setConvs] = useState<Conversation[] | null>(null);
  const [listError, setListError] = useState("");
  const [thread, setThread] = useState<Thread | null>(null);
  const [threadError, setThreadError] = useState("");
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");
  const bottom = useRef<HTMLDivElement>(null);

  const loadList = useCallback(async () => {
    try {
      const r = await get<{ results: Conversation[] }>("/me/conversations/");
      setConvs(r.results);
      setListError("");
    } catch (e) {
      setListError(apiErrorMessage(e, "Vos conversations ne peuvent pas être chargées."));
    }
  }, []);

  const loadThread = useCallback(async (id: number) => {
    try {
      const t = await get<Thread>(`/me/conversations/${id}/messages/`);
      setThread(t);
      setThreadError("");
      if (t.results.some((m) => !m.mine && !m.is_read)) {
        await post(`/me/conversations/${id}/messages/`);
        void dash.reload();
        void loadList();
      }
    } catch (e) {
      setThreadError(apiErrorMessage(e, "Cette conversation ne peut pas être chargée."));
    }
  }, [dash, loadList]);

  useEffect(() => { void loadList(); }, [loadList]);

  useEffect(() => {
    setThread(null);
    setThreadError("");
    setSendError("");
    if (!selected) return;
    void loadThread(selected);
    const t = setInterval(() => void loadThread(selected), POLL_MS);
    return () => clearInterval(t);
  }, [selected, loadThread]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [thread?.results.length]);

  async function send() {
    const content = text.trim();
    if (!content || !selected || !user) return;
    setSending(true);
    setSendError("");
    try {
      await post("/messages/", { conversation: selected, sender: user.id, content });
      setText("");
      await Promise.all([loadThread(selected), loadList()]);
    } catch (e) {
      setSendError(apiErrorMessage(e, "Le message n’a pas pu être envoyé."));
    } finally {
      setSending(false);
    }
  }

  const open = (id: number | null) => router.replace(id ? `/dashboard/messages?c=${id}` : "/dashboard/messages");

  const list = (
    <div className={cx("min-w-0", selected && "hidden lg:block")}>
      {convs === null && !listError ? (
        <SkeletonList count={4} />
      ) : listError ? (
        <Alert tone="danger" title="Messagerie indisponible" action={<Button size="sm" variant="outline" onClick={() => void loadList()}>Réessayer</Button>}>{listError}</Alert>
      ) : convs && convs.length === 0 ? (
        <EmptyState icon={<MessageSquare />} title="Aucune conversation"
          description="Ouvrez une réservation pour écrire à l’artisan ou au client concerné." />
      ) : (
        <ul className="grid grid-cols-1 gap-2">
          {convs!.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => open(c.id)}
                aria-current={c.id === selected ? "true" : undefined}
                className={cx(
                  "flex w-full items-center gap-3 rounded-2xl border p-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
                  c.id === selected ? "border-primary/40 bg-primarySoft/50" : "border-line bg-white hover:border-primary/30",
                )}
              >
                <Avatar name={c.counterpart} size={44} />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2">
                    <span className={cx("truncate text-sm", c.unread ? "font-bold text-ink" : "font-semibold text-ink")}>{c.counterpart}</span>
                    <span className="shrink-0 text-[11px] text-ash">{formatDateTimeShort(c.last_at)}</span>
                  </span>
                  <span className="flex items-center justify-between gap-2">
                    <span className={cx("truncate text-xs", c.unread ? "text-ink" : "text-ash")}>{c.last_message ?? "Aucun message pour le moment"}</span>
                    {c.unread ? <span className="grid h-5 min-w-5 shrink-0 place-items-center rounded-full bg-primary px-1 text-[11px] font-bold text-white">{c.unread}</span> : null}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  const pane = selected ? (
    <Card padding="none" radius="panel" className="flex h-[calc(100dvh-17rem)] min-h-[20rem] min-w-0 flex-col overflow-hidden lg:h-[34rem]">
      <div className="flex items-center gap-3 border-b border-line px-3 py-3">
        <button type="button" onClick={() => open(null)} aria-label="Retour aux conversations" className="grid h-10 w-10 place-items-center rounded-xl hover:bg-lineSoft lg:hidden">
          <ArrowLeft aria-hidden className="h-5 w-5" />
        </button>
        <Avatar name={thread?.conversation.counterpart ?? ""} size={36} />
        <p className="min-w-0 flex-1 truncate font-display text-[15px] font-bold text-ink">{thread?.conversation.counterpart ?? "Conversation"}</p>
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto bg-surface px-3 py-4" aria-live="polite">
        {threadError ? (
          <Alert tone="danger">{threadError}</Alert>
        ) : !thread ? (
          <SkeletonList count={3} />
        ) : thread.results.length === 0 ? (
          <p className="py-10 text-center text-sm text-ash">Aucun message. Écrivez le premier.</p>
        ) : (
          thread.results.map((m) => (
            <div key={m.id} className={cx("flex", m.mine ? "justify-end" : "justify-start")}>
              <div className={cx("max-w-[82%] rounded-2xl px-3.5 py-2 text-sm leading-snug", m.mine ? "rounded-br-md bg-primary text-white" : "rounded-bl-md border border-line bg-white text-ink")}>
                <p className="whitespace-pre-wrap break-words">{m.content}</p>
                <p className={cx("mt-1 text-[10px]", m.mine ? "text-white/70" : "text-ash")}>{formatDateTimeShort(m.created_at)}</p>
              </div>
            </div>
          ))
        )}
        <div ref={bottom} />
      </div>
      {sendError ? <div className="px-3 pt-2"><Alert tone="danger">{sendError}</Alert></div> : null}
      <form
        className="flex items-end gap-2 border-t border-line p-3"
        onSubmit={(e) => { e.preventDefault(); void send(); }}
      >
        <label htmlFor="msg-input" className="sr-only">Votre message</label>
        <textarea
          id="msg-input"
          rows={1}
          value={text}
          maxLength={2000}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }}
          placeholder="Votre message…"
          className="max-h-32 min-h-11 flex-1 resize-none rounded-2xl border border-line bg-white px-4 py-2.5 text-sm text-ink placeholder:text-ash focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
        />
        <Button type="submit" size="md" loading={sending} disabled={!text.trim() || Boolean(threadError)} aria-label="Envoyer" leftIcon={<Send aria-hidden className="h-4 w-4" />}>
          <span className="hidden sm:inline">Envoyer</span>
        </Button>
      </form>
    </Card>
  ) : (
    <div className="hidden lg:block">
      <EmptyState icon={<MessageSquare />} title="Sélectionnez une conversation" description="Vos échanges avec les artisans et les clients apparaissent ici." />
    </div>
  );

  return (
    <>
      <PageHeader title="Messages" description="Échangez avec vos artisans et vos clients à propos de vos réservations." />
      <div className="grid gap-4 lg:grid-cols-[20rem_1fr]">
        {list}
        {pane}
      </div>
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
