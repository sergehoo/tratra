"use client";
import { useEffect, useRef, useState } from "react";
import { Camera, Globe2, Type, Users, Video, WifiOff } from "lucide-react";
import { ApiError, apiErrorMessage, get, uploadWithProgress } from "@/lib/api";
import { Alert, Button, Modal, cx } from "@/components/ds";
import { BACKGROUNDS, compressImage, newClientId, videoDuration, type StatusItem, type StatusLimits } from "@/lib/statuses";

type Mode = "text" | "photo" | "video";
const MODES: { id: Mode; label: string; icon: typeof Type }[] = [
  { id: "text", label: "Texte", icon: Type },
  { id: "photo", label: "Photo", icon: Camera },
  { id: "video", label: "Vidéo", icon: Video },
];

/** Publication rapide : texte, photo, vidéo (ou média + légende), aperçu avant publication, progression et reprise après coupure réseau. */
export function StatusComposer({ open, limits, onClose, onPublished }: { open: boolean; limits: StatusLimits; onClose: () => void; onPublished: (s: StatusItem) => void }) {
  const [mode, setMode] = useState<Mode>("text");
  const [text, setText] = useState("");
  const [background, setBackground] = useState("green");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [audience, setAudience] = useState<"contacts" | "extended">("contacts");
  const [replies, setReplies] = useState(true);
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [offline, setOffline] = useState(false);
  const clientId = useRef(newClientId());
  const abort = useRef<AbortController | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setOffline(typeof navigator !== "undefined" && !navigator.onLine);
    const on = () => setOffline(false);
    const off = () => setOffline(true);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    get<{ audience: "contacts" | "extended"; allow_replies: boolean }>("/statuses/settings/")
      .then((s) => {
        setAudience(s.audience);
        setReplies(s.allow_replies);
      })
      .catch(() => undefined);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, [open]);

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  function reset() {
    setText("");
    setFile(null);
    setPreview(null);
    setProgress(0);
    setError("");
    setMode("text");
    clientId.current = newClientId();
  }

  async function pick(f: File | undefined) {
    setError("");
    if (!f) return;
    try {
      if (mode === "photo") {
        if (!/^image\/(jpeg|png|webp)$/.test(f.type)) return setError("Choisissez une photo JPEG, PNG ou WebP.");
        const small = await compressImage(f);
        if (small.size > limits.image_max_bytes) return setError(`Photo trop lourde : ${Math.round(limits.image_max_bytes / 1048576)} Mo au maximum.`);
        setFile(small);
        setPreview(URL.createObjectURL(small));
      } else {
        if (!/^video\/(mp4|quicktime)$/.test(f.type)) return setError("Choisissez une vidéo MP4 ou MOV.");
        if (f.size > limits.video_max_bytes) return setError(`Vidéo trop lourde : ${Math.round(limits.video_max_bytes / 1048576)} Mo au maximum.`);
        const d = await videoDuration(f).catch(() => 0);
        if (d > limits.video_max_seconds + 0.5) return setError(`Vidéo trop longue (${Math.round(d)} s) : ${limits.video_max_seconds} secondes au maximum.`);
        setFile(f);
        setPreview(URL.createObjectURL(f));
      }
      clientId.current = newClientId();       // nouveau contenu = nouvelle publication
    } catch {
      setError("Ce fichier n’a pas pu être lu.");
    }
  }

  const empty = mode === "text" ? !text.trim() : !file;
  async function publish() {
    if (empty || busy) return;
    setBusy(true);
    setError("");
    setProgress(0);
    const form = new FormData();
    form.set("text", text.trim());
    form.set("audience", audience);
    form.set("allow_replies", String(replies));
    form.set("client_id", clientId.current);       // idempotence : un renvoi après coupure ne publie jamais deux fois
    if (mode === "text") form.set("background", background);
    if (file && mode !== "text") form.set("file", file);
    abort.current = new AbortController();
    try {
      const r = await uploadWithProgress<{ status: StatusItem }>("/statuses/", form, setProgress, abort.current.signal);
      onPublished(r.status);
      reset();
      onClose();
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") setError("Envoi annulé.");
      else if (e instanceof ApiError) setError(apiErrorMessage(e, "Le statut n’a pas pu être publié."));
      else setError("Connexion interrompue. Appuyez sur « Réessayer » : votre statut ne sera publié qu’une seule fois.");
    } finally {
      setBusy(false);
    }
  }

  const bg = BACKGROUNDS[background];
  return (
    <Modal open={open} onClose={() => (busy ? abort.current?.abort() : onClose())} dismissible={!busy} title="Nouveau statut" description={`Visible ${limits.ttl_hours} h, puis supprimé automatiquement.`} size="md"
      footer={
        <div className="flex w-full flex-col gap-2">
          {busy ? <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)} className="h-2 overflow-hidden rounded-full bg-lineSoft"><div className="h-full bg-primary transition-[width]" style={{ width: `${Math.round(progress * 100)}%` }} /></div> : null}
          <div className="flex gap-2">
            <Button variant="ghost" block onClick={() => (busy ? abort.current?.abort() : onClose())}>{busy ? "Annuler l’envoi" : "Fermer"}</Button>
            <Button block loading={busy} disabled={empty || offline} onClick={() => void publish()}>{error && !busy ? "Réessayer" : "Publier"}</Button>
          </div>
        </div>
      }>
      <div className="space-y-4">
        {offline ? <Alert tone="warning" title="Hors connexion"><span className="inline-flex items-center gap-2"><WifiOff aria-hidden className="h-4 w-4" />La publication reprendra dès que le réseau sera rétabli.</span></Alert> : null}
        <div role="tablist" aria-label="Type de statut" className="grid grid-cols-3 gap-1 rounded-2xl bg-lineSoft p-1">
          {MODES.map(({ id, label, icon: Icon }) => (
            <button key={id} type="button" role="tab" aria-selected={mode === id} disabled={busy}
              onClick={() => { setMode(id); setFile(null); setPreview(null); setError(""); }}
              className={cx("flex min-h-11 items-center justify-center gap-2 rounded-xl text-sm font-semibold transition", mode === id ? "bg-white text-primaryDark shadow-hair" : "text-ash hover:text-ink")}>
              <Icon aria-hidden className="h-4 w-4" />{label}
            </button>
          ))}
        </div>

        {/* Aperçu avant publication */}
        <div className="overflow-hidden rounded-2xl border border-line" style={mode === "text" ? { background: bg.bg, color: bg.fg } : undefined}>
          {mode === "text" ? (
            <div className="grid min-h-[12rem] place-items-center p-6 text-center">
              <p className={cx("whitespace-pre-wrap break-words font-display text-xl font-bold", !text && "opacity-60")}>{text || "Votre texte apparaîtra ici"}</p>
            </div>
          ) : preview ? (
            mode === "photo"
              // eslint-disable-next-line @next/next/no-img-element
              ? <img src={preview} alt="Aperçu de la photo" className="max-h-72 w-full bg-night object-contain" />
              : <video src={preview} controls playsInline className="max-h-72 w-full bg-night" />
          ) : (
            <button type="button" onClick={() => input.current?.click()} className="grid min-h-[12rem] w-full place-items-center bg-surface p-6 text-center text-sm text-ash hover:bg-lineSoft">
              <span>{mode === "photo" ? <Camera aria-hidden className="mx-auto mb-2 h-8 w-8 text-primary" /> : <Video aria-hidden className="mx-auto mb-2 h-8 w-8 text-primary" />}
                {mode === "photo" ? "Choisir une photo" : `Choisir une vidéo (${limits.video_max_seconds} s max.)`}</span>
            </button>
          )}
        </div>
        <input ref={input} type="file" className="sr-only" tabIndex={-1} aria-label={mode === "photo" ? "Choisir une photo" : "Choisir une vidéo"}
          accept={mode === "photo" ? "image/jpeg,image/png,image/webp" : "video/mp4,video/quicktime"} onChange={(e) => { void pick(e.target.files?.[0]); e.target.value = ""; }} />
        {mode !== "text" && file ? <Button variant="outline" size="sm" onClick={() => input.current?.click()} disabled={busy}>Changer le fichier</Button> : null}

        <div>
          <label htmlFor="status-text" className="mb-1 block text-sm font-semibold text-ink">{mode === "text" ? "Votre texte" : "Légende (facultative)"}</label>
          <textarea id="status-text" value={text} onChange={(e) => setText(e.target.value.slice(0, limits.text_max))} rows={mode === "text" ? 4 : 2} maxLength={limits.text_max} disabled={busy}
            className="w-full rounded-xl border border-line bg-white px-3 py-2.5 text-sm text-ink focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30" />
          <p className={cx("mt-1 text-right text-xs", text.length >= limits.text_max ? "text-dangerInk" : "text-ash")}>{text.length} / {limits.text_max}</p>
        </div>

        {mode === "text" ? (
          <div role="radiogroup" aria-label="Couleur de fond" className="flex gap-2">
            {Object.entries(BACKGROUNDS).map(([key, v]) => (
              <button key={key} type="button" role="radio" aria-checked={background === key} aria-label={v.label} onClick={() => setBackground(key)} disabled={busy}
                className={cx("h-9 w-9 rounded-full ring-offset-2 transition", background === key ? "ring-2 ring-primary" : "ring-1 ring-line")} style={{ background: v.bg }} />
            ))}
          </div>
        ) : null}

        <fieldset className="space-y-2">
          <legend className="text-sm font-semibold text-ink">Qui peut voir ce statut ?</legend>
          {([["contacts", "Mes contacts Tratra", "Clients et artisans avec qui vous avez une réservation, un contrat ou une conversation.", Users], ["extended", "Tous les membres", "Aussi visible dans « Découvrir les statuts ».", Globe2]] as const).map(([value, label, hint, Icon]) => (
            <label key={value} className={cx("flex cursor-pointer items-start gap-3 rounded-xl border p-3", audience === value ? "border-primary bg-primarySoft/40" : "border-line")}>
              <input type="radio" name="audience" checked={audience === value} onChange={() => setAudience(value)} disabled={busy} className="mt-1" />
              <span className="min-w-0"><span className="flex items-center gap-2 text-sm font-semibold text-ink"><Icon aria-hidden className="h-4 w-4 text-primary" />{label}</span><span className="block text-xs text-ash">{hint}</span></span>
            </label>
          ))}
        </fieldset>
        <label className="flex items-center gap-3 text-sm text-ink"><input type="checkbox" checked={replies} onChange={(e) => setReplies(e.target.checked)} disabled={busy} />Autoriser les réponses par message</label>

        {error ? <Alert tone="danger">{error}</Alert> : null}
      </div>
    </Modal>
  );
}
