"use client";
import Link from "next/link";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { ArrowUp, History as HistoryIcon, Info, Pencil, Plus, RefreshCw, ShieldCheck, Sparkles, Square, Trash2, X } from "lucide-react";
import { Alert, Badge, Button, ConfirmDialog, cx } from "@/components/ds";
import { assistantApi, type AssistantStatus, type ConversationRow, type Insight } from "@/lib/assistant";
import { boError } from "@/lib/bo";
import { parseBlocks, type Inline } from "@/lib/safeText";
import { dt } from "../ui";
import { loadSaved, persist, useAssistant, type UiMessage } from "./useAssistant";

const RING = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2";
const NOT_CONFIGURED = "IA non configurée";

const PROMPTS = [
  { tool: "security_events", label: "Synthèse sécurité", text: "Fais la synthèse des événements de sécurité des dernières 24 heures et dis ce qui mérite mon attention." },
  { tool: "account_alerts", label: "Alertes sur les comptes", text: "Quelles alertes sur les comptes dois-je traiter en priorité ?" },
  { tool: "booking_anomalies", label: "Anomalies de réservations", text: "Y a-t-il des anomalies sur les réservations ces 30 derniers jours ?" },
  { tool: "kyc_overview", label: "File KYC", text: "Où en est la file de vérification KYC et quelles pièces attendent depuis le plus longtemps ?" },
  { tool: "communications_overview", label: "Messagerie en attente", text: "Quelles conversations attendent une réponse de l’équipe ?" },
  { tool: "platform_overview", label: "Vue d’ensemble", text: "Donne-moi une vue d’ensemble de la plateforme." },
];

function InlineText({ parts }: { parts: Inline[] }) {
  return (
    <>
      {parts.map((p, i) =>
        p.t === "bold" ? <strong key={i}>{p.v}</strong> : p.t === "link" ? <Link key={i} href={p.href} className="font-semibold text-primaryDark underline underline-offset-2">{p.v}</Link> : <span key={i}>{p.v}</span>,
      )}
    </>
  );
}

/** Rendu SÛR : gras, listes et liens internes du Back-Office uniquement (voir lib/safeText.ts) ; jamais de HTML. */
function SafeText({ text }: { text: string }) {
  const blocks = useMemo(() => parseBlocks(text), [text]);
  return (
    <div className="space-y-2 break-words">
      {blocks.map((b, i) =>
        b.t === "ul" ? (
          <ul key={i} className="list-disc space-y-1 pl-5">{b.items.map((it, j) => <li key={j}><InlineText parts={it} /></li>)}</ul>
        ) : (
          <p key={i}><InlineText parts={b.inline} /></p>
        ),
      )}
    </div>
  );
}

function Bubble({ m, onRetry }: { m: UiMessage; onRetry: (m: UiMessage) => void }) {
  const mine = m.role === "user";
  return (
    <div className={cx("flex", mine ? "justify-end" : "justify-start")}>
      <div className={cx("max-w-[92%] rounded-2xl px-3.5 py-2.5 text-sm", mine ? "bg-primaryDark text-white" : "border border-line bg-white text-ink")}>
        {mine ? <p className="whitespace-pre-wrap break-words">{m.content}</p> : m.content ? <SafeText text={m.content} /> : null}
        {!mine && m.streaming && !m.content ? (
          <p className="flex items-center gap-2 text-ash" aria-hidden>
            <span className="inline-flex gap-1"><i className="h-1.5 w-1.5 rounded-full bg-ash motion-safe:animate-pulse" /><i className="h-1.5 w-1.5 rounded-full bg-ash motion-safe:animate-pulse [animation-delay:150ms]" /><i className="h-1.5 w-1.5 rounded-full bg-ash motion-safe:animate-pulse [animation-delay:300ms]" /></span>
            {m.statusLabel ?? "Réflexion…"}
          </p>
        ) : null}
        {!mine && m.streaming && m.content && m.statusLabel ? <p className="mt-1 text-xs text-ash">{m.statusLabel}</p> : null}
        {!mine && m.sources.length ? (
          <p className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-lineSoft pt-2 text-[11px] text-ash">
            <ShieldCheck aria-hidden className="h-3.5 w-3.5 text-primary" />Sources :
            {m.sources.map((s, i) => <Badge key={`${s.tool}-${i}`} tone={s.ok ? "gray" : "warning"}>{s.label}{s.ok ? "" : " (refusé)"}</Badge>)}
          </p>
        ) : null}
        {!mine && !m.streaming && !m.sources.length && m.content && !m.error ? <p className="mt-2 border-t border-lineSoft pt-2 text-[11px] text-ash">Réponse sans consultation de données : à ne pas citer comme un chiffre.</p> : null}
        {m.error ? <p className="mt-2 text-xs font-semibold text-dangerInk" role="alert">{m.error.detail}</p> : null}
        {m.stopped ? <p className="mt-2 text-xs text-ash">Réponse arrêtée.</p> : null}
        {m.failed ? (
          <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-dangerInk" role="alert">
            Connexion interrompue.
            <button type="button" onClick={() => onRetry(m)} className={cx("rounded-full border border-line bg-white px-2.5 py-1 font-semibold text-ink hover:border-primary/50", RING)}>Réessayer</button>
          </p>
        ) : null}
      </div>
    </div>
  );
}

