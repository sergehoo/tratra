"use client";
import { useCallback, useEffect, useId, useRef, useState, type DependencyList, type ReactNode } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Alert, Button, Modal, Select, SkeletonList } from "@/components/ds";
import { Input } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api";
import { fingerprint, randomHex } from "@/lib/continuity";
import { WEEKDAYS, type ScheduleSlot } from "@/lib/engagements";

/** Chargement d'une ressource : état réel (chargement / erreur avec « Réessayer » / données), jamais de donnée inventée. */
export function useLoad<T>(fetcher: () => Promise<T>, deps: DependencyList) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const reload = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    setError("");
    try {
      const d = await fetcher();
      if (mine === seq.current) setData(d);
    } catch (e) {
      if (mine === seq.current) setError(apiErrorMessage(e, "Chargement impossible pour le moment."));
    } finally {
      if (mine === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { data, error, loading, reload, setData };
}

/** États d'une page de détail : squelette, erreur réelle, ou le contenu. */
export function LoadState({ loading, error, hasData, reload, children }: { loading: boolean; error: string; hasData: boolean; reload: () => void; children: ReactNode }) {
  if (!hasData && loading) return <SkeletonList count={3} />;
  if (!hasData && error) {
    return (
      <Alert tone="danger" title="Chargement impossible" action={<Button size="sm" variant="outline" onClick={reload}>Réessayer</Button>}>
        {error}
      </Alert>
    );
  }
  return <>{children}</>;
}

/**
 * Clé d'idempotence liée au CONTENU de la demande : un renvoi identique (double clic, retour du réseau) rejoue la même action côté
 * serveur sans doublon ; modifier un champ crée une nouvelle intention. `reset()` après un succès.
 */
export function useIntent(scope: string) {
  const base = useRef(randomHex(6));
  return {
    key: (payload: unknown) => `${scope}-${base.current}-${fingerprint(JSON.stringify(payload))}`.slice(0, 80),
    reset: () => {
      base.current = randomHex(6);
    },
  };
}

/** Modale d'action : attente, erreur réelle du serveur dans la boîte, fermeture seulement après confirmation du serveur. */
export function ActionModal({
  open, title, description, confirmLabel, tone = "primary", size = "md", disabled, onClose, onSubmit, onError, children,
}: {
  open: boolean; title: string; description?: ReactNode; confirmLabel: string; tone?: "primary" | "danger"; size?: "sm" | "md" | "lg"; disabled?: boolean;
  onClose: () => void; onSubmit: () => Promise<void>; onError?: (e: unknown) => void; children?: ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (open) setError("");
  }, [open]);
  async function submit() {
    setBusy(true);
    setError("");
    try {
      await onSubmit();
    } catch (e) {
      onError?.(e);
      setError(apiErrorMessage(e, "L’opération a échoué. Rien n’a été modifié."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      size={size}
      dismissible={!busy}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={busy}>Annuler</Button>
          <Button variant={tone} loading={busy} disabled={disabled} onClick={() => void submit()}>{confirmLabel}</Button>
        </>
      }
    >
      <div className="space-y-4">
        {children}
        {error ? <Alert tone="danger">{error}</Alert> : null}
      </div>
    </Modal>
  );
}

export function Facts({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
      {items.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-xs font-semibold uppercase tracking-wide text-ash">{k}</dt>
          <dd className="mt-0.5 break-words text-sm text-ink">{v === null || v === undefined || v === "" ? "—" : v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Éditeur du planning hebdomadaire : une ligne par créneau (jour, début, fin). Aucune valeur imposée au-delà du point de départ d'un nouveau créneau. */
export function ScheduleEditor({ value, onChange, error, disabled }: { value: ScheduleSlot[]; onChange: (v: ScheduleSlot[]) => void; error?: string; disabled?: boolean }) {
  const id = useId();
  const set = (i: number, patch: Partial<ScheduleSlot>) => onChange(value.map((s, k) => (k === i ? { ...s, ...patch } : s)));
  return (
    <fieldset className="space-y-2" aria-describedby={error ? `${id}-err` : undefined}>
      <legend className="text-sm font-semibold text-ink">Planning hebdomadaire</legend>
      {value.length === 0 ? <p className="text-xs text-ash">Aucun créneau fixe : les interventions seront convenues au fil de l’eau.</p> : null}
      {value.map((s, i) => (
        <div key={i} className="grid grid-cols-[1fr_auto] items-end gap-2 sm:grid-cols-[10rem_8rem_8rem_auto]">
          <label className="col-span-2 block text-xs font-semibold text-ash sm:col-span-1">
            Jour
            <Select className="mt-1" disabled={disabled} value={String(s.weekday)} onChange={(e) => set(i, { weekday: Number(e.target.value) })}>
              {WEEKDAYS.map((d, k) => <option key={d} value={k}>{d}</option>)}
            </Select>
          </label>
          <label className="block text-xs font-semibold text-ash">
            Début
            <Input className="mt-1" type="time" disabled={disabled} value={s.start} onChange={(e) => set(i, { start: e.target.value })} />
          </label>
          <label className="block text-xs font-semibold text-ash">
            Fin
            <Input className="mt-1" type="time" disabled={disabled} value={s.end} onChange={(e) => set(i, { end: e.target.value })} />
          </label>
          <Button type="button" size="sm" variant="ghost" disabled={disabled} aria-label={`Retirer le créneau ${i + 1}`} onClick={() => onChange(value.filter((_, k) => k !== i))}>
            <Trash2 aria-hidden className="h-4 w-4" />
          </Button>
        </div>
      ))}
      {error ? <p id={`${id}-err`} role="alert" className="text-xs font-medium text-dangerInk">{error}</p> : null}
      <Button type="button" size="sm" variant="soft" disabled={disabled} leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => onChange([...value, { weekday: value.length ? (value[value.length - 1].weekday + 1) % 7 : 0, start: value[value.length - 1]?.start ?? "08:00", end: value[value.length - 1]?.end ?? "12:00" }])}>
        Ajouter un créneau
      </Button>
    </fieldset>
  );
}

/** Onglet courant, lu depuis `?tab=` après le montage (aucun écart d'hydratation) et gardé dans l'URL. */
export function useTabParam<T extends string>(allowed: readonly T[], fallback: T): [T, (t: T) => void] {
  const [tab, setTabState] = useState<T>(fallback);
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("tab") as T | null;
    if (t && allowed.includes(t)) setTabState(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const setTab = useCallback((t: T) => {
    setTabState(t);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", t);
    window.history.replaceState(null, "", url);
  }, []);
  return [tab, setTab];
}

/** Message de confirmation éphémère (jamais affiché avant la confirmation du serveur). */
export function useNotice(): [string, (m: string) => void] {
  const [msg, setMsg] = useState("");
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(""), 6000);
    return () => clearTimeout(t);
  }, [msg]);
  return [msg, setMsg];
}
