import type { ReactNode } from "react";
import { BadgeCheck, CircleAlert, ShieldAlert } from "lucide-react";
import { Avatar, Card } from "@/components/ds";
import type { IdHolder } from "@/lib/tratraId";
import { TrustBadges } from "./TrustBadge";

type Tone = "ok" | "danger" | "warn";
const TONE: Record<Tone, { box: string; icon: string; Icon: typeof BadgeCheck }> = {
  ok: { box: "border-success/30 bg-successSoft", icon: "text-success", Icon: BadgeCheck },
  danger: { box: "border-danger/30 bg-dangerSoft", icon: "text-danger", Icon: ShieldAlert },
  warn: { box: "border-warning/30 bg-warningSoft", icon: "text-warning", Icon: CircleAlert },
};

/** Résultat d'une vérification d'identité professionnelle : décision lisible d'un coup d'œil, puis le détail. */
export function VerifyCard({
  tone,
  title,
  message,
  holder,
  tratraId,
  children,
}: {
  tone: Tone;
  title: string;
  message: string;
  holder?: IdHolder;
  tratraId?: string;
  children?: ReactNode;
}) {
  const { box, icon, Icon } = TONE[tone];
  return (
    <Card padding="lg" className="space-y-5">
      <div role={tone === "ok" ? "status" : "alert"} className={`flex items-start gap-3 rounded-panel border p-4 ${box}`}>
        <Icon aria-hidden className={`mt-0.5 h-6 w-6 shrink-0 ${icon}`} />
        <div>
          <h1 className="font-display text-xl font-bold text-ink">{title}</h1>
          <p className="mt-1 text-sm text-inkSoft">{message}</p>
        </div>
      </div>

      {holder ? (
        <div className="flex items-start gap-4">
          <Avatar name={holder.display_name} photo={holder.photo} size={72} />
          <div className="min-w-0 space-y-2">
            <p className="font-display text-lg font-bold text-ink">{holder.display_name}</p>
            {holder.trades.length ? <p className="text-sm text-inkSoft">{holder.trades.join(", ")}</p> : null}
            {holder.commune ? <p className="text-xs text-ash">{holder.commune}</p> : null}
            <TrustBadges badges={holder.badges} />
          </div>
        </div>
      ) : null}

      {tratraId ? (
        <p className="text-xs text-ash">
          Tratra ID : <strong className="font-mono text-sm tracking-wide text-ink">{tratraId}</strong>
          {holder?.kyc_verified_on ? ` · identité vérifiée le ${new Date(holder.kyc_verified_on).toLocaleDateString("fr-FR")}` : ""}
        </p>
      ) : null}
      {children}
    </Card>
  );
}