function Composer({ status, busy, onSend, onStop, inputRef }: { status: AssistantStatus | null; busy: boolean; onSend: (text: string) => void; onStop: () => void; inputRef: React.RefObject<HTMLTextAreaElement> }) {
  const [text, setText] = useState("");
  const max = status?.limits.max_input_chars ?? 2000;
  const loading = status === null;
  const disabled = loading || !status.configured;
  const id = useId();
  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!text.trim() || busy || disabled) return;
    onSend(text);
    setText("");
  }
  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) submit(e);
  }
  return (
    <form onSubmit={submit} className="border-t border-line bg-white p-3">
      <label htmlFor={id} className="sr-only">Votre question à Tratra AI</label>
      <div className="flex items-end gap-2">
        <textarea
          ref={inputRef}
          id={id}
          rows={2}
          value={text}
          maxLength={max}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          placeholder={loading ? "Chargement…" : disabled ? NOT_CONFIGURED : "Posez une question sur la plateforme…"}
          className="min-h-11 flex-1 resize-none rounded-xl border border-line px-3 py-2 text-sm focus:border-primary focus:outline-none disabled:bg-lineSoft disabled:text-ash"
        />
        {busy ? (
          <Button type="button" variant="outline" onClick={onStop} aria-label="Arrêter la réponse" leftIcon={<Square aria-hidden className="h-4 w-4" />}>Stop</Button>
        ) : (
          <Button type="submit" disabled={disabled || !text.trim()} aria-label="Envoyer la question" leftIcon={<ArrowUp aria-hidden className="h-4 w-4" />}>Envoyer</Button>
        )}
      </div>
      <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-snug text-ash">
        <Info aria-hidden className="mt-0.5 h-3 w-3 shrink-0" />
        <span>Lecture seule : l’IA propose, vous décidez. Aucune action n’est exécutée. Les coordonnées sont masquées et rien de biométrique n’est transmis. Entrée pour envoyer, Maj+Entrée pour un retour à la ligne.</span>
      </p>
    </form>
  );
}

