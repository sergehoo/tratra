import { Card, CardHeader } from "@/components/ds";
import type { Passport } from "@/lib/trust";
import { SourceTag } from "./SourceTag";

/** Anneau du score : valeur réelle uniquement. */
export function ScoreRing({ value, size = 112 }: { value: number; size?: number }) {
  const r = 46;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }} role="img" aria-label={`Score de confiance ${value} sur 100`}>
      <svg viewBox="0 0 112 112" className="h-full w-full -rotate-90">
        <circle cx="56" cy="56" r={r} className="fill-none stroke-lineSoft" strokeWidth="9" />
        <circle
          cx="56"
          cy="56"
          r={r}
          className="fill-none stroke-primary"
          strokeWidth="9"
          strokeLinecap="round"
          strokeDasharray={`${(c * value) / 100} ${c}`}
        />
      </svg>
      <div className="absolute text-center">
        <p className="font-display text-3xl font-bold leading-none text-ink">{value}</p>
        <p className="mt-0.5 text-[11px] font-semibold text-ash">sur 100</p>
      </div>
    </div>
  );
}

/** Explication du score : chaque composante, son poids réel et sa provenance. Aucune donnée manquante n'est comptée comme un zéro. */
export function ScoreBreakdown({ passport }: { passport: Passport }) {
  const { score } = passport;
  return (
    <Card as="section" aria-label="Score de confiance" className="space-y-5">
      <CardHeader
        title="Score de confiance"
        description="Calculé par Tratra à partir de données réelles — jamais saisi, jamais acheté."
      />
      {score.value != null ? (
        <div className="flex flex-wrap items-center gap-5">
          <ScoreRing value={score.value} />
          <div className="min-w-0 flex-1 space-y-1">
            <p className="text-sm text-inkSoft">
              Fiabilité de la mesure : <strong className="text-ink">{score.confidence}</strong>
            </p>
            <p className="text-xs leading-relaxed text-ash">{score.note}</p>
          </div>
        </div>
      ) : (
        <p className="rounded-panel bg-canvas p-4 text-sm leading-relaxed text-inkSoft">
          {score.reason || "Le score sera publié dès que l’activité mesurée sera suffisante."}
        </p>
      )}
      <ul className="space-y-3">
        {score.components.map((c) => (
          <li key={c.key} className="space-y-1.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold text-ink">{c.label}</p>
              <SourceTag source={c.source} />
            </div>
            {c.available ? (
              <>
                <div className="h-2 overflow-hidden rounded-full bg-lineSoft" role="presentation">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round((c.ratio ?? 0) * 100)}%` }} />
                </div>
                <p className="text-xs text-ash">
                  {c.detail}
                  {c.points != null && c.max_points != null ? (
                    <>
                      {" "}· <strong className="text-inkSoft">{String(c.points).replace(".", ",")} / {String(c.max_points).replace(".", ",")} pts</strong>
                    </>
                  ) : null}
                </p>
              </>
            ) : (
              <p className="text-xs text-ash">{c.detail || "Pas encore mesurable."} — non comptée, sans pénalité.</p>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
