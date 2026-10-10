import type { ReactNode } from "react";
import { Award, CalendarDays, Clock3, Hourglass, MapPin, ShieldCheck, Star, UserCheck } from "lucide-react";
import { Avatar, Card, CardHeader } from "@/components/ds";
import { BADGE_INFO, formatMinutes, formatPercent, type Passport } from "@/lib/trust";
import { ScoreBreakdown } from "./ScoreBreakdown";
import { SourceTag } from "./SourceTag";
import { TrustBadges } from "./TrustBadge";

function longDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }) : "";
}

export function BadgeHistory({ history }: { history: Passport["history"] }) {
  return (
    <Card as="section" aria-label="Historique des badges">
      <CardHeader title="Historique des badges" description="Chaque badge est attribué et retiré automatiquement ; l’historique est conservé." />
      {history.length ? (
        <ol className="mt-4 space-y-3">
          {history.map((h, i) => (
            <li key={`${h.code}-${i}`} className="flex gap-3 text-sm">
              <span aria-hidden className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${h.ended_at ? "bg-fog" : "bg-primary"}`} />
              <div>
                <p className="font-semibold text-ink">
                  {BADGE_INFO[h.code]?.label ?? h.label}
                  <span className="ml-2 text-xs font-medium text-ash">{h.ended_at ? "retiré" : "actif"}</span>
                </p>
                <p className="text-xs text-ash">
                  depuis le {longDate(h.started_at)}
                  {h.ended_at ? ` · jusqu’au ${longDate(h.ended_at)}` : ""}
                </p>
                {h.ended_at && h.end_reason ? <p className="mt-0.5 text-xs text-inkSoft">{h.end_reason}</p> : null}
                {!h.ended_at && h.start_reason ? <p className="mt-0.5 text-xs text-inkSoft">{h.start_reason}</p> : null}
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-3 text-sm text-ash">Aucun badge attribué pour le moment.</p>
      )}
    </Card>
  );
}

function Fact({ icon, label, value, hint, source }: { icon: ReactNode; label: string; value: ReactNode; hint?: string; source: Passport["experience"]["source"] }) {
  return (
    <div className="rounded-panel bg-canvas p-4">
      <p className="flex items-center gap-1.5 text-xs font-semibold text-ash [&>svg]:h-4 [&>svg]:w-4 [&>svg]:text-primary">
        {icon}
        {label}
      </p>
      <p className="mt-1 font-display text-2xl font-bold text-ink">{value}</p>
      {hint ? <p className="mt-0.5 text-xs text-ash">{hint}</p> : null}
      <SourceTag source={source} className="mt-2" />
    </div>
  );
}

/** Passeport professionnel (public ou propriétaire) : identité, badges, score expliqué, compétences, chiffres, historique. */
export function PassportView({ passport: p, actions, children }: { passport: Passport; actions?: ReactNode; children?: ReactNode }) {
  const memberSince = new Date(p.member_since).toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
  return (
    <div className="space-y-6">
      <Card as="section" aria-label="Identité professionnelle" padding="lg">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
          <div className="shrink-0">
            <Avatar name={p.display_name} photo={p.photo} size={84} />
          </div>
          <div className="min-w-0 flex-1 space-y-2">
            <h1 className="font-display text-2xl font-bold text-ink sm:text-3xl">{p.display_name}</h1>
            <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ash">
              {p.commune ? (
                <span className="inline-flex items-center gap-1.5">
                  <MapPin aria-hidden className="h-4 w-4 text-primary" />
                  {p.commune}
                </span>
              ) : null}
              <span className="inline-flex items-center gap-1.5">
                <CalendarDays aria-hidden className="h-4 w-4 text-primary" />
                Membre depuis {memberSince}
              </span>
            </p>
            <TrustBadges badges={p.badges} />
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-inkSoft">
              <span className="inline-flex items-center gap-2">
                <UserCheck aria-hidden className="h-4 w-4 shrink-0 text-primary" />
                {p.identity.verified ? (
                  <>Identité vérifiée par Tratra{p.identity.verified_on ? ` le ${longDate(p.identity.verified_on)}` : ""}</>
                ) : (
                  "Identité non vérifiée"
                )}
              </span>
              <SourceTag source={p.identity.source} />
            </p>
          </div>
          {actions ? <div className="flex w-full flex-wrap gap-2 sm:w-auto [&>*]:w-full sm:[&>*]:w-auto">{actions}</div> : null}
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5 lg:items-start">
        <div className="space-y-6 lg:col-span-3">
          <Card as="section" aria-label="Chiffres clés">
            <CardHeader title="Chiffres clés" description="Mesurés sur les interventions réelles réalisées via Tratra." />
            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Fact icon={<Award aria-hidden />} label="Missions terminées" value={p.missions.completed}
                hint={`${p.missions.completed_window} sur les ${p.missions.window_days} derniers jours`} source={p.missions.source} />
              <Fact icon={<Star aria-hidden />} label="Satisfaction" value={p.satisfaction.average != null ? `${String(p.satisfaction.average).replace(".", ",")}/5` : "—"}
                hint={p.satisfaction.count ? `${p.satisfaction.count} avis de clients` : "Pas encore d’avis"} source={p.satisfaction.source} />
              <Fact icon={<Clock3 aria-hidden />} label="Ponctualité" value={formatPercent(p.punctuality.rate)}
                hint={p.punctuality.rate != null ? `${p.punctuality.on_time} / ${p.punctuality.sample} missions à l’heure (tolérance ${p.punctuality.tolerance_minutes} min)` : `Pas encore assez de missions mesurées (${p.punctuality.sample}/${p.punctuality.min_sample})`} source={p.punctuality.source} />
              <Fact icon={<Hourglass aria-hidden />} label="Réactivité" value={formatMinutes(p.reactivity.median_minutes)}
                hint={p.reactivity.median_minutes != null ? `Délai médian de réponse · ${p.reactivity.sample} demandes` : `Pas encore assez de demandes traitées (${p.reactivity.sample}/${p.reactivity.min_sample})`} source={p.reactivity.source} />
            </div>
            <p className="mt-3 text-xs text-ash">
              Expérience déclarée : <strong className="text-inkSoft">{p.experience.years} an{p.experience.years > 1 ? "s" : ""}</strong> · <SourceTag source={p.experience.source} />
            </p>
          </Card>

          <Card as="section" aria-label="Compétences">
            <CardHeader title="Compétences" description="Les compétences certifiées sont appuyées par un justificatif approuvé par l’équipe Tratra." />
            <div className="mt-4 space-y-4">
              <div>
                <h3 className="mb-2 flex items-center gap-2 text-sm font-bold text-ink">
                  <ShieldCheck aria-hidden className="h-4 w-4 text-primary" /> Certifiées
                </h3>
                {p.skills.certified.length ? (
                  <ul className="space-y-2">
                    {p.skills.certified.map((c) => (
                      <li key={c.id} className="rounded-panel border border-lineSoft p-3">
                        <p className="text-sm font-semibold text-ink">{c.title}</p>
                        <p className="text-xs text-ash">
                          {[c.category?.name, c.issuer, c.issued_on ? `délivré le ${longDate(c.issued_on)}` : "", c.expires_on ? `valable jusqu’au ${longDate(c.expires_on)}` : ""]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                        <SourceTag source={c.source} className="mt-1.5" />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-ash">Aucun justificatif approuvé pour le moment.</p>
                )}
              </div>
              <div>
                <h3 className="mb-2 text-sm font-bold text-ink">Déclarées</h3>
                {p.skills.declared.length ? (
                  <ul className="flex flex-wrap gap-1.5">
                    {p.skills.declared.map((s) => (
                      <li key={s.id} className="rounded-full bg-lineSoft px-2.5 py-1 text-xs font-medium text-inkSoft">{s.name}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-ash">Aucune spécialité renseignée.</p>
                )}
                <SourceTag source="déclaré" className="mt-2" />
              </div>
            </div>
          </Card>

          {children}
        </div>

        <div className="space-y-6 lg:col-span-2">
          <ScoreBreakdown passport={p} />
          <BadgeHistory history={p.history} />
        </div>
      </div>
    </div>
  );
}
