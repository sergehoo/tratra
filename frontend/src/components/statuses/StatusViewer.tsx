"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, Eye, Flag, Pause, Play, Send, Trash2, Volume2, VolumeX, X } from "lucide-react";
import { apiErrorMessage, del, get, post } from "@/lib/api";
import { Avatar, cx } from "@/components/ds";
import { BACKGROUNDS, timeLeft, type StatusGroup, type StatusItem, type StatusViewer as Viewer } from "@/lib/statuses";

const IMAGE_MS = 6000;
const textMs = (t: string) => Math.min(12000, Math.max(5000, 3500 + t.length * 35));

interface Props {
  groups: StatusGroup[];
  startGroup?: number;
  /** Appelé à la fermeture avec les statuts réellement vus (pour rafraîchir le fil) et un indicateur de suppression. */
  onClose: (info: { viewed: number[]; changed: boolean }) => void;
  onViewed?: (statusId: number) => void;
}

/** Visionneuse plein écran : progression, pause/reprise, précédent/suivant, réponse, compteur de vues et lecteurs (auteur). */
export function StatusViewer({ groups, startGroup = 0, onClose, onViewed }: Props) {
  const [gi, setGi] = useState(startGroup);
  const [si, setSi] = useState(() => {
    const first = groups[startGroup]?.statuses.findIndex((s) => s.seen === false) ?? -1;
    return first > 0 ? first : 0;
  });
  const [removed, setRemoved] = useState<number[]>([]);
  const [progress, setProgress] = useState(0);
  const [holding, setHolding] = useState(false);
  const [userPaused, setUserPaused] = useState(false);
  const [sheet, setSheet] = useState<"viewers" | "report" | null>(null);
  const [ready, setReady] = useState(false);
  const [muted, setMuted] = useState(true);
  const [reply, setReply] = useState("");
  const [replyFocus, setReplyFocus] = useState(false);
  const [notice, setNotice] = useState("");
  const [viewers, setViewers] = useState<Viewer[] | null>(null);
  const [reason, setReason] = useState("");
  const [mounted, setMounted] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const viewed = useRef(new Set<number>());
  const changed = useRef(false);
  const holdTimer = useRef<ReturnType<typeof setTimeout>>();
  const holdActive = useRef(false);

  const group = groups[gi];
  const live = useMemo(() => group?.statuses.filter((s) => !removed.includes(s.id)) ?? [], [group, removed]);
  const status: StatusItem | undefined = live[si];
  const paused = holding || userPaused || sheet !== null || replyFocus;

  useEffect(() => setMounted(true), []);
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  const close = useCallback(() => onClose({ viewed: [...viewed.current], changed: changed.current }), [onClose]);

  const next = useCallback(() => {
    setProgress(0);
    setReady(false);
    if (si + 1 < live.length) return setSi(si + 1);
    if (gi + 1 < groups.length) {
      setGi(gi + 1);
      const first = groups[gi + 1].statuses.findIndex((s) => s.seen === false);
      return setSi(first > 0 ? first : 0);
    }
    close();
  }, [si, live.length, gi, groups, close]);

  const prev = useCallback(() => {
    setProgress(0);
    setReady(false);
    if (si > 0) return setSi(si - 1);
    if (gi > 0) {
      setGi(gi - 1);
      setSi(Math.max(0, groups[gi - 1].statuses.length - 1));
    }
  }, [si, gi, groups]);

  // Une vue n'est enregistrée que lorsque le statut est RÉELLEMENT affiché (texte : dès l'affichage ; photo : image chargée ; vidéo : lecture démarrée).
  useEffect(() => {
    if (!ready || !status || status.mine || viewed.current.has(status.id)) return;
    viewed.current.add(status.id);
    onViewed?.(status.id);
    post(`/statuses/${status.id}/view/`).catch(() => undefined);
  }, [ready, status, onViewed]);

  // Progression des statuts texte et photo (la vidéo suit sa propre lecture).
  useEffect(() => {
    if (!status || !ready || status.kind === "video") return;
    const total = status.kind === "text" ? textMs(status.text) : IMAGE_MS;
    let last = performance.now();
    const id = setInterval(() => {
      const now = performance.now();
      if (!paused) setProgress((p) => Math.min(1, p + (now - last) / total));
      last = now;
    }, 60);
    return () => clearInterval(id);
  }, [status, ready, paused]);

  useEffect(() => {
    if (progress >= 1) next();
  }, [progress, next]);

  useEffect(() => {
    if (status?.kind === "text") setReady(true);
  }, [status]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (paused) v.pause();
    else void v.play().catch(() => undefined);
  }, [paused, status]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (replyFocus || sheet) return;
      if (e.key === "Escape") close();
      else if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") prev();
      else if (e.key === " ") {
        e.preventDefault();
        setUserPaused((p) => !p);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [close, next, prev, replyFocus, sheet]);

  async function openViewers() {
    if (!status) return;
    setSheet("viewers");
    setViewers(null);
    try {
      setViewers((await get<{ results: Viewer[] }>(`/statuses/${status.id}/viewers/`)).results);
    } catch (e) {
      setNotice(apiErrorMessage(e, "La liste des lecteurs n’a pas pu être chargée."));
      setSheet(null);
    }
  }

  async function remove() {
    if (!status || !window.confirm("Supprimer ce statut ? Cette action est définitive.")) return;
    try {
      await del(`/statuses/${status.id}/`);
      changed.current = true;
      setRemoved((r) => [...r, status.id]);
      setProgress(0);
      setReady(false);
      if (live.length <= 1) close();
      else if (si >= live.length - 1) setSi(Math.max(0, si - 1));
    } catch (e) {
      setNotice(apiErrorMessage(e, "Le statut n’a pas pu être supprimé."));
    }
  }

  async function sendReply() {
    const text = reply.trim();
    if (!text || !status) return;
    try {
      await post(`/statuses/${status.id}/reply/`, { content: text });
      setReply("");
      setReplyFocus(false);
      setNotice("Réponse envoyée dans vos messages.");
    } catch (e) {
      setNotice(apiErrorMessage(e, "La réponse n’a pas pu être envoyée."));
    }
  }

  async function sendReport() {
    if (!status) return;
    try {
      await post(`/statuses/${status.id}/report/`, { reason });
      setSheet(null);
      setReason("");
      setNotice("Merci. Le signalement a été transmis à l’équipe Tratra.");
    } catch (e) {
      setNotice(apiErrorMessage(e, "Le signalement n’a pas pu être envoyé."));
    }
  }

  function onPointerDown() {
    holdActive.current = false;
    holdTimer.current = setTimeout(() => {
      holdActive.current = true;
      setHolding(true);
    }, 220);
  }
  function onPointerUp(zone: "prev" | "next") {
    clearTimeout(holdTimer.current);
    if (holdActive.current) {
      holdActive.current = false;
      setHolding(false);
      return;
    }
    if (zone === "prev") prev();
    else next();
  }

  if (!mounted || !group || !status) return null;
  const bg = BACKGROUNDS[status.background ?? "green"] ?? BACKGROUNDS.green;

  return createPortal(
    <div role="dialog" aria-modal="true" aria-label={`Statut de ${group.author.name}`} className="fixed inset-0 z-modal flex select-none items-center justify-center bg-black">
      <div className="relative flex h-full w-full max-w-[28rem] flex-col overflow-hidden bg-night text-white sm:h-[min(100dvh,52rem)] sm:rounded-3xl">
        {/* Barres de progression */}
        <div className="absolute inset-x-0 top-0 z-20 flex gap-1 px-3 pt-3" aria-hidden>
          {live.map((s, i) => (
            <span key={s.id} className="h-1 flex-1 overflow-hidden rounded-full bg-white/30">
              <span className="block h-full bg-white" style={{ width: `${i < si ? 100 : i === si ? progress * 100 : 0}%` }} />
            </span>
          ))}
        </div>
        {/* En-tête */}
        <div className="absolute inset-x-0 top-0 z-20 mt-6 flex items-center gap-3 bg-gradient-to-b from-black/60 to-transparent px-3 pb-6 pt-3">
          <Avatar name={group.author.name} photo={group.author.avatar} size={36} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-bold">{status.mine ? "Mon statut" : group.author.name}</p>
            <p className="text-[11px] text-white/80">Expire dans {timeLeft(status.expires_at)}</p>
          </div>
          {status.kind === "video" ? (
            <button type="button" aria-label={muted ? "Activer le son" : "Couper le son"} onClick={() => setMuted((m) => !m)} className="grid h-10 w-10 place-items-center rounded-full hover:bg-white/15">
              {muted ? <VolumeX className="h-5 w-5" /> : <Volume2 className="h-5 w-5" />}
            </button>
          ) : null}
          <button type="button" aria-label={userPaused ? "Reprendre" : "Pause"} onClick={() => setUserPaused((p) => !p)} className="grid h-10 w-10 place-items-center rounded-full hover:bg-white/15">
            {userPaused ? <Play className="h-5 w-5" /> : <Pause className="h-5 w-5" />}
          </button>
          <button type="button" aria-label="Fermer" onClick={close} className="grid h-10 w-10 place-items-center rounded-full hover:bg-white/15">
            <X className="h-6 w-6" />
          </button>
        </div>

        {/* Contenu */}
        <div className="relative flex-1" style={status.kind === "text" ? { background: bg.bg, color: bg.fg } : undefined}>
          {status.kind === "text" ? (
            <p className="absolute inset-0 grid place-items-center whitespace-pre-wrap break-words px-8 text-center font-display text-2xl font-bold leading-snug">{status.text}</p>
          ) : status.kind === "photo" && status.media?.url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={status.id} src={status.media.url} alt={status.text || "Photo du statut"} onLoad={() => setReady(true)} onError={() => setNotice("Ce média n’a pas pu être chargé.")} className="absolute inset-0 h-full w-full object-contain" />
          ) : status.media?.url ? (
            <video
              key={status.id}
              ref={videoRef}
              src={status.media.url}
              muted={muted}
              playsInline
              autoPlay
              onPlaying={() => setReady(true)}
              onTimeUpdate={(e) => {
                const v = e.currentTarget;
                if (v.duration) setProgress(v.currentTime / v.duration);
              }}
              onEnded={next}
              onError={() => setNotice("Cette vidéo n’a pas pu être chargée.")}
              className="absolute inset-0 h-full w-full object-contain"
            />
          ) : null}
          {status.kind !== "text" && status.text ? (
            <p className="absolute inset-x-0 bottom-0 z-10 bg-gradient-to-t from-black/75 to-transparent px-5 pb-5 pt-12 text-center text-[15px] leading-snug">{status.text}</p>
          ) : null}
          {/* Zones de navigation : appui court = précédent / suivant, appui maintenu = pause */}
          <button type="button" aria-label="Statut précédent" className="absolute inset-y-0 left-0 z-10 w-1/3 cursor-w-resize" onPointerDown={onPointerDown} onPointerUp={() => onPointerUp("prev")} onPointerLeave={() => { clearTimeout(holdTimer.current); if (holdActive.current) { holdActive.current = false; setHolding(false); } }} />
          <button type="button" aria-label="Statut suivant" className="absolute inset-y-0 right-0 z-10 w-2/3 cursor-e-resize" onPointerDown={onPointerDown} onPointerUp={() => onPointerUp("next")} onPointerLeave={() => { clearTimeout(holdTimer.current); if (holdActive.current) { holdActive.current = false; setHolding(false); } }} />
          <button type="button" aria-label="Précédent" onClick={prev} className="absolute left-2 top-1/2 z-20 hidden h-10 w-10 -translate-y-1/2 place-items-center rounded-full bg-black/40 hover:bg-black/60 sm:grid"><ChevronLeft className="h-5 w-5" /></button>
          <button type="button" aria-label="Suivant" onClick={next} className="absolute right-2 top-1/2 z-20 hidden h-10 w-10 -translate-y-1/2 place-items-center rounded-full bg-black/40 hover:bg-black/60 sm:grid"><ChevronRight className="h-5 w-5" /></button>
        </div>

        {/* Pied : auteur = vues et suppression ; lecteur = réponse et signalement */}
        <div className="z-20 border-t border-white/10 bg-night px-3 py-3">
          {notice ? <p role="status" className="mb-2 text-center text-xs text-accent">{notice}</p> : null}
          {status.mine ? (
            <div className="flex items-center justify-between gap-2">
              <button type="button" onClick={() => void openViewers()} className="flex min-h-11 items-center gap-2 rounded-full bg-white/10 px-4 text-sm font-semibold hover:bg-white/20">
                <Eye aria-hidden className="h-4 w-4" />
                {status.views?.unique ?? 0} {(status.views?.unique ?? 0) > 1 ? "vues" : "vue"}
                {status.views && status.views.total > status.views.unique ? <span className="text-white/70">· {status.views.total} consultations</span> : null}
              </button>
              <button type="button" aria-label="Supprimer ce statut" onClick={() => void remove()} className="grid h-11 w-11 place-items-center rounded-full bg-white/10 hover:bg-dangerSoft hover:text-dangerInk"><Trash2 className="h-5 w-5" /></button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              {status.allow_replies ? (
                <form className="flex flex-1 items-center gap-2" onSubmit={(e) => { e.preventDefault(); void sendReply(); }}>
                  <label htmlFor="status-reply" className="sr-only">Répondre par message</label>
                  <input id="status-reply" value={reply} onChange={(e) => setReply(e.target.value)} onFocus={() => setReplyFocus(true)} onBlur={() => setReplyFocus(false)} maxLength={1000} placeholder="Répondre par message…" className="min-h-11 flex-1 rounded-full border border-white/25 bg-white/10 px-4 text-sm text-white placeholder:text-white/60 focus:border-accent focus:outline-none" />
                  <button type="submit" aria-label="Envoyer la réponse" disabled={!reply.trim()} className="grid h-11 w-11 place-items-center rounded-full bg-accent text-ink disabled:opacity-40"><Send className="h-5 w-5" /></button>
                </form>
              ) : <p className="flex-1 text-center text-xs text-white/60">Les réponses sont désactivées pour ce statut.</p>}
              <button type="button" aria-label="Signaler ce statut" onClick={() => setSheet("report")} className="grid h-11 w-11 place-items-center rounded-full bg-white/10 hover:bg-white/20"><Flag className="h-5 w-5" /></button>
            </div>
          )}
        </div>

        {/* Feuilles : lecteurs (auteur) et signalement */}
        {sheet ? (
          <div className="absolute inset-x-0 bottom-0 z-30 max-h-[70%] overflow-y-auto rounded-t-3xl bg-white p-4 text-ink shadow-strong">
            <div className="mb-3 flex items-center justify-between">
              <p className="font-display text-base font-bold">{sheet === "viewers" ? "Lecteurs de ce statut" : "Signaler ce statut"}</p>
              <button type="button" aria-label="Fermer" onClick={() => setSheet(null)} className="grid h-9 w-9 place-items-center rounded-full hover:bg-lineSoft"><X className="h-5 w-5" /></button>
            </div>
            {sheet === "viewers" ? (
              viewers === null ? <p className="py-6 text-center text-sm text-ash">Chargement…</p>
              : viewers.length === 0 ? <p className="py-6 text-center text-sm text-ash">Personne n’a encore vu ce statut.</p>
              : (
                <ul className="divide-y divide-lineSoft">
                  {viewers.map((v) => (
                    <li key={`${v.user.id}`} className="flex items-center gap-3 py-2.5">
                      <Avatar name={v.user.name} photo={v.user.avatar} size={36} />
                      <span className="min-w-0 flex-1 truncate text-sm font-semibold">{v.user.name}</span>
                      <span className="shrink-0 text-xs text-ash">{new Date(v.viewed_at).toLocaleString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}{v.count && v.count > 1 ? ` · ×${v.count}` : ""}</span>
                    </li>
                  ))}
                </ul>
              )
            ) : (
              <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void sendReport(); }}>
                <label htmlFor="status-report" className="text-sm text-inkSoft">Indiquez le motif du signalement</label>
                <textarea id="status-report" value={reason} onChange={(e) => setReason(e.target.value)} rows={3} maxLength={500} className="w-full rounded-xl border border-line px-3 py-2 text-sm focus:border-primary focus:outline-none" />
                <button type="submit" disabled={reason.trim().length < 3} className={cx("min-h-11 w-full rounded-full bg-primary text-sm font-bold text-white", reason.trim().length < 3 && "opacity-40")}>Envoyer le signalement</button>
              </form>
            )}
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
