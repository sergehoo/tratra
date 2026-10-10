"use client";
import { Check, Circle, ExternalLink } from "lucide-react";
import { Alert, ButtonLink, Card, CardHeader, EmptyState, PageHeader, SkeletonPage } from "@/components/ds";
import { useDashboard } from "@/lib/dashboard";
import { useData } from "@/lib/useData";
import { formatCriterion, type OwnerTrust } from "@/lib/trust";
import { CertificationForm } from "@/components/trust/CertificationForm";
import { BadgeHistory } from "@/components/trust/PassportView";
import { ScoreBreakdown } from "@/components/trust/ScoreBreakdown";
import { SourceTag } from "@/components/trust/SourceTag";
import { TrustBadges } from "@/components/trust/TrustBadge";

const CERT_STATUS: Record<string, string> = { pending: "En attente de validation", rejected: "Refusé" };

export default function ReputationPage() {
  const dash = useDashboard();
  const provider = dash.data?.capabilities.provider;
  // Le passeport n'existe que pour un compte disposant d'un profil artisan : pas d'appel (ni d'erreur 404) sinon.
  const { data, error, reload } = useData<OwnerTrust>(provider ? "/me/trust/" : null, "Votre réputation ne peut pas être chargée.");

  if (dash.loading || (provider && !data && !error)) return <SkeletonPage />;
  if (!data) {
    return (
      <>
        <PageHeader eyebrow="Espace artisan" title="Ma réputation" />
        {error ? <Alert tone="danger">{error}</Alert> : null}
        {!provider ? (
          <EmptyState
            title="Aucun profil artisan"
            description="Proposez vos services pour obtenir un passeport professionnel, des badges et un score de confiance."
            actions={<ButtonLink href="/dashboard/provide">Proposer un service</ButtonLink>}
          />
        ) : null}
      </>
    );
  }

  const verified = data.identity.verified;
  return (
    <>
      <PageHeader
        eyebrow="Espace artisan"
        title="Ma réputation"
        description="Vos badges et votre score sont calculés automatiquement à partir de données réelles : vérification d’identité, justificatifs approuvés, missions, avis et ponctualité."
        actions={
          verified ? (
            <ButtonLink href={`/artisans/${data.profile_id}`} variant="outline" rightIcon={<ExternalLink aria-hidden className="h-4 w-4" />}>
              Voir ma fiche publique
            </ButtonLink>
          ) : null
        }
      />

      <div className="mb-6 flex flex-wrap items-center gap-3">
        {data.badges.length ? <TrustBadges badges={data.badges} /> : <p className="text-sm text-ash">Aucun badge actif pour le moment.</p>}
      </div>

      {!verified ? (
        <Alert tone="warning" title="Votre identité n’est pas encore vérifiée" className="mb-6">
          Les badges Vérifié, Expert et Sûr — et la publication de votre fiche — dépendent exclusivement de la vérification d’identité (KYC) par l’équipe Tratra.
          <span className="mt-2 block">
            <ButtonLink href="/dashboard/profile/kyc" size="sm" variant="outline">Compléter mon dossier</ButtonLink>
          </span>
        </Alert>
      ) : null}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5 lg:items-start">
        <div className="space-y-6 lg:col-span-3">
          {!verified ? (
            <Card as="section" aria-label="Dossier à compléter">
              <CardHeader title="Ce qu’il reste à faire" description="Chaque étape est contrôlée par l’équipe Tratra." />
              <ul className="space-y-2">
                {data.checklist.map((c) => (
                  <li key={c.key} className="flex items-start gap-3 text-sm">
                    {c.done ? <Check aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-success" /> : <Circle aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-fog" />}
                    <div>
                      <p className={c.done ? "font-medium text-inkSoft" : "font-semibold text-ink"}>{c.label}</p>
                      {!c.done ? <p className="text-xs text-ash">{c.hint}</p> : null}
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}

          {(["EXPERT", "SUR"] as const).map((code) => {
            const nb = data.next_badges[code];
            const met = nb.criteria.filter((c) => c.met).length;
            return (
              <Card as="section" key={code} aria-label={`Critères du badge ${nb.label}`}>
                <CardHeader
                  title={`Badge ${nb.label}`}
                  description={
                    nb.earned
                      ? "Badge actif — il est réévalué automatiquement et retiré si les critères ne sont plus atteints."
                      : !verified
                        ? "Disponible après la vérification de votre identité."
                        : `${met} critère${met > 1 ? "s" : ""} sur ${nb.criteria.length} atteint${met > 1 ? "s" : ""}.`
                  }
                />
                <ul className="space-y-2.5">
                  {nb.criteria.map((c) => (
                    <li key={c.key} className="flex items-start gap-3 text-sm">
                      {c.met ? <Check aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-success" /> : <Circle aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-fog" />}
                      <div className="min-w-0 flex-1">
                        <p className="font-semibold text-ink">{c.label}</p>
                        <p className="text-xs text-ash">{formatCriterion(c)}</p>
                      </div>
                      <SourceTag source={c.source} />
                    </li>
                  ))}
                </ul>
              </Card>
            );
          })}

          {data.pending_certifications.length ? (
            <Card as="section" aria-label="Justificatifs en cours">
              <CardHeader title="Justificatifs en cours" description="Seuls les justificatifs approuvés comptent pour le badge Expert." />
              <ul className="space-y-2 text-sm">
                {data.pending_certifications.map((c) => (
                  <li key={c.id} className="flex items-center justify-between gap-3 rounded-panel bg-canvas px-3 py-2">
                    <span className="font-medium text-ink">{c.title || "Justificatif"}</span>
                    <span className="text-xs font-semibold text-ash">{CERT_STATUS[c.status] ?? c.status}</span>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}

          <CertificationForm onSent={() => void reload()} />
        </div>

        <div className="space-y-6 lg:col-span-2">
          <ScoreBreakdown passport={data} />
          <BadgeHistory history={data.history} />
        </div>
      </div>
    </>
  );
}
