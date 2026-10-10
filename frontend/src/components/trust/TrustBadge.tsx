import { Award, BadgeCheck, ShieldCheck, Sparkles } from "lucide-react";
import { Badge, type BadgeTone } from "@/components/ds/Badge";
import { BADGE_INFO, type BadgeCode, type PublicBadge } from "@/lib/trust";

const STYLE: Record<BadgeCode, { tone: BadgeTone; Icon: typeof BadgeCheck }> = {
  NOUVEAU: { tone: "gray", Icon: Sparkles },
  VERIFIE: { tone: "primary", Icon: BadgeCheck },
  EXPERT: { tone: "accent", Icon: Award },
  SUR: { tone: "night", Icon: ShieldCheck },
};

/** Un badge Tratra Trust (jamais saisi : attribué par le serveur à partir de données réelles). */
export function TrustBadge({ code, className = "" }: { code: BadgeCode; className?: string }) {
  const { tone, Icon } = STYLE[code];
  return (
    <span title={BADGE_INFO[code].help} className="inline-flex">
      <Badge tone={tone} icon={<Icon />} className={className}>
        {BADGE_INFO[code].label}
      </Badge>
    </span>
  );
}

/** Badges ACTUELS d'un artisan, cumulables. N'affiche rien s'il n'y en a aucun. */
export function TrustBadges({ badges, className = "" }: { badges?: PublicBadge[] | null; className?: string }) {
  const known = (badges ?? []).filter((b) => b.code in BADGE_INFO);
  if (!known.length) return null;
  return (
    <ul className={`flex flex-wrap items-center gap-1.5 ${className}`} aria-label="Badges Tratra">
      {known.map((b) => (
        <li key={b.code}>
          <TrustBadge code={b.code} />
        </li>
      ))}
    </ul>
  );
}

/** Score de confiance sur 100 ; rien tant qu'il n'est pas calculable (jamais de chiffre inventé). */
export function TrustScorePill({ score, className = "" }: { score?: number | null; className?: string }) {
  if (score == null) return null;
  return (
    <span
      title="Score de confiance Tratra, calculé à partir de données réelles (détail sur la fiche de l'artisan)."
      className={`inline-flex items-center gap-1 rounded-full bg-lineSoft px-2.5 py-1 text-xs font-semibold text-ink ${className}`}
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-primary" />
      Confiance {score}/100
    </span>
  );
}
