import type { ReactNode } from "react";
import { Badge, Card } from "@/components/ds";
import { PRIORITIES, REQUEST_STATUS } from "@/lib/business";

export function StatusPill({ status }: { status: string }) {
  const v = REQUEST_STATUS[status] ?? { label: status, tone: "gray" as const };
  return <Badge tone={v.tone}>{v.label}</Badge>;
}

export function PriorityPill({ priority }: { priority: string }) {
  const v = PRIORITIES[priority] ?? { label: priority, tone: "gray" as const };
  return <Badge tone={v.tone}>{v.label}</Badge>;
}

/** Indicateur chiffré : valeur réelle, jamais de remplissage. */
export function Kpi({ label, value, hint, tone = "default" }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "default" | "danger" | "success" }) {
  return (
    <Card padding="md" className="space-y-1">
      <p className="text-xs font-semibold text-ash">{label}</p>
      <p className={`font-display text-2xl font-bold ${tone === "danger" ? "text-dangerInk" : tone === "success" ? "text-successInk" : "text-ink"}`}>{value}</p>
      {hint ? <p className="text-xs text-ash">{hint}</p> : null}
    </Card>
  );
}

/** Barre de progression d'un budget : couleur selon le niveau réel. */
export function Progress({ percent, level }: { percent: number; level: "ok" | "warning" | "exceeded" }) {
  const color = level === "exceeded" ? "bg-danger" : level === "warning" ? "bg-warning" : "bg-primary";
  return (
    <div className="h-2.5 overflow-hidden rounded-full bg-lineSoft" role="progressbar" aria-valuenow={Math.min(100, Math.round(percent))} aria-valuemin={0} aria-valuemax={100}>
      <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(100, percent)}%` }} />
    </div>
  );
}

/** Histogramme horizontal simple (dépenses par site / mois). */
export function Bars({ rows, format }: { rows: { label: string; value: number }[]; format: (n: number) => string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="space-y-2.5">
      {rows.map((r) => (
        <li key={r.label} className="space-y-1">
          <div className="flex justify-between gap-3 text-sm">
            <span className="truncate font-medium text-ink">{r.label}</span>
            <span className="shrink-0 text-inkSoft">{format(r.value)}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-lineSoft"><div className="h-full rounded-full bg-primary" style={{ width: `${(r.value / max) * 100}%` }} /></div>
        </li>
      ))}
    </ul>
  );
}