function Chat({ a, status, onGoInsights }: { a: ReturnType<typeof useAssistant>; status: AssistantStatus | null; onGoInsights: () => void }) {
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = list.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 160;
    if (near || a.busy) end.current?.scrollIntoView({ block: "end" });
  }, [a.messages, a.busy]);
  useEffect(() => input.current?.focus(), [a.convId]);
  const prompts = PROMPTS.filter((p) => status?.tools.some((t) => t.name === p.tool));
  const announce = a.busy ? "Tratra AI répond…" : a.messages.length ? "Réponse reçue." : "";
  return (
    <>
      <div ref={list} className="flex-1 space-y-3 overflow-y-auto bg-surface p-3">
        {status && !status.configured ? (
          <Alert tone="warning" title={NOT_CONFIGURED}>
            {status.message === "IA non configurée." || !status.message ? "Aucune clé de fournisseur d’IA n’est définie sur le serveur : l’assistant ne peut pas répondre. " : `${status.message} `}
            Les synthèses de gestion restent disponibles : elles reposent sur des règles et non sur l’IA.
            <button type="button" onClick={onGoInsights} className={cx("mt-2 block rounded font-semibold text-primaryDark underline underline-offset-2", RING)}>Ouvrir les synthèses</button>
          </Alert>
        ) : null}
        {a.notice ? <Alert tone="danger" onDismiss={() => a.setNotice("")}>{a.notice}</Alert> : null}
        {!a.messages.length && status?.configured ? (
          <div className="space-y-3 py-2">
            <p className="text-sm text-inkSoft">Je consulte les données réelles de la plateforme selon vos droits, sans jamais rien modifier. Par exemple :</p>
            <ul className="flex flex-wrap gap-2">
              {prompts.map((p) => (
                <li key={p.tool}><button type="button" onClick={() => void a.send(p.text)} disabled={a.busy} className={cx("rounded-full border border-line bg-white px-3 py-1.5 text-xs font-semibold text-inkSoft hover:border-primary/50 hover:text-primaryDark disabled:opacity-50", RING)}>{p.label}</button></li>
              ))}
            </ul>
          </div>
        ) : null}
        {a.statusError ? <Alert tone="danger">{a.statusError}</Alert> : null}
        {a.messages.map((m) => (
          <Bubble key={m.id} m={m} onRetry={(failed) => { const q = a.messages.find((x) => x.role === "user" && x.clientId === failed.clientId); if (q) void a.send(q.content, failed.clientId); }} />
        ))}
        <div ref={end} />
        <div className="sr-only" role="status" aria-live="polite">{announce}</div>
      </div>
      <Composer status={status} busy={a.busy} onSend={(t) => void a.send(t)} onStop={a.stop} inputRef={input} />
    </>
  );
}

