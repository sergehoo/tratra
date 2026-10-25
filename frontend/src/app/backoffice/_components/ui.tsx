"use client";
import { useEffect, useId, useState, type ReactNode } from "react";
import { Search } from "lucide-react";
import { Alert, Badge, Button, Card, Input, Modal, Select, Textarea, TextField, type BadgeTone } from "@/components/ds";
import { bo, boError, fieldErrors, MIN_REASON } from "@/lib/bo";
import { formatDateTimeShort } from "../../dashboard/_components/dates";

export const dt = (value: string | null | undefined): string => (value ? formatDateTimeShort(value) ?? "—" : "—");

/** Date courte pour les tableaux (« 11 oct. 2026 ») ; l'heure reste dans l'infobulle. */
export function dd(value: string | null | undefined): ReactNode {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return <time dateTime={value} title={dt(value)}>{d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" })}</time>;
}

// ── Filtres ────────────────────────────────────────────────────────────────────────────────────────────────────────

export function SearchBox({ value, onChange, placeholder = "Rechercher…", label = "Recherche" }: { value: string; onChange: (v: string) => void; placeholder?: string; label?: string }) {
  const id = useId();
  return (
    <div className="min-w-[14rem] flex-1">
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <Input id={id} type="search" value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} leading={<Search className="h-4 w-4" />} />
    </div>
  );
}

export function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: [string, string][] }) {
  const id = useId();
  return (
    <div className="min-w-[10rem]">
      <label htmlFor={id} className="mb-1 block text-xs font-semibold text-ash">
        {label}
      </label>
      <Select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </Select>
    </div>
  );
}

export function DateRange({ from, to, onFrom, onTo }: { from: string; to: string; onFrom: (v: string) => void; onTo: (v: string) => void }) {
  const a = useId();
  const b = useId();
  return (
    <>
      <div>
        <label htmlFor={a} className="mb-1 block text-xs font-semibold text-ash">
          Du
        </label>
        <Input id={a} type="date" value={from} onChange={(e) => onFrom(e.target.value)} />
      </div>
      <div>
        <label htmlFor={b} className="mb-1 block text-xs font-semibold text-ash">
          Au
        </label>
        <Input id={b} type="date" value={to} onChange={(e) => onTo(e.target.value)} />
      </div>
    </>
  );
}

// ── Liste paginée avec états (tri, actions par ligne et groupées, pagination) : voir list.tsx ───────────────────────────

export { ExportButton, FilterBar, Kpi, KpiGrid, ListView, RowMenu, StatusChips } from "./list";
export { Drawer } from "./Drawer";
export type { BoColumn, BulkAction, RowAction } from "./list";

// ── Présentation ───────────────────────────────────────────────────────────────────────────────────────────────────

