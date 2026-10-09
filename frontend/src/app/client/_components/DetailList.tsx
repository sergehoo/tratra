import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cx } from "@/components/ds";

export interface DetailItem {
  label: string;
  value: ReactNode;
  icon?: LucideIcon;
}

/** Liste « libellé / valeur » (réservation, récapitulatif) : <dl> sémantique, rangées séparées par un filet. */
export function DetailList({ items, className = "" }: { items: DetailItem[]; className?: string }) {
  return (
    <dl className={cx("divide-y divide-lineSoft", className)}>
      {items.map(({ label, value, icon: Icon }) => (
        <div key={label} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
          {Icon ? (
            <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-primarySoft text-primary">
              <Icon className="h-[18px] w-[18px]" />
            </span>
          ) : null}
          <div className="min-w-0 flex-1">
            <dt className="text-eyebrow uppercase text-ash">{label}</dt>
            <dd className="mt-1 break-words text-sm font-medium leading-snug text-ink">{value}</dd>
          </div>
        </div>
      ))}
    </dl>
  );
}
