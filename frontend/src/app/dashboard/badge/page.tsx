"use client";
import { useState } from "react";
import { Check, Copy, Download, ExternalLink, IdCard } from "lucide-react";
import { Alert, Avatar, Button, ButtonLink, Card, CardHeader, EmptyState, PageHeader, SkeletonPage } from "@/components/ds";
import { TrustBadges } from "@/components/trust/TrustBadge";
import { privateFileUrl } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard";
import type { MyTratraId } from "@/lib/tratraId";
import { useData } from "@/lib/useData";

export default function BadgePage() {
  const dash = useDashboard();
  const provider = dash.data?.capabilities.provider;
  const { data, error } = useData<MyTratraId>(provider ? "/me/tratra-id/" : null, "Votre badge ne peut pas être chargé.");
  const [copied, setCopied] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [pdfError, setPdfError] = useState("");

  if (dash.loading || (provider && !data && !error)) return <SkeletonPage />;
  if (!data) {
    return (
      <>
        <PageHeader eyebrow="Espace artisan" title="Mon badge Tratra ID" />
        {error ? <Alert tone="danger">{error}</Alert> : null}
        {!provider ? (
          <EmptyState
            title="Aucun profil artisan"
            description="Le badge Tratra ID est délivré aux artisans : proposez vos services pour l’obtenir."
            actions={<ButtonLink href="/dashboard/provide">Proposer un service</ButtonLink>}
          />
        ) : null}
      </>
    );
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(data!.verify_url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  async function download() {
    setPdfBusy(true);
    setPdfError("");
    try {
      const url = await privateFileUrl("/me/tratra-id/badge.pdf");
      const a = document.createElement("a");
      a.href = url;
      a.download = `tratra-id-${data!.tratra_id}.pdf`;
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch {
      setPdfError("Le badge imprimable n’est pas disponible pour le moment.");
    } finally {
      setPdfBusy(false);
    }
  }

  const active = data.valid;
  return (
    <>
      <PageHeader
        eyebrow="Espace artisan"
        title="Mon badge Tratra ID"
        description="Votre identité professionnelle vérifiable : les clients scannent le QR pour confirmer en direct que vous êtes bien vérifié par Tratra."
      />
      {!active ? <Alert tone="warning" title="Badge suspendu" className="mb-6">{data.message}</Alert> : null}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5 lg:items-start">
        <Card padding="none" className="overflow-hidden lg:col-span-3">
          <div className="flex items-center justify-between bg-primary px-5 py-3 text-white">
            <span className="font-display text-lg font-bold">Tratra</span>
            <span className="text-[11px] font-bold uppercase tracking-[0.16em]">Identité professionnelle</span>
          </div>
          <div className="h-1.5 bg-accent" />
          <div className="flex flex-col gap-6 p-5 sm:flex-row sm:items-start">
            <div className="flex min-w-0 flex-1 items-start gap-4">
              <Avatar name={data.holder.display_name} photo={data.holder.photo} size={88} />
              <div className="min-w-0 space-y-2">
                <p className="font-display text-xl font-bold text-ink">{data.holder.display_name}</p>
                {data.holder.trades.length ? <p className="text-sm text-inkSoft">{data.holder.trades.join(", ")}</p> : null}
                <TrustBadges badges={data.holder.badges} />
                <p className="pt-2 text-[11px] font-bold uppercase tracking-[0.16em] text-ash">Tratra ID</p>
                <p className="font-mono text-xl font-bold tracking-wide text-primaryDark">{data.tratra_id}</p>
                <p className="text-xs text-ash">
                  {data.holder.kyc_verified_on
                    ? `Identité vérifiée le ${new Date(data.holder.kyc_verified_on).toLocaleDateString("fr-FR")}`
                    : "Identité non vérifiée"}
                </p>
              </div>
            </div>
            <div className="mx-auto shrink-0 text-center">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={data.qr}
                alt={`QR de vérification Tratra ID ${data.tratra_id}`}
                className={`h-44 w-44 rounded-panel border border-lineSoft bg-white p-2 ${active ? "" : "opacity-40 grayscale"}`}
              />
              <p className="mt-1 text-xs font-semibold text-inkSoft">{active ? "Scannez pour vérifier" : "Badge suspendu"}</p>
            </div>
          </div>
        </Card>

        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader icon={<IdCard className="h-5 w-5" />} title="Utiliser mon badge" description="Le QR ne contient aucune donnée sensible : il renvoie vers la page de vérification Tratra." />
            <div className="space-y-3">
              <Button type="button" block size="lg" loading={pdfBusy} disabled={!data.pdf_available} leftIcon={<Download aria-hidden className="h-4 w-4" />} onClick={download}>
                Télécharger le badge (PDF)
              </Button>
              <Button type="button" block variant="outline" leftIcon={copied ? <Check aria-hidden className="h-4 w-4" /> : <Copy aria-hidden className="h-4 w-4" />} onClick={copy}>
                {copied ? "Lien copié" : "Copier le lien de vérification"}
              </Button>
              <ButtonLink href={`/verify/${data.tratra_id}`} variant="ghost" block rightIcon={<ExternalLink aria-hidden className="h-4 w-4" />}>
                Voir ce que verra le client
              </ButtonLink>
              {pdfError ? <Alert tone="danger">{pdfError}</Alert> : null}
              {!data.pdf_available ? <p className="text-xs text-ash">Le badge imprimable redevient disponible dès que votre identité est vérifiée.</p> : null}
            </div>
          </Card>
          <Card variant="soft">
            <p className="font-display text-base font-bold text-ink">QR de mission</p>
            <p className="mt-1 text-sm text-ash">
              À chaque intervention, affichez le QR de mission depuis la page de la mission : il est temporaire (15 min), à usage unique et lié à la réservation.
            </p>
          </Card>
        </div>
      </div>
    </>
  );
}