export function Section({ title, actions, children, className = "" }: { title: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <Card padding="md" radius="card" className={className}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-lg font-bold text-ink">{title}</h2>
        {actions}
      </div>
      {children}
    </Card>
  );
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
      {items.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-xs font-semibold uppercase tracking-wide text-ash">{k}</dt>
          <dd className="mt-0.5 break-words text-sm text-ink">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

const TONES: Record<string, BadgeTone> = {
  // états génériques
  pending: "warning", ready: "info", approved: "success", rejected: "danger", incomplete: "gray", confirmed: "info", in_progress: "primary",
  completed: "success", cancelled: "gray", open: "warning", under_review: "info", resolved: "success", held: "info", released: "success",
  refunded: "gray", failed: "danger", sent: "success", queued: "warning", true: "success", false: "gray",
};

export function Tag({ value, label, tone }: { value: string; label?: string; tone?: BadgeTone }) {
  return <Badge tone={tone ?? TONES[value] ?? "gray"}>{label ?? value}</Badge>;
}

export const STATUS_FR: Record<string, string> = {
  pending: "En attente", confirmed: "Confirmée", in_progress: "En cours", completed: "Terminée", cancelled: "Annulée", open: "Ouvert",
  under_review: "En examen", resolved: "Résolu", rejected: "Rejeté", held: "Séquestre", released: "Versé", refunded: "Remboursé", failed: "Échoué",
  sent: "Envoyé", queued: "En file", approved: "Approuvé", ready: "Prêt", incomplete: "Incomplet",
};

// ── Graphiques légers (SVG, accessibles) ───────────────────────────────────────────────────────────────────────────

export function Bars({ data, label, color = "var(--color-primary, #2E8B57)" }: { data: { date: string; count: number }[]; label: string; color?: string }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  const total = data.reduce((s, d) => s + d.count, 0);
  const w = 100 / Math.max(1, data.length);
  return (
    <figure className="m-0">
      <svg role="img" aria-label={`${label} : ${total} au total sur ${data.length} jours`} viewBox="0 0 100 32" preserveAspectRatio="none" className="h-24 w-full">
        {data.map((d, i) => {
          const h = (d.count / max) * 30;
          return <rect key={d.date} x={i * w + w * 0.15} y={31 - h} width={w * 0.7} height={Math.max(h, d.count ? 0.8 : 0.3)} rx="0.4" fill={color} opacity={d.count ? 1 : 0.25}>
            <title>{`${d.date} : ${d.count}`}</title>
          </rect>;
        })}
      </svg>
      <figcaption className="mt-1 flex justify-between text-[11px] text-ash">
        <span>{data[0]?.date}</span>
        <span className="font-semibold text-inkSoft">{label} — {total}</span>
        <span>{data[data.length - 1]?.date}</span>
      </figcaption>
    </figure>
  );
}

// ── Actions avec motif ─────────────────────────────────────────────────────────────────────────────────────────────

export interface ExtraField {
  key: string;
  label: string;
  hint?: string;
  required?: boolean;
  minLength?: number;
  type?: "text" | "number" | "select";
  options?: [string, string][];
}

/**
 * Action sensible : saisie d'un MOTIF (≥ 5 caractères, revalidé par le serveur) + champs complémentaires éventuels, état
 * d'attente, erreur réelle du serveur dans la boîte (jamais un succès affiché avant sa confirmation).
 */
export function ReasonModal({
  open,
  title,
  description,
  confirmLabel,
  tone = "primary",
  reasonLabel = "Motif",
  reasonKey = "reason",
  fields = [],
  minReason = MIN_REASON,
  onClose,
  onDone,
  request,
  children,
}: {
  open: boolean;
  title: string;
  description?: ReactNode;
  confirmLabel: string;
  tone?: "primary" | "danger";
  reasonLabel?: string;
  reasonKey?: string;
  fields?: ExtraField[];
  /** Longueur minimale du motif exigée par le serveur pour cette action. */
  minReason?: number;
  onClose: () => void;
  onDone: () => void;
  /** Envoie la requête avec le corps construit ; lève en cas d'échec (le message est affiché). */
  request: (body: Record<string, string>) => Promise<unknown>;
  children?: ReactNode;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (open) {
      setValues({});
      setError("");
      setErrors({});
    }
  }, [open]);

  const reason = (values[reasonKey] ?? "").trim();
  const missing = reason.length < minReason || fields.some((f) => f.required && (values[f.key] ?? "").trim().length < (f.minLength ?? 1));

  async function submit() {
    setBusy(true);
    setError("");
    setErrors({});
    try {
      await request({ ...values, [reasonKey]: reason });
      onDone();
    } catch (e) {
      setErrors(fieldErrors(e));
      setError(boError(e, "L’opération a échoué. Rien n’a été modifié."));
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
      dismissible={!busy}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Annuler
          </Button>
          <Button variant={tone} loading={busy} disabled={missing} onClick={() => void submit()}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {children}
        {fields.map((f) =>
          f.type === "select" ? (
            <label key={f.key} className="block text-sm font-semibold text-ink">
              {f.label}
              <Select className="mt-1.5" value={values[f.key] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}>
                {f.options?.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </Select>
            </label>
          ) : (
            <TextField key={f.key} label={f.label} hint={f.hint} type={f.type === "number" ? "text" : "text"} inputMode={f.type === "number" ? "decimal" : undefined}
              value={values[f.key] ?? ""} error={errors[f.key]} onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))} />
          ),
        )}
        <label className="block text-sm font-semibold text-ink">
          {reasonLabel} <span aria-hidden className="text-danger">*</span>
          <Textarea
            className="mt-1.5"
            rows={3}
            value={values[reasonKey] ?? ""}
            onChange={(e) => setValues((v) => ({ ...v, [reasonKey]: e.target.value }))}
            placeholder={`Au moins ${minReason} caractères — conservé dans le journal d’audit`}
            invalid={Boolean(errors[reasonKey])}
          />
          {errors[reasonKey] ? <span role="alert" className="mt-1 block text-xs font-medium text-dangerInk">{errors[reasonKey]}</span> : null}
        </label>
        {error ? <Alert tone="danger">{error}</Alert> : null}
      </div>
    </Modal>
  );
}

/** Appel POST protégé : renvoie une fonction `request(body)` pour <ReasonModal>. */
export const postTo = (path: string) => (body: Record<string, string>) => bo.post(path, body);

export { useTabParam } from "@/lib/useUrlFilters";

/** Message de confirmation éphémère en haut de page (jamais affiché avant la confirmation du serveur). */
export function useNotice(): [string, (m: string) => void] {
  const [msg, setMsg] = useState("");
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(""), 6000);
    return () => clearTimeout(t);
  }, [msg]);
  return [msg, setMsg];
}
