"use client";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Plus } from "lucide-react";
import { Alert, Button, DataTable, EmptyState, Modal, PageHeader, Tabs, type Column } from "@/components/ds";
import { money, shortDate, useBusiness, useOrgData, type BizRequest } from "@/lib/business";
import { NewRequestForm } from "@/components/business/NewRequestForm";
import { PriorityPill, StatusPill } from "@/components/business/ui";

type Scope = "all" | "mine" | "to_approve" | "open";
const STATUS_QS: Record<Scope, string> = { all: "", mine: "mine=1", to_approve: "to_approve=1", open: "" };

function RequestsPage() {
  const { can, org } = useBusiness();
  const router = useRouter();
  const params = useSearchParams();
  const [scope, setScope] = useState<Scope>(can("requests.view_all") ? "all" : "mine");
  const [creating, setCreating] = useState(false);
  useEffect(() => { if (params.get("new") === "1" && can("requests.create")) setCreating(true); }, [params, can]);
  const qs = STATUS_QS[scope];
  const { data, loading, error, reload } = useOrgData<{ results: BizRequest[]; count: number }>(`requests/?page_size=50${qs ? `&${qs}` : ""}`, "Les demandes ne peuvent pas être chargées.");
  const rows = (data?.results ?? []).filter((r) => scope !== "open" || ["pending_approval", "approved", "dispatched", "scheduled", "in_progress"].includes(r.status));

  const columns: Column<BizRequest>[] = [
    { key: "n", header: "N°", primary: true, cell: (r) => <span><span className="font-mono text-xs text-ash">{r.number}</span><span className="block font-semibold text-ink">{r.title}</span></span> },
    { key: "site", header: "Site / équipement", cell: (r) => <span>{r.site_name}{r.equipment_name ? <span className="block text-xs text-ash">{r.equipment_name}</span> : null}</span> },
    { key: "prio", header: "Priorité", cell: (r) => <PriorityPill priority={r.priority} /> },
    { key: "st", header: "Statut", cell: (r) => <span className="flex items-center gap-2"><StatusPill status={r.status} />{r.can_decide ? <span className="text-xs font-bold text-warningInk">À valider</span> : null}</span> },
    { key: "by", header: "Demandeur", hideOnMobile: true, cell: (r) => r.requested_by_name },
    { key: "cost", header: "Coût", align: "right", hideOnMobile: true, cell: (r) => money(r.cost ?? r.estimated_cost, org?.currency) },
    { key: "d", header: "Créée le", hideOnMobile: true, cell: (r) => shortDate(r.created_at) },
  ];
  const tabs = [
    ...(can("requests.view_all") ? [{ id: "all" as const, label: "Toutes" }, { id: "open" as const, label: "Ouvertes" }] : []),
    { id: "mine" as const, label: "Mes demandes" },
    ...(can("requests.approve") ? [{ id: "to_approve" as const, label: "À valider" }] : []),
  ];
  return (
    <>
      <PageHeader
        eyebrow="Tratra Business"
        title="Demandes d’intervention"
        description="Chaque demande suit la validation prévue par votre organisation, puis est confiée à un artisan vérifié."
        actions={can("requests.create") ? <Button leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => setCreating(true)}>Nouvelle demande</Button> : null}
      />
      <Tabs ariaLabel="Filtrer les demandes" items={tabs} value={scope} onChange={setScope} className="mb-4" />
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <DataTable
        caption="Demandes d’intervention"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        rowHref={(r) => `/dashboard/business/requests/${r.id}`}
        loading={loading}
        empty={<EmptyState title="Aucune demande" description="Rien à afficher pour ce filtre." />}
      />
      <Modal open={creating} onClose={() => setCreating(false)} title="Nouvelle demande d’intervention" size="lg">
        <NewRequestForm
          onCreated={(r) => {
            setCreating(false);
            void reload();
            router.push(`/dashboard/business/requests/${r.id}`);
          }}
        />
      </Modal>
    </>
  );
}

export default function Page() {
  return (
    <Suspense fallback={null}>
      <RequestsPage />
    </Suspense>
  );
}
