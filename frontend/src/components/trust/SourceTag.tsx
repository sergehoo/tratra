import { BadgeCheck, Activity, UserRound } from "lucide-react";
import { SOURCE_LABEL, type DataSource } from "@/lib/trust";

const ICON = { vérifié: BadgeCheck, plateforme: Activity, déclaré: UserRound } as const;
const STYLE: Record<DataSource, string> = {
  vérifié: "bg-primarySoft text-primaryDark",
  plateforme: "bg-infoSoft text-infoInk",
  déclaré: "bg-lineSoft text-inkSoft",
};

/** Provenance d'une information : vérifiée par Tratra, mesurée sur la plateforme ou simplement déclarée. */
export function SourceTag({ source, className = "" }: { source: DataSource; className?: string }) {
  const Icon = ICON[source];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${STYLE[source]} ${className}`}>
      <Icon aria-hidden className="h-3 w-3" />
      {SOURCE_LABEL[source]}
    </span>
  );
}
