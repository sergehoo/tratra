"use client";
import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { CheckCircle2, MapPin, Wrench } from "lucide-react";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";
import { RoleGuard } from "@/components/RoleGuard";
import { Alert, Badge, ButtonLink, Card, CardHeader, EmptyState, Skeleton } from "@/components/ds";
import { NewRequestForm } from "@/components/business/NewRequestForm";
import { BusinessProvider, type BizRequest, type Equipment } from "@/lib/business";
import { useData } from "@/lib/useData";

interface Lookup extends Equipment { organization: number; organization_name: string; can_request: boolean; open_requests: number }

function Scan({ code }: { code: string }) {
  const router = useRouter();
  const { data, loading } = useData<Lookup>(`/business/equipment/lookup/${encodeURIComponent(code)}/`);
  const [created, setCreated] = useState<BizRequest | null>(null);
  if (loading) return <Skeleton className="h-72 w-full !rounded-card" />;
  if (!data) return <EmptyState icon={<Wrench aria-hidden />} title="Équipement introuvable" description="Ce QR n’existe pas, ou l’équipement n’appartient pas à une organisation dont vous êtes membre." actions={<ButtonLink href="/dashboard/business">Tratra Business</ButtonLink>} />;
  return (
    <div className="space-y-6">
      <Card padding="lg" as="section" aria-label="Équipement">
        <p className="text-xs font-bold uppercase tracking-[0.16em] text-ash">{data.organization_name}</p>
        <h1 className="mt-1 font-display text-2xl font-bold text-ink">{data.name}</h1>
        <p className="mt-1 flex items-center gap-1.5 text-sm text-inkSoft"><MapPin aria-hidden className="h-4 w-4 text-primary" />{data.site_name}{data.location_detail ? ` · ${data.location_detail}` : ""}</p>
        <div className="mt-3 flex flex-wrap items-center gap-2"><Badge tone="gray">{data.qr_code}</Badge>{data.open_requests ? <Badge tone="warning">{data.open_requests} demande(s) ouverte(s)</Badge> : <Badge tone="success">Aucune demande ouverte</Badge>}</div>
      </Card>
      {created ? (
        <Alert tone="success" icon={<CheckCircle2 aria-hidden className="h-4 w-4" />} title={`Demande ${created.number} envoyée`} action={<ButtonLink size="sm" href={`/dashboard/business/requests/${created.id}`}>Suivre</ButtonLink>}>
          {created.status === "pending_approval" ? "Elle est en attente de validation." : "Elle est validée et sera confiée à un artisan."}
        </Alert>
      ) : data.can_request ? (
        <Card padding="lg" as="section" aria-label="Signaler un problème">
          <CardHeader title="Signaler un problème" description="Décrivez ce qui ne va pas : la demande suit le circuit de validation de votre organisation." />
          <NewRequestForm orgId={data.organization} fromQr initial={{ site: data.site, equipment: data.id, category: data.category }} onCreated={(r) => { setCreated(r); router.refresh(); }} />
        </Card>
      ) : <Alert tone="info">Votre rôle ne permet pas de créer une demande sur cet équipement.</Alert>}
    </div>
  );
}

export default function EquipmentPage() {
  const { code } = useParams<{ code: string }>();
  return (
    <>
      <SiteHeader variant="solid" />
      <main id="contenu" tabIndex={-1} className="min-h-screen bg-canvas py-8 outline-none sm:py-12">
        <div className="mx-auto w-full max-w-xl px-4 sm:px-6">
          <RoleGuard>
            <BusinessProvider><Scan code={code} /></BusinessProvider>
          </RoleGuard>
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
