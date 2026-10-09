import type { ReactNode } from "react";
import { Clock, FileText, FileX, ShieldCheck, type LucideIcon } from "lucide-react";
import { Alert, Card, StatusBadge } from "@/components/ds";
import { formatSentDate } from "./documents";

/** Pastille d'icône selon le statut réel du document (l'écusson n'apparaît que pour un document validé). */
const TILE: Record<string, { icon: LucideIcon; box: string }> = {
  pending: { icon: Clock, box: "bg-accentSoft text-accentDark" },
  approved: { icon: ShieldCheck, box: "bg-successSoft text-successInk" },
  rejected: { icon: FileX, box: "bg-dangerSoft text-dangerInk" },
};
const FALLBACK_TILE = { icon: FileText, box: "bg-primarySoft text-primary" };

/**
 * Carte d'un document KYC, partagée par l'espace artisan (dépôt) et le back-office (revue) :
 * type, statut français, date d'envoi, motif de rejet réel et actions fournies par la page.
 */
export function KycDocumentCard({
  title,
  status,
  uploadedAt,
  byline,
  note,
  rejectionReason,
  audience,
  actions,
  children,
}: {
  title: string;
  status: string;
  uploadedAt?: string | null;
  /** Qui a envoyé le document (back-office). */
  byline?: ReactNode;
  /** Information neutre sous la date (ex. « en cours d’examen »). */
  note?: ReactNode;
  rejectionReason?: string | null;
  audience: "worker" | "admin";
  actions?: ReactNode;
  /** Messages contextuels additionnels (erreur d'action…). */
  children?: ReactNode;
}) {
  const tile = TILE[status] ?? FALLBACK_TILE;
  const Icon = tile.icon;
  const sent = formatSentDate(uploadedAt);
  const reason = rejectionReason?.trim();

  return (
    <Card as="article" padding="md" radius="card">
      <div className="flex items-start gap-4">
        <span aria-hidden className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl ${tile.box}`}>
          <Icon className="h-6 w-6" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
            <h3 className="min-w-0 font-display text-base font-bold leading-snug text-ink">{title}</h3>
            <StatusBadge kind="document" status={status} />
          </div>
          {byline ? <div className="mt-1.5 text-sm text-inkSoft">{byline}</div> : null}
          {sent ? <p className="mt-1 text-xs text-ash">Envoyé le {sent}</p> : null}
          {note ? <p className="mt-2 text-sm leading-relaxed text-inkSoft">{note}</p> : null}
        </div>
      </div>

      {status === "rejected" ? (
        <Alert tone="danger" title={audience === "worker" ? "Pièce refusée" : "Motif du refus"} className="mt-4">
          <span className="whitespace-pre-line break-words">
            {reason ||
              (audience === "worker"
                ? "Aucun motif n’a été indiqué. Vous pouvez déposer une nouvelle pièce."
                : "Aucun motif n’a été indiqué.")}
          </span>
        </Alert>
      ) : null}

      {children ? <div className="mt-4 space-y-3">{children}</div> : null}

      {actions ? <div className="mt-4 flex flex-wrap gap-2 border-t border-lineSoft pt-4">{actions}</div> : null}
    </Card>
  );
}
