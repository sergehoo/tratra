import { statusView, type StatusKind } from "@/lib/status";
import { Badge } from "./Badge";

/** Badge de statut métier (réservation, document KYC, litige, abonnement). */
export function StatusBadge({
  kind,
  status,
  className,
}: {
  kind: StatusKind;
  status: string | null | undefined;
  className?: string;
}) {
  const v = statusView(kind, status);
  return (
    <Badge tone={v.tone} dot pulse={v.pulse} className={className}>
      {v.label}
    </Badge>
  );
}