function History({ a, onOpen }: { a: ReturnType<typeof useAssistant>; onOpen: () => void }) {
  const [rows, setRows] = useState<ConversationRow[] | null>(null);
  const [q, setQ] = useState("");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<{ id: number; title: string } | null>(null);
  const [removing, setRemoving] = useState<ConversationRow | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      setRows((await assistantApi.conversations(q.trim())).results);
      setError("");
    } catch (e) {
      setError(boError(e, "L’historique n’a pas pu être chargé."));
    }
  }, [q]);
  useEffect(() => {
    const t = setTimeout(() => void load(), q ? 250 : 0);
    return () => clearTimeout(t);
  }, [load, q, a.historyVersion]);
  async function rename() {
    if (!editing?.title.trim()) return;
    try {
      await assistantApi.rename(editing.id, editing.title.trim());
      setEditing(null);
      void load();
    } catch (e) {
      setError(boError(e, "Le titre n’a pas pu être modifié."));
    }
  }
  async function remove() {
    if (!removing) return;
    setBusy(true);
    try {
      await assistantApi.remove(removing.id);
      if (removing.id === a.convId) a.newConversation();
      setRemoving(null);
      void load();
    } catch (e) {
      setError(boError(e, "La conversation n’a pas pu être supprimée."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="flex-1 space-y-3 overflow-y-auto bg-surface p-3">
      <label htmlFor="ai-history-q" className="sr-only">Rechercher dans mes conversations</label>
      <input id="ai-history-q" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher dans mes conversations…" className="min-h-11 w-full rounded-xl border border-line bg-white px-3 text-sm focus:border-primary focus:outline-none" />
      <p className="text-[11px] text-ash">Vos conversations sont privées : aucun autre administrateur ne peut les lire. Elles sont conservées {a.status?.retention_days ?? 90} jours après la dernière activité.</p>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {rows === null ? <p className="py-6 text-center text-sm text-ash">Chargement…</p> : rows.length === 0 ? <p className="py-6 text-center text-sm text-ash">{q ? "Aucune conversation ne correspond." : "Aucune conversation pour le moment."}</p> : (
        <ul className="space-y-2">
          {rows.map((r) => (
            <li key={r.id} className={cx("rounded-2xl border bg-white p-3", r.id === a.convId ? "border-primary/40" : "border-line")}>
              {editing?.id === r.id ? (
                <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void rename(); }}>
                  <label htmlFor={`ai-title-${r.id}`} className="sr-only">Titre de la conversation</label>
                  <input id={`ai-title-${r.id}`} autoFocus value={editing.title} maxLength={80} onChange={(e) => setEditing({ id: r.id, title: e.target.value })} className="min-h-10 flex-1 rounded-lg border border-line px-2 text-sm focus:border-primary focus:outline-none" />
                  <Button size="sm" type="submit">Enregistrer</Button>
                  <Button size="sm" variant="ghost" type="button" onClick={() => setEditing(null)}>Annuler</Button>
                </form>
              ) : (
                <div className="flex items-start gap-2">
                  <button type="button" onClick={() => { void a.openConversation(r.id); onOpen(); }} className={cx("min-w-0 flex-1 rounded text-left", RING)}>
                    <span className="block truncate text-sm font-semibold text-ink">{r.title}</span>
                    <span className="block text-[11px] text-ash">{dt(r.updated_at)}</span>
                  </button>
                  <button type="button" aria-label={`Renommer « ${r.title} »`} onClick={() => setEditing({ id: r.id, title: r.title })} className={cx("grid h-9 w-9 place-items-center rounded-full text-ash hover:bg-lineSoft hover:text-ink", RING)}><Pencil aria-hidden className="h-4 w-4" /></button>
                  <button type="button" aria-label={`Supprimer « ${r.title} »`} onClick={() => setRemoving(r)} className={cx("grid h-9 w-9 place-items-center rounded-full text-ash hover:bg-dangerSoft hover:text-dangerInk", RING)}><Trash2 aria-hidden className="h-4 w-4" /></button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog open={removing !== null} onClose={() => setRemoving(null)} onConfirm={() => void remove()} loading={busy} tone="danger" title="Supprimer cette conversation ?" description="Elle disparaît de votre historique. Cette action ne modifie aucune donnée de la plateforme." confirmLabel="Supprimer" />
    </div>
  );
}

const STAT_LABEL: Record<string, string> = {
  members: "Membres", active: "Comptes actifs", verified_phone: "Téléphones vérifiés", new_24h: "Nouveaux (24 h)", new_7d: "Nouveaux (7 j)", new_30d: "Nouveaux (30 j)", artisans: "Artisans",
  artisans_approved: "Artisans approuvés", kyc_pending_documents: "Pièces KYC en attente", risk_cases_active: "Dossiers de risque actifs", reports_unresolved: "Signalements non traités",
  failed_logins_24h: "Échecs de connexion (24 h)", sources_failing_24h: "Sources en échec (24 h)", locked_now: "Sources bloquées", successful_logins_24h: "Connexions réussies (24 h)",
  distinct_accounts_logged_in_24h: "Comptes connectés (24 h)", staff_mfa_locked: "Comptes admin verrouillés", ip_blacklist_entries: "Adresses en liste noire",
  created: "Réservations créées (30 j)", cancellation_rate: "Taux d’annulation", completion_rate: "Taux de réalisation", disputes_open: "Litiges ouverts",
};
const SEVERITY: Record<string, { tone: "danger" | "warning" | "info"; label: string }> = { danger: { tone: "danger", label: "À examiner vite" }, warning: { tone: "warning", label: "À surveiller" }, info: { tone: "info", label: "Information" } };
const SCOPES = [{ id: "accounts", label: "Comptes" }, { id: "security", label: "Sécurité" }, { id: "bookings", label: "Réservations" }] as const;

function statValue(key: string, v: unknown): string | null {
  if (typeof v !== "number") return null;
  return key.endsWith("_rate") ? `${Math.round(v * 1000) / 10} %` : String(v);
}

function Insights({ status, onAsk }: { status: AssistantStatus | null; onAsk: (text: string) => void }) {
  const scopes = SCOPES.filter((s) => status?.scopes[s.id]);
  const [scope, setScope] = useState<(typeof SCOPES)[number]["id"] | null>(null);
  const [data, setData] = useState<Insight | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const current = scope ?? scopes[0]?.id ?? null;
  const load = useCallback(async () => {
    if (!current) return;
    setLoading(true);
    try {
      setData(await assistantApi.insights(current));
      setError("");
    } catch (e) {
      setData(null);
      setError(boError(e, "La synthèse n’a pas pu être calculée."));
    } finally {
      setLoading(false);
    }
  }, [current]);
  useEffect(() => { void load(); }, [load]);
  if (!status) return <div className="flex-1 bg-surface p-4 text-sm text-ash">Chargement…</div>;
  if (!scopes.length) return <div className="flex-1 bg-surface p-4"><Alert tone="info">Votre rôle ne donne accès à aucune synthèse de gestion.</Alert></div>;
  return (
    <div className="flex-1 space-y-3 overflow-y-auto bg-surface p-3">
      <div className="flex items-center gap-2">
        <div role="tablist" aria-label="Synthèses" className="grid flex-1 gap-1 rounded-xl bg-lineSoft p-1" style={{ gridTemplateColumns: `repeat(${scopes.length}, minmax(0, 1fr))` }}>
          {scopes.map((s) => (
            <button key={s.id} type="button" role="tab" aria-selected={current === s.id} onClick={() => setScope(s.id)} className={cx("min-h-10 rounded-lg text-sm font-semibold", RING, current === s.id ? "bg-white text-primaryDark shadow-hair" : "text-ash")}>{s.label}</button>
          ))}
        </div>
        <button type="button" onClick={() => void load()} aria-label="Actualiser la synthèse" disabled={loading} className={cx("grid h-10 w-10 place-items-center rounded-full border border-line bg-white text-ash hover:text-ink disabled:opacity-50", RING)}><RefreshCw aria-hidden className={cx("h-4 w-4", loading && "motion-safe:animate-spin")} /></button>
      </div>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {data ? (
        <>
          <p className="text-[11px] text-ash">Calculé le {dt(data.generated_at)} · {data.note}</p>
          {data.omitted.length ? <p className="text-[11px] text-ash">Sections non affichées faute de droit : {data.omitted.join(", ")}.</p> : null}
          {data.alerts.length === 0 ? <Alert tone="success">Aucune alerte selon les règles actuelles.</Alert> : (
            <ul className="space-y-2">
              {data.alerts.map((al) => (
                <li key={al.key} className="rounded-2xl border border-line bg-white p-3 text-sm">
                  <p className="flex items-start justify-between gap-2"><span className="font-semibold text-ink">{al.title}</span><span className="flex shrink-0 items-center gap-1.5"><Badge tone={SEVERITY[al.severity].tone}>{SEVERITY[al.severity].label}</Badge><Badge tone="gray">{al.count}</Badge></span></p>
                  <p className="mt-1 text-xs text-inkSoft"><span className="font-semibold">Règle appliquée : </span>{al.explanation}</p>
                  {al.examples.length ? <ul className="mt-2 space-y-1 text-xs">{al.examples.map((ex, i) => <li key={i} className="text-inkSoft">{ex.link ? <Link href={ex.link} className="font-semibold text-primaryDark underline underline-offset-2">{ex.label}</Link> : ex.label}</li>)}</ul> : null}
                  {al.actions.length ? (
                    <div className="mt-2 border-t border-lineSoft pt-2">
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-ash">Actions proposées (non exécutées)</p>
                      <ul className="mt-1 space-y-1 text-xs">{al.actions.map((ac, i) => <li key={i}><Link href={ac.href} className="font-semibold text-primaryDark underline underline-offset-2">{ac.label}</Link></li>)}</ul>
                    </div>
                  ) : null}
                  <button type="button" disabled={!status.configured} title={status.configured ? undefined : NOT_CONFIGURED} onClick={() => onAsk(`Explique cette alerte et dis quelles vérifications faire avant toute décision : « ${al.title} ».`)} className={cx("mt-2 inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1 text-xs font-semibold text-inkSoft hover:border-primary/50 disabled:opacity-50", RING)}><Sparkles aria-hidden className="h-3.5 w-3.5" />Demander à Tratra AI</button>
                </li>
              ))}
            </ul>
          )}
          <dl className="grid grid-cols-3 gap-1.5">
            {Object.entries(data.stats).map(([k, v]) => {
              const value = statValue(k, v);
              return STAT_LABEL[k] && value !== null ? <div key={k} className="rounded-lg border border-line bg-white px-2 py-1.5"><dt className="text-[10px] leading-tight text-ash">{STAT_LABEL[k]}</dt><dd className="font-display text-base font-bold text-ink">{value}</dd></div> : null;
            })}
          </dl>
        </>
      ) : loading ? <p className="py-6 text-center text-sm text-ash">Calcul en cours…</p> : null}
    </div>
  );
}

type View = "chat" | "history" | "insights";

/** Bouton flottant « Tratra AI » + panneau de conversation persistant (monté dans la coque du Back-Office : il survit à la navigation). */
export function TratraAI() {
  const [open, setOpen] = useState(false);
  const [used, setUsed] = useState(false);
  const [view, setView] = useState<View>("chat");
  const launcher = useRef<HTMLButtonElement>(null);
  const a = useAssistant(used);
  const panelId = useId();

  useEffect(() => {
    const saved = loadSaved();
    if (saved.open) { setOpen(true); setUsed(true); }
  }, []);
  const toggle = useCallback((next: boolean) => {
    setOpen(next);
    if (next) setUsed(true);
    persist({ open: next, conversation: loadSaved().conversation });
    if (!next) launcher.current?.focus();
  }, []);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape") toggle(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, toggle]);

  const tabs: { id: View; label: string; icon: ReactNode }[] = [
    { id: "chat", label: "Discussion", icon: <Sparkles aria-hidden className="h-4 w-4" /> },
    { id: "history", label: "Historique", icon: <HistoryIcon aria-hidden className="h-4 w-4" /> },
    { id: "insights", label: "Synthèses", icon: <ShieldCheck aria-hidden className="h-4 w-4" /> },
  ];
  const ask = (text: string) => { setView("chat"); void a.send(text); };

  return (
    <>
      <button
        ref={launcher}
        type="button"
        onClick={() => toggle(!open)}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={open ? "Fermer Tratra AI" : "Ouvrir Tratra AI"}
        className={cx("fixed bottom-5 right-5 z-header flex h-14 items-center gap-2 rounded-full bg-primaryDark px-5 text-sm font-semibold text-white shadow-strong transition hover:bg-primaryDeep sm:bottom-6 sm:right-6", RING, open && "max-sm:hidden")}
      >
        <Sparkles aria-hidden className="h-5 w-5 text-accent" />
        <span className="hidden sm:inline">Tratra AI</span>
      </button>
      {open ? (
        <section
          id={panelId}
          role="dialog"
          aria-modal="false"
          aria-label="Tratra AI"
          className="fixed inset-0 z-overlay flex flex-col overflow-hidden bg-white shadow-strong sm:inset-auto sm:bottom-24 sm:right-6 sm:h-[min(40rem,calc(100vh-7rem))] sm:w-[27rem] sm:rounded-panel sm:border sm:border-line"
        >
          <header className="flex items-center gap-2 border-b border-line bg-night px-4 py-3 text-white">
            <Sparkles aria-hidden className="h-5 w-5 text-accent" />
            <div className="min-w-0 flex-1">
              <h2 className="font-display text-base font-bold leading-tight">Tratra AI</h2>
              <p className="truncate text-[11px] text-white/70">{a.status ? (a.status.configured ? "Assistant du Back-Office · lecture seule" : NOT_CONFIGURED) : "Chargement…"}</p>
            </div>
            <button type="button" onClick={() => { a.newConversation(); setView("chat"); }} aria-label="Nouvelle conversation" className={cx("grid h-10 w-10 place-items-center rounded-full text-white/80 hover:bg-white/10 hover:text-white", RING)}><Plus aria-hidden className="h-5 w-5" /></button>
            <button type="button" onClick={() => toggle(false)} aria-label="Fermer le panneau" className={cx("grid h-10 w-10 place-items-center rounded-full text-white/80 hover:bg-white/10 hover:text-white", RING)}><X aria-hidden className="h-5 w-5" /></button>
          </header>
          <div role="tablist" aria-label="Sections de Tratra AI" className="grid grid-cols-3 gap-1 border-b border-line bg-white p-1.5">
            {tabs.map((t) => (
              <button key={t.id} type="button" role="tab" aria-selected={view === t.id} onClick={() => setView(t.id)} className={cx("flex min-h-10 items-center justify-center gap-1.5 rounded-lg text-xs font-semibold", RING, view === t.id ? "bg-primarySoft text-primaryDark" : "text-ash hover:bg-lineSoft")}>{t.icon}{t.label}</button>
            ))}
          </div>
          {view === "chat" ? <Chat a={a} status={a.status} onGoInsights={() => setView("insights")} /> : view === "history" ? <History a={a} onOpen={() => setView("chat")} /> : <Insights status={a.status} onAsk={ask} />}
        </section>
      ) : null}
    </>
  );
}
